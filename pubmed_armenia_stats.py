#!/usr/bin/env python3
"""
PubMed Statistics: Papers with Armenia Author Affiliations (2020-2025)

Uses NCBI Entrez API (no API key required, but rate-limited to 3 req/s).
Set NCBI_API_KEY env var to increase to 10 req/s.
"""

import os
import time
import json
import re
from collections import Counter, defaultdict
from datetime import datetime

from Bio import Entrez
import pandas as pd

# ── Configuration ────────────────────────────────────────────────────────────
Entrez.email = os.environ.get("NCBI_EMAIL", "arakelyanaa@gmail.com")
Entrez.api_key = os.environ.get("NCBI_API_KEY", "23c05c2767a9c081747df797c3c287997608")
BATCH_SIZE = 200        # records per fetch call
RATE_DELAY = 0.15       # seconds between requests (safe for 10 req/s with API key)
YEARS = range(2020, 2026)  # 2020–2025 inclusive
QUERY = '("Armenia"[Affiliation]) AND ({year}[PDAT])'

# ── Helpers ───────────────────────────────────────────────────────────────────

def entrez_search(query: str, retmax: int = 10000) -> list[str]:
    """Return list of PubMed IDs for a query."""
    handle = Entrez.esearch(db="pubmed", term=query, retmax=retmax, usehistory="y")
    record = Entrez.read(handle)
    handle.close()
    return record["IdList"], int(record["Count"])


def fetch_records_batch(ids: list[str]) -> list[dict]:
    """Fetch parsed XML records for a list of PMIDs."""
    handle = Entrez.efetch(
        db="pubmed",
        id=",".join(ids),
        rettype="xml",
        retmode="xml",
    )
    records = Entrez.read(handle)
    handle.close()
    return records.get("PubmedArticle", [])


def extract_affiliations(article) -> list[str]:
    """Return all affiliation strings from an article."""
    affiliations = []
    medline = article.get("MedlineCitation", {})
    article_data = medline.get("Article", {})
    author_list = article_data.get("AuthorList", [])
    for author in author_list:
        for aff in author.get("AffiliationInfo", []):
            text = str(aff.get("Affiliation", ""))
            if text:
                affiliations.append(text)
    return affiliations


def is_armenia_affiliation(aff: str) -> bool:
    """True if the affiliation string references Armenia."""
    return bool(re.search(r"\barmenia\b", aff, re.IGNORECASE))


def extract_journal(article) -> str:
    medline = article.get("MedlineCitation", {})
    journal = medline.get("Article", {}).get("Journal", {})
    return str(journal.get("Title", "Unknown"))


def extract_pub_type(article) -> list[str]:
    medline = article.get("MedlineCitation", {})
    pt_list = medline.get("Article", {}).get("PublicationTypeList", [])
    return [str(pt) for pt in pt_list]


def extract_mesh(article) -> list[str]:
    medline = article.get("MedlineCitation", {})
    mesh_list = medline.get("MeshHeadingList", [])
    terms = []
    for heading in mesh_list:
        descriptor = heading.get("DescriptorName", None)
        if descriptor is not None:
            terms.append(str(descriptor))
    return terms


def extract_keywords(article) -> list[str]:
    medline = article.get("MedlineCitation", {})
    kw_list = medline.get("KeywordList", [])
    keywords = []
    for group in kw_list:
        for kw in group:
            keywords.append(str(kw))
    return keywords


def extract_country_from_affiliation(aff: str) -> str:
    """
    Heuristic: last comma-separated token, cleaned up.
    Returns 'Armenia' for Armenia affiliations, or the extracted token.
    """
    parts = [p.strip().rstrip(".") for p in aff.split(",")]
    if parts:
        return parts[-1]
    return "Unknown"


# ── Main pipeline ─────────────────────────────────────────────────────────────

def collect_data() -> list[dict]:
    """Fetch all Armenia-affiliated papers for 2020-2025."""
    all_rows = []
    for year in YEARS:
        query = QUERY.format(year=year)
        print(f"\n[{year}] Searching: {query}")
        ids, total = entrez_search(query)
        print(f"  → {total} papers found (fetching {len(ids)})")

        for i in range(0, len(ids), BATCH_SIZE):
            batch = ids[i : i + BATCH_SIZE]
            time.sleep(RATE_DELAY)
            articles = fetch_records_batch(batch)
            for article in articles:
                medline = article.get("MedlineCitation", {})
                pmid = str(medline.get("PMID", ""))
                affiliations = extract_affiliations(article)
                # keep only articles with at least one Armenia affiliation
                if not any(is_armenia_affiliation(a) for a in affiliations):
                    continue
                journal = extract_journal(article)
                pub_types = extract_pub_type(article)
                mesh = extract_mesh(article)
                keywords = extract_keywords(article)
                all_rows.append(
                    {
                        "pmid": pmid,
                        "year": year,
                        "journal": journal,
                        "pub_types": pub_types,
                        "mesh_terms": mesh,
                        "keywords": keywords,
                        "affiliations": affiliations,
                    }
                )
            print(
                f"  fetched {min(i + BATCH_SIZE, len(ids))}/{len(ids)}",
                end="\r",
            )
        print()

    return all_rows


