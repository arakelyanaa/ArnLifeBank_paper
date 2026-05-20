"""
Open Access full-text retrieval for the ArmLifeBank pipeline.

For each validated Armenia-country article this module:
  1. Resolves PMCID (from PubMed XML → PMC ID Converter API → ELink fallback)
  2. Checks PMC OA availability via the PMC OA service
  3. Downloads machine-readable full text via:
       a. JATS XML from PMC OA FTP package links
       b. BioC XML/JSON from the NCBI BioC API
       c. Europe PMC full-text XML as a last resort
  4. Caches every network call by PMID/PMCID
  5. Records failure reason when retrieval is not possible

All scraping of arbitrary publisher HTML/PDF pages is intentionally avoided.
"""

from __future__ import annotations

import logging
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import Optional

import requests
from Bio import Entrez

from armlifebank.cache import Cache
from armlifebank.config import Config

logger = logging.getLogger(__name__)

# ── API endpoints ─────────────────────────────────────────────────────────────
_IDCONV_URL   = "https://www.ncbi.nlm.nih.gov/pmc/utils/idconv/v1.0/"
_PMC_OA_URL   = "https://www.ncbi.nlm.nih.gov/pmc/utils/oa/oa.fcgi"
_BIOC_URL     = "https://www.ncbi.nlm.nih.gov/research/biopubchem/api/rest/bioc/pubmed/{pmid}/unicode"
_EUROPEPMC_FT = "https://europepmc.org/api/articleFulltextXML"

# Known retrieval failure reasons (used as status strings in output)
STATUS_NO_PMCID          = "no_pmcid"
STATUS_NOT_PMC_LIVE      = "pmcid_not_live"
STATUS_NOT_OA            = "not_in_oa_subset"
STATUS_OA_NO_XML         = "oa_metadata_found_no_xml"
STATUS_NETWORK_ERROR     = "network_or_api_error"
STATUS_OK                = "ok"


# ── Result dataclass ──────────────────────────────────────────────────────────

@dataclass
class FullTextResult:
    pmid: str
    doi: str = ""
    pmcid: str = ""
    has_pmcid: bool = False
    is_pmc_live: bool = False
    is_pmc_oa: bool = False
    oa_license: str = ""
    full_text_source: str = ""          # "pmc_oa_jats" | "bioc" | "europepmc" | ""
    full_text_cached_path: str = ""     # relative path inside cache dir
    full_text_retrieval_status: str = STATUS_NO_PMCID
    full_text_xml: str = ""             # in-memory XML string (not serialised to CSV)
    errors: list[str] = field(default_factory=list)


# ── HTTP helper ───────────────────────────────────────────────────────────────

def _get(url: str, params: dict, cfg: Config, timeout: int = 30) -> requests.Response:
    """GET with rate-limiting and retries.

    404 / 4xx responses are NOT retried — they indicate the resource does not
    exist and retrying would only waste time and quota.  Only 5xx responses and
    connection / timeout errors trigger the exponential back-off retry loop.
    """
    delay = cfg.retry_backoff
    for attempt in range(1, cfg.max_retries + 1):
        time.sleep(cfg.rate_delay)
        try:
            r = requests.get(url, params=params, timeout=timeout,
                             headers={"User-Agent": f"{cfg.ncbi_tool}/1.0 ({cfg.ncbi_email})"})
            # 4xx → permanent failure, do not retry
            if 400 <= r.status_code < 500:
                r.raise_for_status()   # raises immediately, exits the loop
            r.raise_for_status()       # raises on 5xx too
            return r
        except requests.HTTPError as exc:
            # 4xx: re-raise immediately without retry
            if exc.response is not None and exc.response.status_code < 500:
                raise
            if attempt == cfg.max_retries:
                raise
            logger.warning("HTTP attempt %d/%d for %s failed: %s. Retrying in %.1fs…",
                           attempt, cfg.max_retries, url, exc, delay)
            time.sleep(delay)
            delay *= 2
        except requests.RequestException as exc:
            # Connection errors, timeouts — retry these
            if attempt == cfg.max_retries:
                raise
            logger.warning("HTTP attempt %d/%d for %s failed: %s. Retrying in %.1fs…",
                           attempt, cfg.max_retries, url, exc, delay)
            time.sleep(delay)
            delay *= 2


# ── Step 1: PMCID resolution ──────────────────────────────────────────────────

