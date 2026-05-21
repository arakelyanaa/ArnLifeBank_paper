#!/usr/bin/env python3
"""
Reuse & citation analysis for DOI-bearing deposited datasets.

For each unique DOI found in article_repository_links.csv (across all countries),
queries the DataCite API for citation counts and deposition dates, then aggregates
median / mean citations per country × repository class.

Usage:
  python analysis/reuse.py
  python analysis/reuse.py --countries armenia georgia estonia
  python analysis/reuse.py --windowed          # adds 24-month windowed count (slower)
  python analysis/reuse.py --force-refresh-cache
"""

from __future__ import annotations

import argparse
import logging
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from urllib.parse import quote as urlquote

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from armlifebank.cache import Cache  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# ── Constants ──────────────────────────────────────────────────────────────────

DATACITE_BASE = "https://api.datacite.org"
RATE_LIMIT_DELAY = 0.2          # seconds between DataCite requests (5 req/s)
RETRY_MAX = 3
RETRY_BACKOFF = 2.0             # seconds; doubles each attempt
WINDOW_DAYS = 730               # 24-month citation window

DOI_RE = re.compile(r"^10\.\d{4,}/.+", re.IGNORECASE)

REPO_CLASSES: dict[str, set[str]] = {
    "domain_standard": {
        "GenBank", "PDB", "Gene Expression Omnibus", "SRA", "ENA",
        "BioProject", "BioSample", "PRIDE", "EGA", "RefSeq",
        "ArrayExpress", "MetaboLights", "dbGaP",
    },
    "general_purpose": {
        "Zenodo", "Figshare", "OSF", "Mendeley Data", "Dryad", "Dataverse",
    },
    "code_other": {
        "GitHub", "GitLab", "ClinicalTrials.gov",
    },
}


# ── DOI helpers ────────────────────────────────────────────────────────────────

def normalise_doi(raw: str) -> Optional[str]:
    """Return a canonical lowercase DOI string, or None if not a valid DOI."""
    doi = raw.strip().lower()
    if not DOI_RE.match(doi):
        return None
    # Figshare: strip .v{N} version suffix for deduplication
    doi = re.sub(r"(10\.6084/m9\.figshare\.\d+)\.v\d+$", r"\1", doi)
    # Strip trailing punctuation that sometimes bleeds in from text extraction
    doi = doi.rstrip(".,;)")
    return doi


def classify_repo(name: str) -> str:
    for cls, members in REPO_CLASSES.items():
        if name in members:
            return cls
    return "unclassified"


# ── DataCite API ───────────────────────────────────────────────────────────────

def _get(session: requests.Session, url: str) -> Optional[dict]:
    """GET with retries; returns parsed JSON or None on unrecoverable error."""
    for attempt in range(RETRY_MAX):
        try:
            r = session.get(url, timeout=15)
            if r.status_code == 200:
                return r.json()
            if r.status_code in (404, 410):
                return None          # DOI not in DataCite; no point retrying
            if r.status_code < 500:
                logger.warning("Non-retryable %s for %s", r.status_code, url)
                return None
            # 5xx — retry
            logger.warning("HTTP %s on attempt %d for %s", r.status_code, attempt + 1, url)
        except requests.RequestException as exc:
            logger.warning("Request error on attempt %d for %s: %s", attempt + 1, url, exc)
        if attempt < RETRY_MAX - 1:
            time.sleep(RETRY_BACKOFF * (2 ** attempt))
    return None


def fetch_doi_metadata(doi: str, session: requests.Session, cache: Cache) -> Optional[dict]:
    """Return DataCite metadata dict for a DOI, using cache."""
    key = f"datacite:{doi}"
    cached = cache.get(key)
    if cached is not None:
        return cached
    time.sleep(RATE_LIMIT_DELAY)
    url = f"{DATACITE_BASE}/dois/{urlquote(doi, safe='')}"
    data = _get(session, url)
    result = data["data"]["attributes"] if data and "data" in data else {}
    cache.set(key, result)
    return result or None


def fetch_windowed_citations(
    doi: str,
    registered: Optional[datetime],
    session: requests.Session,
    cache: Cache,
) -> Optional[int]:
    """Count citation events within WINDOW_DAYS of deposition via DataCite Events API."""
    if registered is None:
        return None
    key = f"datacite_events:{doi}"
    events = cache.get(key)
    if events is None:
        time.sleep(RATE_LIMIT_DELAY)
        url = (
            f"{DATACITE_BASE}/events"
            f"?obj-id={urlquote(doi, safe='')}"
            f"&relation-type-id=references"
            f"&page[size]=1000"
        )
        data = _get(session, url)
        events = data.get("data", []) if data else []
        cache.set(key, events)

    if not events:
        return 0

    cutoff = registered.timestamp() + WINDOW_DAYS * 86400
    count = 0
    for ev in events:
        occurred = ev.get("attributes", {}).get("occurred-at", "")
        try:
            ts = datetime.fromisoformat(occurred.replace("Z", "+00:00")).timestamp()
            if ts <= cutoff:
                count += 1
        except (ValueError, AttributeError):
            continue
    return count


