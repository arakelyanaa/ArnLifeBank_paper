"""
PubMed search and XML fetch via NCBI E-utilities.

Responsibilities:
  - Search PubMed with a broad Armenia[Affiliation] query per year
  - Fetch full PubMed XML records in batches
  - Retry on transient errors with exponential back-off
  - Cache every response to avoid redundant API calls
  - Return structured per-article dicts ready for the affiliation classifier
"""

from __future__ import annotations

import logging
import time
import xml.etree.ElementTree as ET
from typing import Iterator, Optional

import requests
from Bio import Entrez

from armlifebank.cache import Cache
from armlifebank.config import Config

logger = logging.getLogger(__name__)

# NCBI E-utilities base URL
_EBASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"


# ── Entrez initialisation ─────────────────────────────────────────────────────

def init_entrez(cfg: Config) -> None:
    Entrez.email = cfg.ncbi_email
    Entrez.tool = cfg.ncbi_tool
    if cfg.ncbi_api_key:
        Entrez.api_key = cfg.ncbi_api_key


# ── Low-level retry wrapper ───────────────────────────────────────────────────

def _fetch_with_retry(fn, cfg: Config, *args, **kwargs):
    """Call *fn* (a Bio.Entrez call) with exponential back-off on failure."""
    delay = cfg.retry_backoff
    for attempt in range(1, cfg.max_retries + 1):
        try:
            time.sleep(cfg.rate_delay)
            return fn(*args, **kwargs)
        except Exception as exc:
            if attempt == cfg.max_retries:
                raise
            logger.warning("Attempt %d/%d failed (%s). Retrying in %.1fs…",
                           attempt, cfg.max_retries, exc, delay)
            time.sleep(delay)
            delay *= 2


# ── Search ────────────────────────────────────────────────────────────────────

def search_year(year: int, cfg: Config, cache: Cache) -> list[str]:
    """
    Return a list of PMIDs matching the Armenia affiliation query for *year*.
    Results are cached so repeated runs do not re-query.
    """
    cache_key = f"search:{year}"
    cached = cache.get(cache_key)
    if cached is not None:
        logger.info("[%d] Using cached search results (%d PMIDs).", year, len(cached))
        return cached

    query = cfg.query_template.format(year=year)
    logger.info("[%d] Searching PubMed: %s", year, query)

    handle = _fetch_with_retry(
        Entrez.esearch, cfg,
        db="pubmed", term=query, retmax=100_000, usehistory="n"
    )
    record = Entrez.read(handle)
    handle.close()

    ids: list[str] = list(record["IdList"])
    total = int(record["Count"])
    logger.info("[%d] PubMed reports %d hits; retrieved %d PMIDs.", year, total, len(ids))

    cache.set(cache_key, ids)
    return ids


# ── XML fetch ─────────────────────────────────────────────────────────────────

def _fetch_xml_batch(pmids: list[str], cfg: Config) -> str:
    """Fetch raw PubMed XML for a list of PMIDs. Returns XML string."""
    handle = _fetch_with_retry(
        Entrez.efetch, cfg,
        db="pubmed",
        id=",".join(pmids),
        rettype="xml",
        retmode="xml",
    )
    xml_bytes = handle.read()
    handle.close()
    # Entrez may return bytes or str
    if isinstance(xml_bytes, bytes):
        return xml_bytes.decode("utf-8", errors="replace")
    return xml_bytes