def resolve_pmcid(pmid: str, doi: str, pmcid_from_xml: str,
                  cfg: Config, cache: Cache) -> str:
    """
    Return a PMCID string (e.g. "PMC1234567") or "" if unavailable.

    Resolution order:
      1. PMCID already extracted from PubMed XML
      2. PMC ID Converter API (batch-friendly, called per-PMID here for simplicity)
      3. Entrez ELink pubmed→pmc
    """
    if pmcid_from_xml:
        # Normalise: ensure "PMC" prefix
        return pmcid_from_xml if pmcid_from_xml.startswith("PMC") else f"PMC{pmcid_from_xml}"

    cache_key = f"pmcid_lookup:{pmid}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    # ── PMC ID Converter ─────────────────────────────────────────────────
    try:
        params: dict = {
            "ids": pmid,
            "format": "json",
            "tool": cfg.ncbi_tool,
            "email": cfg.ncbi_email,
        }
        if cfg.ncbi_api_key:
            params["api_key"] = cfg.ncbi_api_key
        r = _get(_IDCONV_URL, params, cfg)
        data = r.json()
        records = data.get("records", [])
        if records:
            pmcid = records[0].get("pmcid", "")
            if pmcid:
                cache.set(cache_key, pmcid)
                return pmcid
    except Exception as exc:
        logger.debug("ID Converter failed for PMID %s: %s", pmid, exc)

    # ── ELink PubMed → PMC fallback ──────────────────────────────────────
    try:
        time.sleep(cfg.rate_delay)
        handle = Entrez.elink(dbfrom="pubmed", db="pmc", id=pmid)
        record = Entrez.read(handle)
        handle.close()
        for linkset in record:
            for linksetdb in linkset.get("LinkSetDb", []):
                if linksetdb.get("DbTo") == "pmc":
                    ids = [str(l["Id"]) for l in linksetdb.get("Link", [])]
                    if ids:
                        pmcid = f"PMC{ids[0]}"
                        cache.set(cache_key, pmcid)
                        return pmcid
    except Exception as exc:
        logger.debug("ELink failed for PMID %s: %s", pmid, exc)

    cache.set(cache_key, "")
    return ""


# ── Step 2: PMC OA check ──────────────────────────────────────────────────────

@dataclass
class OAMeta:
    is_live: bool = False
    is_oa: bool = False
    license: str = ""
    jats_url: str = ""     # direct link to JATS XML tar.gz or XML
    pdf_url: str = ""


def check_pmc_oa(pmcid: str, cfg: Config, cache: Cache) -> OAMeta:
    """Query the PMC OA service for *pmcid*. Returns OAMeta."""
    cache_key = f"oa_check:{pmcid}"
    cached = cache.get(cache_key)
    if cached is not None:
        return OAMeta(**cached)

    meta = OAMeta()
    try:
        # PMC OA service only supports XML; do NOT pass format=json
        params: dict = {"id": pmcid}
        if cfg.ncbi_api_key:
            params["api_key"] = cfg.ncbi_api_key
        r = _get(_PMC_OA_URL, params, cfg)
        # OA service returns XML regardless of format param; parse it
        root = ET.fromstring(r.content)
        # <OA><records><record id="PMC…" license="…"><link format="tgz" …/></record></records></OA>
        error_el = root.find(".//error")
        if error_el is not None:
            # PMCID not found in PMC
            cache.set(cache_key, vars(meta))
            return meta

        record_el = root.find(".//record")
        if record_el is not None:
            meta.is_live = True
            meta.license = record_el.get("license", "")
            meta.is_oa = bool(meta.license)
            for link_el in record_el.findall("link"):
                fmt = link_el.get("format", "")
                href = link_el.get("href", "")
                if fmt in ("tgz", "xml") and not meta.jats_url:
                    meta.jats_url = href
                elif fmt == "pdf" and not meta.pdf_url:
                    meta.pdf_url = href

    except Exception as exc:
        logger.debug("PMC OA check failed for %s: %s", pmcid, exc)

    cache.set(cache_key, vars(meta))
    return meta


# ── Step 3a: JATS XML via PMC E-utilities efetch ─────────────────────────────