# ── Load & extract DOIs ────────────────────────────────────────────────────────

def load_doi_rows(countries: list[str], root: Path) -> pd.DataFrame:
    """
    Load article_repository_links CSVs for each country and return a DataFrame
    of rows with valid DOI identifiers, one row per (country, doi) pair.
    Deduplicates so each DOI appears once per country.
    """
    frames = []
    for country in countries:
        path = root / "output" / country / "article_repository_links.csv"
        if not path.exists():
            logger.warning("Missing links file for %s: %s", country, path)
            continue
        df = pd.read_csv(path, dtype=str).fillna("")
        df["country"] = country
        frames.append(df)

    if not frames:
        logger.error("No links files found — check --countries and output directory.")
        sys.exit(1)

    combined = pd.concat(frames, ignore_index=True)

    # Normalise identifiers and keep only valid DOIs
    combined["doi_norm"] = combined["identifier"].map(normalise_doi)
    combined = combined[combined["doi_norm"].notna()].copy()

    # Classify repository
    combined["repo_class"] = combined["repository"].map(classify_repo)

    # One row per (country, doi_norm) — keep first occurrence for metadata
    deduped = (
        combined
        .sort_values(["country", "doi_norm", "confidence"], ascending=[True, True, False])
        .drop_duplicates(subset=["country", "doi_norm"])
        [["country", "repository", "repo_class", "doi_norm"]]
        .rename(columns={"doi_norm": "doi"})
        .reset_index(drop=True)
    )
    return deduped