def fetch_records(
    pmids: list[str],
    cfg: Config,
    cache: Cache,
) -> Iterator[dict]:
    """
    Yield one parsed article dict per PMID.
    Fetches in batches; caches XML by PMID so individual records survive
    partial runs. Yields in the same order as *pmids*.
    """
    # Split into batches
    to_fetch: list[str] = []
    for pmid in pmids:
        if not cache.has(f"pubmed_xml:{pmid}"):
            to_fetch.append(pmid)

    logger.info("Fetching XML for %d/%d PMIDs (rest cached).", len(to_fetch), len(pmids))

    for i in range(0, len(to_fetch), cfg.batch_size):
        batch = to_fetch[i: i + cfg.batch_size]
        logger.debug("Fetching batch %d–%d…", i + 1, i + len(batch))
        try:
            xml_str = _fetch_xml_batch(batch, cfg)
        except Exception as exc:
            logger.error("Batch fetch failed for PMIDs %s…: %s", batch[:3], exc)
            # Cache None so we don't retry in this run
            for pmid in batch:
                cache.set(f"pubmed_xml:{pmid}", None)
            continue

        # Parse and cache individual records
        try:
            root = ET.fromstring(xml_str.encode("utf-8"))
        except ET.ParseError as exc:
            logger.error("XML parse error for batch starting %s: %s", batch[0], exc)
            for pmid in batch:
                cache.set(f"pubmed_xml:{pmid}", None)
            continue

        fetched_pmids = set()
        for article_el in root.findall(".//PubmedArticle"):
            pmid_el = article_el.find(".//PMID")
            if pmid_el is None:
                continue
            pmid = pmid_el.text.strip()
            fetched_pmids.add(pmid)
            # Store per-PMID XML snippet as string
            record_xml = ET.tostring(article_el, encoding="unicode")
            cache.set(f"pubmed_xml:{pmid}", record_xml)

        # Mark any PMIDs not returned as None
        for pmid in batch:
            if pmid not in fetched_pmids:
                logger.warning("PMID %s not found in batch XML response.", pmid)
                cache.set(f"pubmed_xml:{pmid}", None)

        logger.info("  cached %d/%d records in this batch.", len(fetched_pmids), len(batch))

    # Now yield parsed dicts from cache for all requested PMIDs
    for pmid in pmids:
        record_xml = cache.get(f"pubmed_xml:{pmid}")
        if not record_xml:
            yield {"pmid": pmid, "_fetch_error": True}
            continue
        try:
            parsed = _parse_article_xml(record_xml)
            yield parsed
        except Exception as exc:
            logger.warning("Failed to parse XML for PMID %s: %s", pmid, exc)
            yield {"pmid": pmid, "_parse_error": str(exc)}


# ── XML parsing ───────────────────────────────────────────────────────────────

def _text(el: Optional[ET.Element]) -> str:
    return el.text.strip() if el is not None and el.text else ""