def _fetch_pmc_efetch(pmcid: str, cfg: Config, cache: Cache) -> str:
    """
    Retrieve full-text JATS XML for a PMC article via Entrez efetch (db=pmc).
    This is the primary NCBI-approved route for machine-readable PMC full text.
    Returns XML string or "".
    """
    cache_key = f"fulltext_efetch:{pmcid}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached
    try:
        time.sleep(cfg.rate_delay)
        handle = Entrez.efetch(db="pmc", id=pmcid, rettype="xml", retmode="xml")
        xml_bytes = handle.read()
        handle.close()
        xml_str = xml_bytes.decode("utf-8", errors="replace") if isinstance(xml_bytes, bytes) else xml_bytes
        if xml_str and len(xml_str) > 500:
            cache.set(cache_key, xml_str)
            return xml_str
    except Exception as exc:
        logger.debug("PMC efetch failed for %s: %s", pmcid, exc)
    cache.set(cache_key, "")
    return ""


# ── Step 3b: JATS XML from OA package link ────────────────────────────────────

def _fetch_jats_from_oa(pmcid: str, jats_url: str,
                        cfg: Config, cache: Cache) -> str:
    """
    Download JATS XML from a PMC OA link.
    Handles direct XML links; skips tgz (would require tarfile extraction –
    marks as OA_NO_XML to avoid binary downloads in this pipeline).
    Returns XML string or "".
    """
    if not jats_url:
        return ""
    # Only attempt direct XML links (not tgz archives)
    if jats_url.endswith(".tgz") or jats_url.endswith(".tar.gz"):
        logger.debug("PMCID %s OA link is a tgz archive; skipping direct download.", pmcid)
        return ""
    cache_key = f"fulltext_jats:{pmcid}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached
    try:
        r = _get(jats_url, {}, cfg)
        xml_str = r.text
        cache.set(cache_key, xml_str)
        return xml_str
    except Exception as exc:
        logger.debug("JATS fetch failed for %s: %s", pmcid, exc)
        return ""


# ── Step 3b: BioC XML via NCBI BioC API ──────────────────────────────────────

def _fetch_bioc(pmid: str, cfg: Config, cache: Cache) -> str:
    """
    Retrieve full text via the NCBI BioC API.
    Returns BioC XML string or "".
    Note: BioC coverage is limited to PMC OA articles; 404 is the normal
    response for articles not in the OA subset.
    """
    cache_key = f"fulltext_bioc:{pmid}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached
    url = _BIOC_URL.format(pmid=pmid)
    try:
        r = _get(url, {}, cfg)
        if r.status_code == 200 and "<collection" in r.text:
            cache.set(cache_key, r.text)
            return r.text
    except requests.HTTPError as exc:
        # 404 is expected for non-OA articles; log at debug only
        code = exc.response.status_code if exc.response is not None else 0
        logger.debug("BioC HTTP %s for PMID %s (not in OA subset).", code, pmid)
    except Exception as exc:
        logger.debug("BioC fetch failed for PMID %s: %s", pmid, exc)
    cache.set(cache_key, "")
    return ""


# ── Step 3c: Europe PMC full-text XML ────────────────────────────────────────

def _fetch_europepmc(pmid: str, cfg: Config, cache: Cache) -> str:
    """
    Retrieve full-text XML from Europe PMC.
    Returns XML string or "".
    404 is the normal response for articles not in the Europe PMC OA corpus.
    """
    cache_key = f"fulltext_europepmc:{pmid}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached
    try:
        params = {"id": pmid, "source": "MED"}
        r = _get(_EUROPEPMC_FT, params, cfg)
        if r.status_code == 200 and len(r.text) > 500:
            cache.set(cache_key, r.text)
            return r.text
    except requests.HTTPError as exc:
        code = exc.response.status_code if exc.response is not None else 0
        logger.debug("Europe PMC HTTP %s for PMID %s (not in OA corpus).", code, pmid)
    except Exception as exc:
        logger.debug("Europe PMC fetch failed for PMID %s: %s", pmid, exc)
    cache.set(cache_key, "")
    return ""


# ── Main per-article function ─────────────────────────────────────────────────

