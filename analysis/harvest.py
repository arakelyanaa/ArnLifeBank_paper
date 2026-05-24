#!/usr/bin/env python3
"""
Harvest — Module 1
==================
Builds a local index of every record in a SEEK-based data atlas (Leipzig
Health Atlas, ArmLifeBank, etc.) with enough metadata to enable identifier
matching.

Configured via a YAML file (default: config/lha.yaml).  Pass --config to
point at a different platform (e.g. config/arm.yaml).

Discovery order (configured in the YAML):
  1. dcat_endpoint   — /dcat, /catalog.ttl, /api/dcat  (HealthDCAT-AP / RDF)
  2. rest_api        — SEEK JSON:API via /data_files endpoint
  3. seek_json_api   — alias for rest_api; also harvests /publications endpoint
  4. sitemap_scrape  — /sitemap.xml → enumerate record pages → parse HTML

The first method that returns at least one record is used for the full run.
All raw responses are cached and never re-fetched unless --refresh is passed.

Per-record fields extracted into the index CSV:
  lha_id, lha_url, title, record_type, is_lha_hosted,
  external_dois, external_accessions, external_urls,
  linked_pmids, authors, created_date, modified_date, raw_path

Usage:
  python analysis/harvest.py                           # LHA full harvest
  python analysis/harvest.py --config config/arm.yaml  # ArmLifeBank harvest
  python analysis/harvest.py --limit 50                # probe: first 50 records
  python analysis/harvest.py --refresh                 # ignore cache, re-fetch
  python analysis/harvest.py --method sitemap_scrape   # force a specific method
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import time
import urllib.robotparser
from pathlib import Path
from typing import Optional
from urllib.parse import urljoin, urlparse

import requests
import yaml
from bs4 import BeautifulSoup

import pandas as pd

logger = logging.getLogger(__name__)

# ── Repo root + config ────────────────────────────────────────────────────────
_REPO_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_CONFIG = _REPO_ROOT / "config" / "lha.yaml"


def _load_config(path: Path) -> dict:
    with path.open(encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def _platform_key(cfg: dict) -> str:
    """Return the top-level platform key ('lha', 'arm', …)."""
    structural = {"target", "output", "cache", "comparators"}
    for key in cfg:
        if key not in structural:
            return key
    raise KeyError("No platform key found in config (expected 'lha' or 'arm').")


def _index_path(cfg: dict) -> Path:
    """Return the output index CSV path, tolerating both 'index' and legacy 'lha_index' keys."""
    out = cfg["output"]
    rel = out.get("index") or out.get("lha_index")
    if not rel:
        raise KeyError("config['output'] must have an 'index' or 'lha_index' key.")
    return _REPO_ROOT / rel


def _cache_dir(cfg: dict, platform_key: str) -> Path:
    """Return the raw-cache directory for this platform."""
    cache = cfg["cache"]
    rel = cache.get(f"{platform_key}_raw_dir") or cache.get("lha_raw_dir")
    if not rel:
        raise KeyError(f"No raw_dir found in config['cache'] for platform '{platform_key}'.")
    return _REPO_ROOT / rel


# ── Known repository accession URL patterns ───────────────────────────────────
# Used when parsing external links from HTML pages.
_REPO_URL_PATTERNS: list[tuple[str, str]] = [
    (r"ncbi\.nlm\.nih\.gov/geo/query.*acc=([A-Z]+\d+)",          "Gene Expression Omnibus"),
    (r"ncbi\.nlm\.nih\.gov/nuccore/([A-Z]{1,6}\d+)",             "GenBank"),
    (r"ncbi\.nlm\.nih\.gov/bioproject/([A-Z]+\d+)",              "BioProject"),
    (r"ncbi\.nlm\.nih\.gov/biosample/([A-Z]+\d+)",               "BioSample"),
    (r"ncbi\.nlm\.nih\.gov/sra/([SDE]R[RSPX]\d+)",               "SRA"),
    (r"ebi\.ac\.uk/pride/archive.*PXD\d+",                       "PRIDE"),
    (r"(PXD\d{6})",                                               "PRIDE"),
    (r"rcsb\.org/structure/([A-Z0-9]{4})",                        "PDB"),
    (r"ebi\.ac\.uk/ena/.*([A-Z]{2}\d{6})",                        "ENA"),
    (r"ega-archive\.org.*([EG]GA[A-Z]\d+)",                       "EGA"),
    (r"clinicaltrials\.gov/.*?(NCT\d{8})",                        "ClinicalTrials.gov"),
    (r"zenodo\.org/(?:record|records|doi)/(.+)",                   "Zenodo"),
    (r"figshare\.com/articles/.*?/(\d+)",                          "Figshare"),
    (r"osf\.io/([a-z0-9]{5})",                                     "OSF"),
    (r"github\.com/([\w.\-]+/[\w.\-]+)",                           "GitHub"),
    (r"gitlab\.com/([\w.\-]+/[\w.\-]+)",                           "GitLab"),
]
_REPO_PATTERNS_COMPILED = [
    (re.compile(pat, re.IGNORECASE), repo)
    for pat, repo in _REPO_URL_PATTERNS
]

_PMID_RE   = re.compile(r"pubmed\.ncbi\.nlm\.nih\.gov/(\d{5,9})")
_DOI_RE_FULL = re.compile(r"10\.\d{4,}/[^\s\"'<>]+")


# ── HTTP session with rate limiting ───────────────────────────────────────────

class RateLimitedSession:
    """requests.Session wrapper that enforces a minimum delay between requests."""

    def __init__(self, user_agent: str, rps: float = 1.0):
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": user_agent})
        self._min_interval = 1.0 / rps
        self._last_request_time: float = 0.0

    def get(self, url: str, **kwargs) -> requests.Response:
        elapsed = time.monotonic() - self._last_request_time
        wait = self._min_interval - elapsed
        if wait > 0:
            time.sleep(wait)
        try:
            resp = self.session.get(url, timeout=kwargs.pop("timeout", 30), **kwargs)
            return resp
        finally:
            self._last_request_time = time.monotonic()


# ── Cache ─────────────────────────────────────────────────────────────────────

class RawCache:
    """File-based cache for raw HTTP responses. Key → filename mapping is stable."""

    def __init__(self, cache_dir: Path, force_refresh: bool = False):
        self.cache_dir = cache_dir
        self.force_refresh = force_refresh
        cache_dir.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        safe = re.sub(r"[^\w\-.]", "_", key)[:180]
        return self.cache_dir / safe

    def has(self, key: str) -> bool:
        return not self.force_refresh and self._path(key).exists()

    def read(self, key: str) -> str:
        return self._path(key).read_text(encoding="utf-8", errors="replace")

    def write(self, key: str, content: str | bytes) -> Path:
        path = self._path(key)
        if isinstance(content, bytes):
            path.write_bytes(content)
        else:
            path.write_text(content, encoding="utf-8")
        return path

    def path(self, key: str) -> Path:
        return self._path(key)


# ── robots.txt ────────────────────────────────────────────────────────────────

def _load_robots(base_url: str, session: RateLimitedSession,
                 cache: RawCache) -> urllib.robotparser.RobotFileParser:
    robots_url = urljoin(base_url, "/robots.txt")
    key = "robots.txt"
    if not cache.has(key):
        try:
            resp = session.get(robots_url)
            cache.write(key, resp.text if resp.ok else "")
        except Exception as exc:
            logger.warning("Could not fetch robots.txt: %s", exc)
            cache.write(key, "")
    rp = urllib.robotparser.RobotFileParser()
    rp.set_url(robots_url)
    rp.parse(cache.read(key).splitlines())
    return rp


def _can_fetch(rp: urllib.robotparser.RobotFileParser,
               user_agent: str, url: str) -> bool:
    try:
        return rp.can_fetch(user_agent, url)
    except Exception:
        return True   # if in doubt, allow (we already checked robots.txt)


# ── Record parser — HTML ──────────────────────────────────────────────────────

def _parse_html_record(lha_id: str, lha_url: str, html: str) -> dict:
    """
    Parse one LHA record HTML page into a structured dict.
    Extracts external DOIs, accessions, URLs, and linked PMIDs from
    link hrefs, text content, and common metadata patterns.
    """
    soup = BeautifulSoup(html, "lxml")

    # ── Title ─────────────────────────────────────────────────────────────
    title = ""
    og_title = soup.find("meta", property="og:title")
    if og_title and og_title.get("content"):
        title = og_title["content"].strip()
    if not title:
        h1 = soup.find("h1")
        if h1:
            title = h1.get_text(" ", strip=True)
    if not title:
        t = soup.find("title")
        if t:
            title = t.get_text(" ", strip=True)

    # ── Record type ───────────────────────────────────────────────────────
    record_type = "unknown"
    # LHA URLs often contain type hints: /lha/datasets/..., /lha/models/...
    path = urlparse(lha_url).path.lower()
    for rtype in ("dataset", "model", "phenotype", "tool", "cohort", "study"):
        if rtype in path:
            record_type = rtype
            break
    # Also check breadcrumbs / page badges
    if record_type == "unknown":
        badge = soup.find(class_=re.compile(r"badge|label|tag|type", re.I))
        if badge:
            record_type = badge.get_text(strip=True).lower() or "unknown"

    # ── Collect all outbound links ────────────────────────────────────────
    all_links: list[str] = []
    for tag in soup.find_all("a", href=True):
        href = tag["href"].strip()
        if href.startswith("http"):
            all_links.append(href)

    # Also scan raw text for DOIs not wrapped in <a> tags
    page_text = soup.get_text(" ")

    # ── External DOIs ─────────────────────────────────────────────────────
    external_dois: list[str] = []
    # From link hrefs
    for href in all_links:
        if "doi.org" in href:
            m = _DOI_RE_FULL.search(href)
            if m:
                external_dois.append(m.group(0).lower().rstrip(".,;)>\"'"))
    # From page text (bare DOIs not in links)
    for m in _DOI_RE_FULL.finditer(page_text):
        candidate = m.group(0).lower().rstrip(".,;)>\"'")
        if candidate not in external_dois:
            external_dois.append(candidate)
    external_dois = list(dict.fromkeys(external_dois))   # deduplicate, preserve order

    # ── External accessions ───────────────────────────────────────────────
    external_accessions: list[dict] = []
    seen_accessions: set[str] = set()
    for href in all_links:
        for pat, repo in _REPO_PATTERNS_COMPILED:
            m = pat.search(href)
            if m:
                acc = m.group(1) if m.lastindex else href
                key = f"{repo}:{acc}"
                if key not in seen_accessions:
                    seen_accessions.add(key)
                    external_accessions.append({"repository": repo, "accession": acc})

    # ── External URLs (non-DOI, non-PMID outbound links) ─────────────────
    base_host = urlparse(lha_url).netloc
    external_urls: list[str] = []
    for href in all_links:
        host = urlparse(href).netloc
        if host and host != base_host and "doi.org" not in host:
            if not _PMID_RE.search(href):
                external_urls.append(href)
    external_urls = list(dict.fromkeys(external_urls))

    # ── Linked PMIDs ──────────────────────────────────────────────────────
    linked_pmids: list[str] = []
    # From link hrefs
    for href in all_links:
        m = _PMID_RE.search(href)
        if m:
            linked_pmids.append(m.group(1))
    # From text (e.g. "PMID: 12345678" or "PubMed ID: 12345678")
    for m in re.finditer(r"(?:PMID|PubMed\s+ID)[:\s]+(\d{5,9})", page_text, re.I):
        linked_pmids.append(m.group(1))
    linked_pmids = list(dict.fromkeys(linked_pmids))

    # ── Authors ───────────────────────────────────────────────────────────
    authors: list[str] = []
    # Common metadata patterns
    for meta in soup.find_all("meta"):
        name = meta.get("name", "").lower()
        if "author" in name:
            content = meta.get("content", "").strip()
            if content:
                authors.append(content)

    # ── Dates ─────────────────────────────────────────────────────────────
    created_date = modified_date = ""
    for meta in soup.find_all("meta"):
        prop = (meta.get("property") or meta.get("name") or "").lower()
        content = meta.get("content", "").strip()
        if "created" in prop or "published" in prop:
            created_date = content
        if "modified" in prop or "updated" in prop:
            modified_date = content

    # ── is_lha_hosted ─────────────────────────────────────────────────────
    # If there are no external DOIs, accessions, or repo URLs → data is LHA-hosted
    is_lha_hosted = (
        not external_dois
        and not external_accessions
        and not any(
            any(pat.search(u) for pat, _ in _REPO_PATTERNS_COMPILED)
            for u in external_urls
        )
    )

    return {
        "lha_id":               lha_id,
        "lha_url":              lha_url,
        "title":                title,
        "record_type":          record_type,
        "is_lha_hosted":        is_lha_hosted,
        "external_dois":        json.dumps(external_dois),
        "external_accessions":  json.dumps(external_accessions),
        "external_urls":        json.dumps(external_urls[:50]),   # cap at 50 to avoid huge cells
        "linked_pmids":         json.dumps(linked_pmids),
        "authors":              json.dumps(authors),
        "created_date":         created_date,
        "modified_date":        modified_date,
    }


# ── Discovery method: DCAT endpoint ──────────────────────────────────────────

def _try_dcat(base_url: str, session: RateLimitedSession,
              cache: RawCache) -> list[dict]:
    """Try DCAT / RDF catalog endpoints. Returns list of parsed records or []."""
    candidates = [
        urljoin(base_url, "/dcat"),
        urljoin(base_url, "/catalog.ttl"),
        urljoin(base_url, "/api/dcat"),
        urljoin(base_url, "/api/catalog.ttl"),
    ]
    for url in candidates:
        key = f"dcat_{url.replace('/', '_')}"
        try:
            if not cache.has(key):
                resp = session.get(url, headers={"Accept": "text/turtle, application/rdf+xml, */*"})
                if not resp.ok:
                    logger.debug("DCAT %s → HTTP %d", url, resp.status_code)
                    continue
                cache.write(key, resp.text)
            content = cache.read(key)
            # Quick check: does it look like RDF/DCAT?
            if not any(tok in content for tok in ("dcat:", "dcat#", "@prefix", "<rdf:")):
                logger.debug("DCAT %s → not RDF content", url)
                continue
            logger.info("DCAT endpoint found: %s", url)
            return _parse_dcat_rdf(content, base_url)
        except Exception as exc:
            logger.debug("DCAT %s → %s", url, exc)
    return []


def _parse_dcat_rdf(content: str, base_url: str) -> list[dict]:
    """Parse Turtle/RDF DCAT response into record dicts."""
    try:
        import rdflib
        g = rdflib.Graph()
        fmt = "turtle" if "@prefix" in content or "PREFIX" in content else "xml"
        g.parse(data=content, format=fmt)

        DCAT  = rdflib.Namespace("http://www.w3.org/ns/dcat#")
        DCT   = rdflib.Namespace("http://purl.org/dc/terms/")
        FOAF  = rdflib.Namespace("http://xmlns.com/foaf/0.1/")

        records = []
        for subj in g.subjects(rdflib.RDF.type, DCAT.Dataset):
            lha_url = str(subj)
            lha_id  = urlparse(lha_url).path.strip("/").split("/")[-1]
            title   = str(g.value(subj, DCT.title) or "")
            dois    = [str(o) for o in g.objects(subj, DCT.identifier)
                       if "10." in str(o)]
            pmids   = [str(o) for o in g.objects(subj, DCT.references)
                       if str(o).isdigit()]
            records.append({
                "lha_id":               lha_id,
                "lha_url":              lha_url,
                "title":                title,
                "record_type":          "dataset",
                "is_lha_hosted":        False,
                "external_dois":        json.dumps(dois),
                "external_accessions":  json.dumps([]),
                "external_urls":        json.dumps([]),
                "linked_pmids":         json.dumps(pmids),
                "authors":              json.dumps([]),
                "created_date":         str(g.value(subj, DCT.created) or ""),
                "modified_date":        str(g.value(subj, DCT.modified) or ""),
            })
        return records
    except Exception as exc:
        logger.warning("DCAT parse failed: %s", exc)
        return []


# ── Discovery method: REST API (SEEK JSON:API) ───────────────────────────────
#
# LHA returns HTTP 406 with Accept: application/json.
# SEEK requires Accept: application/vnd.api+json — the JSON:API media type.
#
# SEEK data model relevant to us:
#   data_files   — uploaded datasets; carry a 'doi' attribute and a
#                  'publications' relationship (list of linked papers)
#   publications — each has a 'pubmed_id' attribute
#
# Pagination: SEEK uses page[number] / page[size] query params.
# Response meta: {"pagination": {"current":1,"next":2,"last":N,"per_page":25}}

_SEEK_HEADERS = {"Accept": "application/json"}
_SEEK_PAGE_SIZE = 100    # max records per page (SEEK default cap is often 100)


def _seek_get(url: str, session: RateLimitedSession,
              cache: RawCache, key: str) -> dict | None:
    """GET one SEEK JSON:API URL; cache the raw response. Returns parsed dict or None."""
    if not cache.has(key):
        try:
            resp = session.get(url, headers=_SEEK_HEADERS)
            if not resp.ok:
                logger.debug("SEEK GET %s → HTTP %d", url, resp.status_code)
                cache.write(key, "")
                return None
            cache.write(key, resp.text)
        except Exception as exc:
            logger.debug("SEEK GET %s → %s", url, exc)
            return None
    raw = cache.read(key)
    if not raw:
        return None
    try:
        return json.loads(raw)
    except Exception:
        return None


def _seek_fetch_all_pages(base_url: str, endpoint: str,
                          session: RateLimitedSession,
                          cache: RawCache,
                          limit: int | None) -> list[dict]:
    """
    Page through a SEEK JSON:API collection endpoint and return all items.
    Stops early if limit is reached.
    """
    items: list[dict] = []
    page = 1
    while True:
        url = urljoin(base_url, endpoint) + f"?page[number]={page}&page[size]={_SEEK_PAGE_SIZE}"
        key = f"seek_{endpoint.replace('/', '_')}_p{page}"
        data = _seek_get(url, session, cache, key)
        if not data:
            break
        batch = data.get("data") or []
        if not batch:
            break
        items.extend(batch)
        logger.debug("SEEK %s page %d → %d items (total so far: %d)",
                     endpoint, page, len(batch), len(items))
        if limit and len(items) >= limit:
            items = items[:limit]
            break
        # Check pagination meta
        meta = data.get("meta", {}).get("pagination", {})
        if not meta or page >= (meta.get("last") or 1):
            break
        page += 1
    return items


def _seek_fetch_pmids_for_item(base_url: str, item_type: str, item_id: str,
                                session: RateLimitedSession,
                                cache: RawCache) -> list[str]:
    """
    Follow the publications relationship of a SEEK item to collect PMIDs.
    SEEK JSON:API: GET /api/v1/<type>/<id> → relationships.publications.data[{id}]
    Then: GET /api/v1/publications/<pub_id> → attributes.pubmed_id
    """
    # Fetch the individual item to get its relationships
    detail_url = urljoin(base_url, f"/{item_type}/{item_id}")
    detail_key = f"seek_detail_{item_type}_{item_id}"
    detail = _seek_get(detail_url, session, cache, detail_key)
    if not detail:
        return []

    pub_refs = (
        detail.get("data", {})
              .get("relationships", {})
              .get("publications", {})
              .get("data", [])
    )
    if not pub_refs:
        return []

    pmids: list[str] = []
    for pub_ref in pub_refs:
        pub_id = str(pub_ref.get("id", ""))
        if not pub_id:
            continue
        pub_url = urljoin(base_url, f"/publications/{pub_id}")
        pub_key = f"seek_pub_{pub_id}"
        pub_data = _seek_get(pub_url, session, cache, pub_key)
        if not pub_data:
            continue
        pmid = (
            pub_data.get("data", {})
                    .get("attributes", {})
                    .get("pubmed_id") or ""
        )
        if pmid:
            pmids.append(str(pmid))
    return pmids


def _try_rest_api(base_url: str, session: RateLimitedSession,
                  cache: RawCache, limit: int | None = None) -> list[dict]:
    """
    Try SEEK JSON:API endpoints with the correct Accept header.
    Pages through all records; follows publications relationships for PMIDs.
    Returns list of parsed record dicts, or [] if all endpoints fail.
    """
    # Ordered by relevance — data_files are the primary dataset objects in SEEK
    endpoints = [
        ("/data_files",       "data_files"),
        ("/datasets",         "datasets"),
        ("/studies",          "studies"),
        ("/investigations",   "investigations"),
    ]

    for endpoint, item_type in endpoints:
        items = _seek_fetch_all_pages(base_url, endpoint, session, cache, limit)
        if not items:
            logger.debug("REST %s → 0 items", endpoint)
            continue
        logger.info("SEEK REST API: %s returned %d items", endpoint, len(items))
        return _parse_seek_items(items, item_type, base_url, session, cache)

    return []


def _seek_harvest_publications(base_url: str, session: RateLimitedSession,
                                cache: RawCache,
                                limit: int | None = None) -> list[dict]:
    """
    Harvest the /publications endpoint of a SEEK platform.

    Each publication becomes one index record with:
      record_type  = "publication"
      linked_pmids = [the publication's own PubMed ID]   (if present)
      external_dois = [the publication's DOI]            (if present)

    This is the primary match signal for ArmLifeBank, which has 155
    publications explicitly registered in the system.
    """
    items = _seek_fetch_all_pages(base_url, "/publications", session, cache, limit)
    if not items:
        logger.info("Publications endpoint returned 0 items — skipping.")
        return []

    logger.info("Publications endpoint: %d items", len(items))
    records = []
    for i, item in enumerate(items, 1):
        attrs   = item.get("attributes", {})
        links   = item.get("links", {})
        item_id = str(item.get("id", ""))

        pub_url = urljoin(base_url, links.get("self") or f"/publications/{item_id}")

        title = attrs.get("title") or ""

        # Fetch detail page — pubmed_id, doi, and abstract live here, not in the list
        detail_url = urljoin(base_url, f"/publications/{item_id}")
        detail_key = f"seek_pub_detail_{item_id}"
        detail = _seek_get(detail_url, session, cache, detail_key)

        detail_attrs: dict = {}
        if detail:
            detail_attrs = detail.get("data", {}).get("attributes", {})

        # Use detail title if list title is empty
        if not title:
            title = detail_attrs.get("title") or ""

        # Own PMID — the publication IS the paper (only in detail attrs)
        pmid = str(detail_attrs.get("pubmed_id") or "").strip()
        linked_pmids = [pmid] if pmid else []

        # Own DOI (only in detail attrs)
        doi_raw = str(detail_attrs.get("doi") or "").strip()
        dois = [doi_raw.lower()] if doi_raw else []

        # Extract URLs from abstract
        external_urls: list[str] = []
        if detail_attrs:
            abs_text = str(detail_attrs.get("abstract") or "")
            for url in re.findall(r"https?://\S+", abs_text):
                external_urls.append(url.rstrip(".,;)>\"'"))

        if i % 25 == 0 or i == len(items):
            logger.info("Processed %d / %d publication items…", i, len(items))

        records.append({
            "lha_id":               f"pub_{item_id}",
            "lha_url":              pub_url,
            "title":                title,
            "record_type":          "publication",
            "is_lha_hosted":        False,
            "external_dois":        json.dumps(dois),
            "external_accessions":  json.dumps([]),
            "external_urls":        json.dumps(external_urls[:20]),
            "linked_pmids":         json.dumps(linked_pmids),
            "authors":              json.dumps([]),
            "created_date":         attrs.get("created_at") or "",
            "modified_date":        attrs.get("updated_at") or "",
            "raw_path":             str(cache.path(detail_key)),
        })
    return records


def _try_seek_json_api(base_url: str, session: RateLimitedSession,
                       cache: RawCache, limit: int | None = None) -> list[dict]:
    """
    Extended SEEK JSON:API harvest: data_files + publications.
    Used as the 'seek_json_api' method (alias for rest_api that also pulls
    the /publications endpoint for platforms like ArmLifeBank).
    """
    records: list[dict] = []

    # 1. Data files (primary dataset objects)
    data_file_records = _try_rest_api(base_url, session, cache, limit)
    records.extend(data_file_records)

    # 2. Publications (listed papers — each carries its own PMID)
    pub_records = _seek_harvest_publications(base_url, session, cache, limit)
    records.extend(pub_records)

    return records


def _parse_seek_items(items: list[dict], item_type: str,
                      base_url: str,
                      session: RateLimitedSession,
                      cache: RawCache) -> list[dict]:
    """
    Parse SEEK JSON:API items into lha_index record dicts.
    Fetches linked publications per item to extract PMIDs.
    """
    records = []
    for i, item in enumerate(items, 1):
        attrs   = item.get("attributes", {})
        links   = item.get("links", {})
        item_id = str(item.get("id", ""))

        lha_url = urljoin(base_url, links.get("self") or f"/{item_type}/{item_id}")
        # Prefer the human-readable URL over the API URL when available
        web_url = attrs.get("url") or lha_url

        title = attrs.get("title") or attrs.get("name") or ""

        # DOI
        dois: list[str] = []
        if doi := (attrs.get("doi") or ""):
            dois.append(doi.strip().lower())

        # Content blobs may carry additional download URLs
        content_blobs = attrs.get("content_blobs") or []
        external_urls: list[str] = []
        for blob in content_blobs:
            if url := blob.get("url"):
                external_urls.append(url)

        # PMIDs via publications relationship
        pmids = _seek_fetch_pmids_for_item(
            base_url, item_type, item_id, session, cache
        )

        if i % 25 == 0 or i == len(items):
            logger.info("Processed %d / %d SEEK items…", i, len(items))

        records.append({
            "lha_id":               item_id,
            "lha_url":              web_url,
            "title":                title,
            "record_type":          item_type.rstrip("s"),   # data_files→data_file etc.
            "is_lha_hosted":        not bool(dois) and not bool(external_urls),
            "external_dois":        json.dumps(dois),
            "external_accessions":  json.dumps([]),
            "external_urls":        json.dumps(external_urls),
            "linked_pmids":         json.dumps(pmids),
            "authors":              json.dumps([]),
            "created_date":         attrs.get("created_at") or "",
            "modified_date":        attrs.get("updated_at") or "",
            "raw_path":             str(cache.path(f"seek_detail_{item_type}_{item_id}")),
        })
    return records


# ── Discovery method: sitemap scrape ─────────────────────────────────────────

def _try_sitemap(base_url: str, session: RateLimitedSession,
                 cache: RawCache, rp: urllib.robotparser.RobotFileParser,
                 user_agent: str, limit: Optional[int]) -> list[dict]:
    """
    Fetch /sitemap.xml, extract /lha/<id> URLs, parse each page.
    Returns list of record dicts.
    """
    sitemap_url = urljoin(base_url, "/sitemap.xml")
    key = "sitemap_xml"
    try:
        if not cache.has(key):
            resp = session.get(sitemap_url)
            if not resp.ok:
                logger.warning("Sitemap %s → HTTP %d", sitemap_url, resp.status_code)
                return []
            cache.write(key, resp.text)
        sitemap_xml = cache.read(key)
    except Exception as exc:
        logger.warning("Sitemap fetch failed: %s", exc)
        return []

    # Parse sitemap — handle both plain and index sitemaps
    soup = BeautifulSoup(sitemap_xml, "lxml-xml")

    # Sitemap index: contains <sitemap><loc>...</loc></sitemap>
    sub_sitemap_urls: list[str] = [
        loc.get_text(strip=True)
        for loc in soup.find_all("loc")
        if "sitemap" in loc.get_text(strip=True).lower()
    ]

    record_urls: list[str] = []

    if sub_sitemap_urls:
        logger.info("Sitemap index found — %d sub-sitemaps", len(sub_sitemap_urls))
        for sub_url in sub_sitemap_urls:
            sub_key = f"subsitemap_{sub_url.replace('/', '_')}"
            try:
                if not cache.has(sub_key):
                    resp = session.get(sub_url)
                    if not resp.ok:
                        continue
                    cache.write(sub_key, resp.text)
                sub_soup = BeautifulSoup(cache.read(sub_key), "lxml-xml")
                for loc in sub_soup.find_all("loc"):
                    url = loc.get_text(strip=True)
                    if _is_lha_record_url(url, base_url):
                        record_urls.append(url)
            except Exception as exc:
                logger.debug("Sub-sitemap %s → %s", sub_url, exc)
    else:
        # Plain sitemap: all <loc> entries
        for loc in soup.find_all("loc"):
            url = loc.get_text(strip=True)
            if _is_lha_record_url(url, base_url):
                record_urls.append(url)

    record_urls = list(dict.fromkeys(record_urls))   # deduplicate
    logger.info("Sitemap: found %d candidate record URLs", len(record_urls))

    if limit:
        record_urls = record_urls[:limit]
        logger.info("Limiting to first %d records (--limit)", limit)

    return _fetch_and_parse_pages(record_urls, base_url, session, cache, rp, user_agent)


def _is_lha_record_url(url: str, base_url: str) -> bool:
    """Return True if the URL looks like an individual LHA record page."""
    try:
        base_host = urlparse(base_url).netloc
        parsed    = urlparse(url)
        if parsed.netloc and parsed.netloc != base_host:
            return False
        path = parsed.path
        # Accept paths like /lha/123, /datasets/123, /models/123 etc.
        return bool(re.search(
            r"/(lha|datasets?|models?|phenotypes?|tools?|studies|assays)/[\w\-]+$",
            path, re.I
        ))
    except Exception:
        return False


def _lha_id_from_url(url: str) -> str:
    path = urlparse(url).path.strip("/")
    return path.split("/")[-1]


def _fetch_and_parse_pages(urls: list[str], base_url: str,
                            session: RateLimitedSession, cache: RawCache,
                            rp: urllib.robotparser.RobotFileParser,
                            user_agent: str) -> list[dict]:
    """Fetch and parse each record page. Skip if robots.txt disallows."""
    records = []
    for i, url in enumerate(urls, 1):
        if not _can_fetch(rp, user_agent, url):
            logger.warning("robots.txt disallows: %s — skipping", url)
            continue
        lha_id = _lha_id_from_url(url)
        key    = f"page_{lha_id}"
        try:
            if not cache.has(key):
                resp = session.get(url)
                if not resp.ok:
                    logger.warning("Page %s → HTTP %d — skipping", url, resp.status_code)
                    cache.write(key, "")
                    continue
                cache.write(key, resp.text)
            html = cache.read(key)
            if not html.strip():
                continue
            record = _parse_html_record(lha_id, url, html)
            record["raw_path"] = str(cache.path(key))
            records.append(record)
            if i % 25 == 0 or i == len(urls):
                logger.info("Parsed %d / %d pages…", i, len(urls))
        except Exception as exc:
            logger.error("Failed to parse %s: %s — skipping", url, exc)
    return records


# ── Main entry point ──────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Harvest a SEEK-based data atlas catalog into a local index."
    )
    parser.add_argument("--config", default=str(_DEFAULT_CONFIG), metavar="PATH",
                        help="Path to YAML config (default: config/lha.yaml).")
    parser.add_argument("--limit", type=int, default=None, metavar="N",
                        help="Stop after N records (probe mode).")
    parser.add_argument("--refresh", action="store_true",
                        help="Ignore cached responses and re-fetch everything.")
    parser.add_argument("--method", default=None,
                        choices=["dcat_endpoint", "rest_api", "seek_json_api",
                                 "sitemap_scrape"],
                        help="Force a specific discovery method (skip auto-detection).")
    parser.add_argument("--log-level", default="INFO",
                        choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    args = parser.parse_args()

    cfg_path   = Path(args.config)
    cfg        = _load_config(cfg_path)
    pk         = _platform_key(cfg)
    plat_cfg   = cfg[pk]
    base_url   = plat_cfg["base_url"]
    user_agent = plat_cfg["harvest"]["user_agent"]
    rps        = float(plat_cfg["harvest"]["rate_limit_rps"])
    methods    = [args.method] if args.method else plat_cfg["harvest"]["methods"]

    out_path   = _index_path(cfg)
    cache_dir  = _cache_dir(cfg, pk)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    # ── Logging: console + optional file ─────────────────────────────────
    log_handlers: list[logging.Handler] = [logging.StreamHandler()]
    log_file_rel = cfg["output"].get("harvest_log")
    if log_file_rel:
        log_file = _REPO_ROOT / log_file_rel
        log_file.parent.mkdir(parents=True, exist_ok=True)
        log_handlers.append(logging.FileHandler(log_file, mode="w", encoding="utf-8"))

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=log_handlers,
    )

    session = RateLimitedSession(user_agent=user_agent, rps=rps)
    cache   = RawCache(cache_dir, force_refresh=args.refresh)

    # ── robots.txt ────────────────────────────────────────────────────────
    logger.info("Checking robots.txt at %s", base_url)
    rp = _load_robots(base_url, session, cache)
    if not _can_fetch(rp, user_agent, base_url):
        logger.error("robots.txt disallows access to %s — aborting.", base_url)
        return

    # ── Try discovery methods in configured order ─────────────────────────
    records: list[dict] = []
    used_method = None

    for method in methods:
        logger.info("Trying discovery method: %s", method)
        if method == "dcat_endpoint":
            records = _try_dcat(base_url, session, cache)
        elif method in ("rest_api", "seek_json_api"):
            # seek_json_api is the extended variant: data_files + publications
            if method == "seek_json_api":
                records = _try_seek_json_api(base_url, session, cache, limit=args.limit)
            else:
                records = _try_rest_api(base_url, session, cache, limit=args.limit)
        elif method == "sitemap_scrape":
            records = _try_sitemap(base_url, session, cache, rp,
                                   user_agent, args.limit)
        if records:
            used_method = method
            logger.info("Method '%s' succeeded — %d raw records", method, len(records))
            break
        else:
            logger.warning("Method '%s' returned 0 records.", method)

    if not records:
        logger.error(
            "All discovery methods failed. "
            "Check network access to %s and review DEBUG logs.", base_url
        )
        return

    # Apply limit for non-sitemap methods (sitemap applies it during fetch)
    if args.limit and used_method not in ("sitemap_scrape", "seek_json_api"):
        records = records[:args.limit]

    # ── Write index ───────────────────────────────────────────────────────
    df = pd.DataFrame(records)
    df.to_csv(out_path, index=False)

    # ── Console report ────────────────────────────────────────────────────
    n_with_dois   = (df["external_dois"] != "[]").sum()
    n_with_acc    = (df["external_accessions"] != "[]").sum()
    n_with_pmids  = (df["linked_pmids"] != "[]").sum()
    n_hosted      = df["is_lha_hosted"].sum()

    platform_name = cfg.get("target", {}).get("name", pk.upper())
    print(f"\n{'='*60}")
    print(f"  {platform_name} Harvest complete")
    print(f"{'='*60}")
    print(f"  Config           : {cfg_path}")
    print(f"  Discovery method : {used_method}")
    print(f"  Total records    : {len(df)}")
    if "record_type" in df.columns:
        print(f"  By type          :")
        for rtype, count in df["record_type"].value_counts().items():
            print(f"    {rtype:<20} {count}")
    print(f"  With external DOIs        : {n_with_dois}")
    print(f"  With external accessions  : {n_with_acc}")
    print(f"  With linked PMIDs         : {n_with_pmids}")
    print(f"  Hosted (no ext. repo)     : {n_hosted}")
    print(f"{'='*60}")
    print(f"  Index written → {out_path}")

    # Sample of first 3 records for visual verification
    print(f"\n  Sample records:")
    for _, row in df.head(3).iterrows():
        print(f"    [{row['lha_id']}] {row['title'][:70]}")
        print(f"      type={row['record_type']}  "
              f"dois={row['external_dois'][:60]}  "
              f"pmids={row['linked_pmids'][:40]}")


if __name__ == "__main__":
    main()