def _parse_article_xml(xml_str: str) -> dict:
    """
    Parse a single <PubmedArticle> XML string into a structured dict.

    Extracted fields:
      pmid, title, journal, journal_abbrev, volume, issue, pages,
      pub_year, pub_month,
      doi, pmcid,
      authors: [{last, fore, affiliations: [str]}],
      all_affiliations: [str],         ← flat list across all authors
      pub_types: [str],
      mesh_terms: [str],
      keywords: [str],
      databanks: [{name, accessions:[str]}],   ← from DataBankList
      abstract: str,
    """
    root = ET.fromstring(xml_str.encode("utf-8"))
    medline = root.find("MedlineCitation")
    article = medline.find("Article") if medline is not None else None

    # ── IDs ──────────────────────────────────────────────────────────────
    pmid = _text(medline.find("PMID")) if medline is not None else ""
    doi = ""
    pmcid = ""
    id_list = root.find(".//ArticleIdList")
    if id_list is not None:
        for aid in id_list.findall("ArticleId"):
            id_type = aid.get("IdType", "")
            val = _text(aid)
            if id_type == "doi":
                doi = val
            elif id_type == "pmc":
                pmcid = val

    # ── Bibliographic ────────────────────────────────────────────────────
    journal_el = article.find("Journal") if article is not None else None
    journal = _text(journal_el.find("Title")) if journal_el is not None else ""
    journal_abbrev = _text(journal_el.find("ISOAbbreviation")) if journal_el is not None else ""

    ji = journal_el.find("JournalIssue") if journal_el is not None else None
    volume = _text(ji.find("Volume")) if ji is not None else ""
    issue = _text(ji.find("Issue")) if ji is not None else ""
    pages = ""
    pagination = article.find("Pagination") if article is not None else None
    if pagination is not None:
        pages = _text(pagination.find("MedlinePgn"))

    pub_year, pub_month = "", ""
    if ji is not None:
        pd = ji.find("PubDate")
        if pd is not None:
            pub_year = _text(pd.find("Year")) or _text(pd.find("MedlineDate"))[:4]
            pub_month = _text(pd.find("Month"))

    title = _text(article.find("ArticleTitle")) if article is not None else ""

    # ── Abstract ─────────────────────────────────────────────────────────
    abstract = ""
    if article is not None:
        abs_el = article.find("Abstract")
        if abs_el is not None:
            parts = [_text(t) for t in abs_el.findall("AbstractText")]
            abstract = " ".join(p for p in parts if p)

    # ── Authors & affiliations ────────────────────────────────────────────
    authors = []
    all_affiliations: list[str] = []
    author_list_el = article.find("AuthorList") if article is not None else None
    if author_list_el is not None:
        for auth in author_list_el.findall("Author"):
            last = _text(auth.find("LastName"))
            fore = _text(auth.find("ForeName"))
            affs = [
                _text(ai.find("Affiliation"))
                for ai in auth.findall("AffiliationInfo")
                if auth.find("AffiliationInfo") is not None
            ]
            # AffiliationInfo may be nested differently
            affs = [_text(ai) for ai in auth.findall(".//Affiliation") if ai.text]
            authors.append({"last": last, "fore": fore, "affiliations": affs})
            all_affiliations.extend(affs)

    # Also collect affiliations from top-level AffiliationInfo (some records)
    for aff_el in (medline.findall(".//AffiliationInfo/Affiliation") if medline is not None else []):
        val = _text(aff_el)
        if val and val not in all_affiliations:
            all_affiliations.append(val)

    # ── Publication types ─────────────────────────────────────────────────
    pub_types: list[str] = []
    if article is not None:
        for pt in article.findall(".//PublicationType"):
            pub_types.append(_text(pt))

    # ── MeSH ─────────────────────────────────────────────────────────────
    mesh_terms: list[str] = []
    if medline is not None:
        for mh in medline.findall(".//MeshHeading/DescriptorName"):
            mesh_terms.append(_text(mh))

    # ── Keywords ─────────────────────────────────────────────────────────
    keywords: list[str] = []
    if medline is not None:
        for kw in medline.findall(".//KeywordList/Keyword"):
            keywords.append(_text(kw))

    # ── DataBankList (PubMed-curated accessions) ──────────────────────────
    databanks: list[dict] = []
    if article is not None:
        for db_el in article.findall(".//DataBankList/DataBank"):
            db_name = _text(db_el.find("DataBankName"))
            accessions = [_text(a) for a in db_el.findall(".//AccessionNumber") if a.text]
            databanks.append({"name": db_name, "accessions": accessions})

    return {
        "pmid": pmid,
        "doi": doi,
        "pmcid": pmcid,
        "title": title,
        "abstract": abstract,
        "journal": journal,
        "journal_abbrev": journal_abbrev,
        "volume": volume,
        "issue": issue,
        "pages": pages,
        "pub_year": pub_year,
        "pub_month": pub_month,
        "authors": authors,
        "all_affiliations": all_affiliations,
        "pub_types": pub_types,
        "mesh_terms": mesh_terms,
        "keywords": keywords,
        "databanks": databanks,
    }


# ── Convenience: fetch all years ──────────────────────────────────────────────

def fetch_all_years(cfg: Config, cache: Cache) -> list[dict]:
    """
    Search and fetch PubMed XML for all configured years.
    Returns a flat list of article dicts (one per PMID, deduplicated).
    Respects cfg.sample_size if set.
    """
    init_entrez(cfg)
    all_pmids: list[str] = []
    seen: set[str] = set()

    for year in range(cfg.start_year, cfg.end_year + 1):
        ids = search_year(year, cfg, cache)
        for pmid in ids:
            if pmid not in seen:
                seen.add(pmid)
                all_pmids.append(pmid)

    logger.info("Total unique PMIDs across all years: %d", len(all_pmids))

    if cfg.sample_size is not None:
        logger.info("Sample mode: limiting to first %d PMIDs.", cfg.sample_size)
        all_pmids = all_pmids[: cfg.sample_size]

    articles = list(fetch_records(all_pmids, cfg, cache))
    errors = sum(1 for a in articles if a.get("_fetch_error") or a.get("_parse_error"))
    if errors:
        logger.warning("%d articles had fetch/parse errors.", errors)

    return articles