def resolve_fulltext(article: dict, cfg: Config, cache: Cache) -> FullTextResult:
    """
    Resolve full-text availability for one article dict (as returned by pubmed.py).
    Returns a populated FullTextResult.
    """
    pmid  = article.get("pmid", "")
    doi   = article.get("doi", "")
    pmcid_xml = article.get("pmcid", "")

    result = FullTextResult(pmid=pmid, doi=doi)

    # ── 1. Resolve PMCID ─────────────────────────────────────────────────
    pmcid = resolve_pmcid(pmid, doi, pmcid_xml, cfg, cache)
    result.pmcid = pmcid
    result.has_pmcid = bool(pmcid)

    if not pmcid:
        result.full_text_retrieval_status = STATUS_NO_PMCID
        # Still try BioC and Europe PMC as they sometimes work without PMCID
        xml = _fetch_bioc(pmid, cfg, cache)
        if xml:
            result.full_text_xml = xml
            result.full_text_source = "bioc"
            result.full_text_retrieval_status = STATUS_OK
            return result
        xml = _fetch_europepmc(pmid, cfg, cache)
        if xml:
            result.full_text_xml = xml
            result.full_text_source = "europepmc"
            result.full_text_retrieval_status = STATUS_OK
        return result

    # ── 2. PMC OA check ──────────────────────────────────────────────────
    oa_meta = check_pmc_oa(pmcid, cfg, cache)
    result.is_pmc_live = oa_meta.is_live
    result.is_pmc_oa   = oa_meta.is_oa
    result.oa_license  = oa_meta.license

    if not oa_meta.is_live:
        result.full_text_retrieval_status = STATUS_NOT_PMC_LIVE
        # Fallback attempts
        xml = _fetch_bioc(pmid, cfg, cache)
        if xml:
            result.full_text_xml = xml
            result.full_text_source = "bioc"
            result.full_text_retrieval_status = STATUS_OK
            return result
        xml = _fetch_europepmc(pmid, cfg, cache)
        if xml:
            result.full_text_xml = xml
            result.full_text_source = "europepmc"
            result.full_text_retrieval_status = STATUS_OK
        return result

    if not oa_meta.is_oa:
        result.full_text_retrieval_status = STATUS_NOT_OA
        return result

    # ── 3a. PMC efetch (primary: NCBI-approved, works for all PMC OA) ────
    xml = _fetch_pmc_efetch(pmcid, cfg, cache)
    if xml:
        result.full_text_xml = xml
        result.full_text_source = "pmc_efetch"
        result.full_text_retrieval_status = STATUS_OK
        return result

    # ── 3b. JATS XML from direct OA link (non-tgz only) ──────────────────
    xml = _fetch_jats_from_oa(pmcid, oa_meta.jats_url, cfg, cache)
    if xml:
        result.full_text_xml = xml
        result.full_text_source = "pmc_oa_jats"
        result.full_text_retrieval_status = STATUS_OK
        return result

    # ── 3c. BioC fallback ────────────────────────────────────────────────
    xml = _fetch_bioc(pmid, cfg, cache)
    if xml:
        result.full_text_xml = xml
        result.full_text_source = "bioc"
        result.full_text_retrieval_status = STATUS_OK
        return result

    # ── 3d. Europe PMC fallback ──────────────────────────────────────────
    xml = _fetch_europepmc(pmid, cfg, cache)
    if xml:
        result.full_text_xml = xml
        result.full_text_source = "europepmc"
        result.full_text_retrieval_status = STATUS_OK
        return result

    result.full_text_retrieval_status = STATUS_OA_NO_XML
    return result


# ── Batch processor ───────────────────────────────────────────────────────────

def resolve_fulltext_batch(
    articles: list[dict],
    cfg: Config,
    cache: Cache,
) -> list[FullTextResult]:
    """
    Process all articles. Returns one FullTextResult per article.
    Logs a progress line every 10 articles.
    """
    results: list[FullTextResult] = []
    total = len(articles)
    for i, article in enumerate(articles, 1):
        if i % 10 == 0 or i == total:
            logger.info("Full-text resolution: %d/%d…", i, total)
        try:
            res = resolve_fulltext(article, cfg, cache)
        except Exception as exc:
            pmid = article.get("pmid", "?")
            logger.error("Unexpected error resolving full text for PMID %s: %s", pmid, exc)
            res = FullTextResult(
                pmid=pmid,
                full_text_retrieval_status=STATUS_NETWORK_ERROR,
                errors=[str(exc)],
            )
        results.append(res)

    # Summary log
    n_ok      = sum(1 for r in results if r.full_text_retrieval_status == STATUS_OK)
    n_oa      = sum(1 for r in results if r.is_pmc_oa)
    n_pmcid   = sum(1 for r in results if r.has_pmcid)
    by_source: dict[str, int] = {}
    for r in results:
        if r.full_text_source:
            by_source[r.full_text_source] = by_source.get(r.full_text_source, 0) + 1

    logger.info(
        "Full-text summary: %d articles | %d with PMCID | %d PMC OA | "
        "%d full texts retrieved | sources: %s",
        total, n_pmcid, n_oa, n_ok, by_source,
    )
    return results