# ── Main ───────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Reuse & citation analysis for DOI-bearing deposited datasets."
    )
    parser.add_argument(
        "--countries", nargs="+", default=["armenia", "georgia", "estonia"],
        help="Country codes to analyse (must have output/{country}/ directories).",
    )
    parser.add_argument(
        "--windowed", action="store_true",
        help="Also fetch 24-month windowed citation count via DataCite Events API "
             "(slower: one extra request per DOI).",
    )
    parser.add_argument(
        "--force-refresh-cache", action="store_true",
        help="Ignore existing cache entries and re-fetch from DataCite.",
    )
    parser.add_argument(
        "--output-dir", default=None, metavar="DIR",
        help="Directory for output files (default: output/).",
    )
    args = parser.parse_args()

    out_dir = Path(args.output_dir) if args.output_dir else ROOT / "output"
    cache = Cache(ROOT / ".cache", force_refresh=args.force_refresh_cache)
    session = requests.Session()
    session.headers["Accept"] = "application/vnd.api+json"

    # ── 1. Load DOIs ──────────────────────────────────────────────────────────
    logger.info("Loading links CSVs for: %s", ", ".join(args.countries))
    doi_df = load_doi_rows(args.countries, ROOT)
    logger.info("Found %d unique (country, DOI) pairs", len(doi_df))

    # ── 2. Fetch DataCite metadata ────────────────────────────────────────────
    unique_dois = doi_df["doi"].unique()
    logger.info("Fetching DataCite metadata for %d unique DOIs …", len(unique_dois))

    meta: dict[str, dict] = {}
    for i, doi in enumerate(unique_dois, 1):
        if i % 50 == 0:
            logger.info("  … %d / %d", i, len(unique_dois))
        result = fetch_doi_metadata(doi, session, cache)
        meta[doi] = result or {}

    # ── 3. Parse metadata ─────────────────────────────────────────────────────
    records = []
    for _, row in doi_df.iterrows():
        doi = row["doi"]
        attrs = meta.get(doi, {})

        registered_raw = attrs.get("registered") or attrs.get("created")
        registered_dt: Optional[datetime] = None
        if registered_raw:
            try:
                registered_dt = datetime.fromisoformat(
                    registered_raw.replace("Z", "+00:00")
                )
            except ValueError:
                pass

        citation_count = attrs.get("citationCount")
        if citation_count is not None:
            try:
                citation_count = int(citation_count)
            except (TypeError, ValueError):
                citation_count = None

        windowed_count: Optional[int] = None
        if args.windowed:
            windowed_count = fetch_windowed_citations(doi, registered_dt, session, cache)

        records.append({
            "country": row["country"],
            "repository": row["repository"],
            "repo_class": row["repo_class"],
            "doi": doi,
            "registered": registered_dt.date().isoformat() if registered_dt else None,
            "citation_count": citation_count,
            "citation_count_windowed_24m": windowed_count,
            "view_count": attrs.get("viewCount"),
            "download_count": attrs.get("downloadCount"),
            "has_datacite_record": bool(attrs),
        })

    citations_df = pd.DataFrame(records)

    # ── 4. Aggregate ──────────────────────────────────────────────────────────
    def agg_group(grp: pd.DataFrame) -> pd.Series:
        cc = grp["citation_count"].dropna()
        wc = grp["citation_count_windowed_24m"].dropna()
        return pd.Series({
            "n_datasets": len(grp),
            "n_with_datacite_record": int(grp["has_datacite_record"].sum()),
            "n_with_citation_data": int(cc.notna().sum() if not cc.empty else 0),
            "coverage_pct": round(cc.notna().sum() / len(grp) * 100, 1) if len(grp) else 0,
            "median_citations": round(cc.median(), 2) if not cc.empty else None,
            "mean_citations": round(cc.mean(), 2) if not cc.empty else None,
            "p25_citations": round(cc.quantile(0.25), 2) if not cc.empty else None,
            "p75_citations": round(cc.quantile(0.75), 2) if not cc.empty else None,
            "median_citations_24m": round(wc.median(), 2) if not wc.empty else None,
            "mean_citations_24m": round(wc.mean(), 2) if not wc.empty else None,
        })

    summary_df = (
        citations_df
        .groupby(["country", "repo_class"], sort=True)
        .apply(agg_group)
        .reset_index()
    )

    # ── 5. Write outputs ──────────────────────────────────────────────────────
    citations_path = out_dir / "reuse_citations.csv"
    summary_path = out_dir / "reuse_summary.csv"
    report_path = out_dir / "reuse_report.md"

    citations_df.to_csv(citations_path, index=False)
    summary_df.to_csv(summary_path, index=False)

    # ── 6. Markdown report ────────────────────────────────────────────────────
    total_dois = len(unique_dois)
    total_with_record = sum(1 for v in meta.values() if v)
    total_with_citations = int(citations_df["citation_count"].notna().sum())

    lines = [
        "# Reuse & Citation Analysis — DOI-bearing Datasets",
        "",
        f"*Generated {datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M UTC')}*  ",
        f"*Countries: {', '.join(c.capitalize() for c in args.countries)}*  ",
        f"*Scope: DOI-bearing identifiers only (accession-only datasets excluded)*",
        "",
        "---",
        "",
        "## 1. Coverage",
        "",
        f"| Metric | n |",
        f"|--------|--:|",
        f"| Unique DOIs extracted | {total_dois:,} |",
        f"| DOIs with DataCite record | {total_with_record:,} "
        f"({total_with_record/total_dois:.0%}) |",
        f"| DOIs with citation count | {total_with_citations:,} "
        f"({total_with_citations/total_dois:.0%}) |",
        "",
        "---",
        "",
        "## 2. Citations by Country × Repository Class",
        "",
        "| Country | Repo class | Datasets | Coverage | Median citations | Mean | P25–P75 |",
        "|---------|------------|--------:|---------:|----------------:|-----:|---------|",
    ]

    for _, r in summary_df.iterrows():
        p25 = r["p25_citations"]
        p75 = r["p75_citations"]
        iqr = f"{p25:.0f}–{p75:.0f}" if pd.notna(p25) and pd.notna(p75) else "—"
        med = f"{r['median_citations']:.1f}" if pd.notna(r["median_citations"]) else "—"
        mean = f"{r['mean_citations']:.1f}" if pd.notna(r["mean_citations"]) else "—"
        lines.append(
            f"| {r['country'].capitalize()} | {r['repo_class']} "
            f"| {int(r['n_datasets'])} | {r['coverage_pct']:.0f}% "
            f"| {med} | {mean} | {iqr} |"
        )

    if args.windowed:
        lines += [
            "",
            "---",
            "",
            "## 3. Windowed Citations (≤ 24 months post-deposition)",
            "",
            "| Country | Repo class | Datasets | Median (24m) | Mean (24m) |",
            "|---------|------------|--------:|-------------:|-----------:|",
        ]
        for _, r in summary_df.iterrows():
            med24 = f"{r['median_citations_24m']:.1f}" if pd.notna(r.get("median_citations_24m")) else "—"
            mean24 = f"{r['mean_citations_24m']:.1f}" if pd.notna(r.get("mean_citations_24m")) else "—"
            lines.append(
                f"| {r['country'].capitalize()} | {r['repo_class']} "
                f"| {int(r['n_datasets'])} | {med24} | {mean24} |"
            )

    lines += [
        "",
        "---",
        "",
        "## Limitations",
        "",
        "- Make Data Count citation data has uneven coverage; deposits before 2020 "
        "often have `citationCount = 0` even if cited.",
        "- `citation_count` is a **lifetime total**, not windowed "
        "(use `--windowed` for 24-month counts via the DataCite Events API).",
        "- Self-citations are not filtered.",
        "- Accession-only deposits (GenBank, SRA, PDB, GEO, BioProject) are excluded "
        "from this analysis — they represent the majority of domain-standard archive deposits.",
    ]

    report_path.write_text("\n".join(lines), encoding="utf-8")

    # ── Console summary ───────────────────────────────────────────────────────
    print(f"\nReuse & citation analysis")
    print(f"  Unique DOIs          : {total_dois:,}")
    print(f"  DataCite records     : {total_with_record:,} ({total_with_record/total_dois:.0%})")
    print(f"  With citation count  : {total_with_citations:,} ({total_with_citations/total_dois:.0%})")
    print()
    print(summary_df[["country", "repo_class", "n_datasets",
                       "coverage_pct", "median_citations", "mean_citations"]].to_string(index=False))
    print(f"\n  Outputs:")
    print(f"    {citations_path}")
    print(f"    {summary_path}")
    print(f"    {report_path}")


if __name__ == "__main__":
    main()