def compute_statistics(rows: list[dict]) -> dict:
    stats = {}

    # ── 1. Total & per-year counts ────────────────────────────────────────
    stats["total_papers"] = len(rows)
    year_counts = Counter(r["year"] for r in rows)
    stats["papers_per_year"] = dict(sorted(year_counts.items()))

    # ── 2. Top journals ───────────────────────────────────────────────────
    journal_counts = Counter(r["journal"] for r in rows)
    stats["top_journals"] = journal_counts.most_common(20)

    # ── 3. Publication types ──────────────────────────────────────────────
    pub_type_counts: Counter = Counter()
    for r in rows:
        for pt in r["pub_types"]:
            pub_type_counts[pt] += 1
    stats["publication_types"] = pub_type_counts.most_common(15)

    # ── 4. Top MeSH terms ────────────────────────────────────────────────
    mesh_counts: Counter = Counter()
    for r in rows:
        for m in r["mesh_terms"]:
            mesh_counts[m] += 1
    stats["top_mesh_terms"] = mesh_counts.most_common(30)

    # ── 5. Top keywords ───────────────────────────────────────────────────
    kw_counts: Counter = Counter()
    for r in rows:
        for kw in r["keywords"]:
            kw_counts[kw.lower()] += 1
    stats["top_keywords"] = kw_counts.most_common(30)

    # ── 6. Collaboration: co-affiliations from other countries ────────────
    collab_counts: Counter = Counter()
    for r in rows:
        countries = set()
        for aff in r["affiliations"]:
            if not is_armenia_affiliation(aff):
                country = extract_country_from_affiliation(aff)
                if country and len(country) > 1:
                    countries.add(country)
        for c in countries:
            collab_counts[c] += 1
    stats["top_collaborating_countries_raw"] = collab_counts.most_common(30)

    # ── 7. Single-country vs international ───────────────────────────────
    solo = sum(
        1
        for r in rows
        if all(is_armenia_affiliation(a) for a in r["affiliations"])
    )
    stats["armenia_only_papers"] = solo
    stats["international_collaboration_papers"] = len(rows) - solo

    return stats


def print_report(stats: dict):
    sep = "=" * 65

    print(f"\n{sep}")
    print("  PubMed Armenia Affiliation Statistics  2020–2025")
    print(sep)
    print(f"\nTotal papers: {stats['total_papers']}")

    print("\n── Papers per year ──────────────────────────────────────────")
    for yr, cnt in stats["papers_per_year"].items():
        bar = "█" * (cnt // 5)
        print(f"  {yr}: {cnt:>5}  {bar}")

    print("\n── Collaboration ────────────────────────────────────────────")
    print(f"  Armenia-only affiliations : {stats['armenia_only_papers']}")
    print(f"  International             : {stats['international_collaboration_papers']}")

    print("\n── Top 20 Journals ──────────────────────────────────────────")
    for i, (journal, cnt) in enumerate(stats["top_journals"], 1):
        print(f"  {i:>2}. {cnt:>4}  {journal}")

    print("\n── Publication Types ────────────────────────────────────────")
    for pt, cnt in stats["publication_types"]:
        print(f"  {cnt:>5}  {pt}")

    print("\n── Top 30 MeSH Terms ────────────────────────────────────────")
    for i, (term, cnt) in enumerate(stats["top_mesh_terms"], 1):
        print(f"  {i:>2}. {cnt:>4}  {term}")

    print("\n── Top 30 Keywords ──────────────────────────────────────────")
    for i, (kw, cnt) in enumerate(stats["top_keywords"], 1):
        print(f"  {i:>2}. {cnt:>4}  {kw}")

    print("\n── Top 30 Collaborating Countries (heuristic) ───────────────")
    for i, (country, cnt) in enumerate(stats["top_collaborating_countries_raw"], 1):
        print(f"  {i:>2}. {cnt:>4}  {country}")

    print(f"\n{sep}\n")


def save_outputs(rows: list[dict], stats: dict):
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")

    # Raw data as JSON
    json_path = f"armenia_pubmed_{ts}.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(rows, f, indent=2, ensure_ascii=False)
    print(f"Raw data saved → {json_path}")

    # Stats as JSON
    stats_json_path = f"armenia_pubmed_stats_{ts}.json"
    # make Counter objects JSON-serialisable
    serialisable_stats = json.loads(json.dumps(stats, default=list))
    with open(stats_json_path, "w", encoding="utf-8") as f:
        json.dump(serialisable_stats, f, indent=2, ensure_ascii=False)
    print(f"Statistics saved → {stats_json_path}")

    # CSV summary per year
    df = pd.DataFrame(
        [
            {"year": yr, "papers": cnt}
            for yr, cnt in stats["papers_per_year"].items()
        ]
    )
    csv_path = f"armenia_pubmed_yearly_{ts}.csv"
    df.to_csv(csv_path, index=False)
    print(f"Yearly CSV saved → {csv_path}")


# ── Entry point ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("Collecting PubMed records for Armenia affiliations (2020-2025)…")
    rows = collect_data()
    print(f"\nTotal qualifying records after affiliation filter: {len(rows)}")

    print("\nComputing statistics…")
    stats = compute_statistics(rows)

    print_report(stats)
    save_outputs(rows, stats)
