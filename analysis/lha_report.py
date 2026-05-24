#!/usr/bin/env python3
"""
Report — Module 4
=================
Reads results.json (from match.py) and writes a Markdown summary report.

Configured via a YAML file (default: config/lha.yaml).  Pass --config to
target a different platform (e.g. config/arm.yaml for ArmLifeBank).

Outputs:
  <output.summary_report>  (e.g. output/arm_discoverability/summary.md)

Usage:
  python analysis/lha_report.py
  python analysis/lha_report.py --config config/arm.yaml
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import yaml

_REPO_ROOT      = Path(__file__).resolve().parent.parent
_DEFAULT_CONFIG = _REPO_ROOT / "config" / "lha.yaml"


def _load_config(path: Path) -> dict:
    with path.open(encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def _article_info(pmid: str, articles_path: Path) -> str:
    """Return a short citation line for a PMID by looking up articles.csv."""
    try:
        import pandas as pd
        art = pd.read_csv(articles_path, dtype={"pmid": str})
        row = art[art["pmid"] == pmid]
        if row.empty:
            return f"PMID {pmid}"
        r = row.iloc[0]
        title = str(r.get("title", "")) or ""
        year  = str(r.get("pub_year", r.get("year", ""))) or ""
        doi   = str(r.get("doi",   "")) or ""
        return f"PMID {pmid} ({year}): {title[:80]}{'…' if len(title)>80 else ''}" + \
               (f" doi:{doi}" if doi and doi != "nan" else "")
    except Exception:
        return f"PMID {pmid}"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate a Markdown discoverability report from results.json."
    )
    parser.add_argument("--config", default=str(_DEFAULT_CONFIG), metavar="PATH",
                        help="Path to YAML config (default: config/lha.yaml).")
    args = parser.parse_args()

    cfg_path = Path(args.config)
    cfg      = _load_config(cfg_path)

    # Detect platform key and atlas name
    structural   = {"target", "output", "cache", "comparators"}
    pk           = next((k for k in cfg if k not in structural), "lha")
    base_url     = cfg[pk].get("base_url", "")
    atlas_name   = {"lha": "Leipzig Health Atlas (LHA)",
                    "arm": "ArmLifeBank"}.get(pk, pk.upper())
    target_name  = cfg["target"]["name"]
    articles_path = _REPO_ROOT / cfg["target"]["input_articles"]

    in_json = _REPO_ROOT / cfg["output"]["per_tier_json"]
    out_md  = _REPO_ROOT / cfg["output"]["summary_report"]
    out_md.parent.mkdir(parents=True, exist_ok=True)

    results = json.loads(in_json.read_text(encoding="utf-8"))

    n_total      = results["n_papers_total"]
    n_repos      = results["n_papers_with_any_repo"]
    n_atlas      = results.get("n_atlas_records_total", results.get("n_lha_records_total", 0))
    n_atlas_link = results.get("n_atlas_records_with_pmid_link",
                               results.get("n_lha_records_with_pmid_link", 0))

    t1 = results["tier1"]
    t2 = results["tier2"]
    c  = results["combined"]

    # ── Tier 2: split resolved vs unresolved ─────────────────────────────────
    t2_resolved   = [m for m in results["matches"] if m["tier"] == 2
                     and "unresolved" not in m["match_basis"]]
    t2_unresolved = [m for m in results["matches"] if m["tier"] == 2
                     and "unresolved" in m["match_basis"]]

    # ── Build Markdown ────────────────────────────────────────────────────────
    lines: list[str] = []

    def h(level: int, text: str) -> None:
        lines.append(f"{'#' * level} {text}\n")

    def p(text: str = "") -> None:
        lines.append(text + "\n")

    h(1, f"{atlas_name} Discoverability Analysis — {target_name} (2020–2025)")

    p(f"**Research question:** Of all data products referenced in {target_name}–"
      f"affiliated biomedical publications (2020–2025), what percentage are "
      f"discoverable through {atlas_name}?")
    p()

    h(2, "Summary")

    p(f"| Metric | Value |")
    p(f"|--------|-------|")
    p(f"| {target_name} papers analysed (2020–2025) | {n_total:,} |")
    p(f"| Papers citing any external data repository | {n_repos:,} |")
    p(f"| {atlas_name} records harvested | {n_atlas:,} |")
    p(f"| Records with at least one linked publication | {n_atlas_link} |")
    p(f"| **{target_name} papers discoverable via {atlas_name} (any tier)** | **{c['n_papers_matched']}** |")
    p(f"| Atlas records matched | {c['n_lha_records_matched']} |")
    p()

    h(2, "Headline Answer")

    pct_repos = c["pct_of_papers_with_any_repo"]
    pct_all   = c["pct_of_all_papers"]
    p(f"**{pct_repos:.2f}%** of {target_name} papers that cite any external repository "
      f"({c['n_papers_matched']} of {n_repos:,}) have at least one record "
      f"discoverable through {atlas_name}.")
    p()
    p(f"**{pct_all:.3f}%** of all {target_name} papers ({c['n_papers_matched']} of {n_total:,}) "
      f"are represented in {atlas_name}.")
    p()

    h(2, "Match breakdown by tier")

    h(3, "Tier 1 — PMID anchor (confirmed)")
    p(f"An atlas record's SEEK publications relationship or own PubMed ID "
      f"matches a {target_name} paper. This is the highest-confidence match.")
    p()
    p(f"- Papers matched: **{t1['n_papers_matched']}**")
    p(f"- Atlas records matched: **{t1['n_lha_records']}**")
    p()
    if t1["pmids"]:
        p("| PMID | Atlas ID | Title |")
        p("|------|----------|-------|")
        for m in results["matches"]:
            if m["tier"] == 1:
                p(f"| {m['pmid']} | [{m['lha_id']}]({m['lha_url']}) | {m['lha_title']} |")
        p()

    h(3, "Tier 2 — URL reference")
    host_display = base_url.lstrip("https://").lstrip("http://").rstrip("/")
    p(f"A {target_name} paper's full text contains a `{host_display}` URL "
      f"resolved to an atlas record by path.")
    p()
    p(f"- Papers matched: **{t2['n_papers_matched']}**")
    p(f"- Atlas records matched (resolved): **{len(t2_resolved)}**")
    p(f"- Unresolved (record type not in harvest): **{len(t2_unresolved)}**")
    p()
    if results["matches"]:
        t2_all = [m for m in results["matches"] if m["tier"] == 2]
        if t2_all:
            p("| PMID | Atlas reference | Status |")
            p("|------|----------------|--------|")
            for m in t2_all:
                status = "resolved" if "unresolved" not in m["match_basis"] else "unresolved"
                p(f"| {m['pmid']} | [{m['lha_id']}]({m['lha_url']}) | {status} |")
            p()

    h(2, "Matched papers — detail")

    seen_pmids: set[str] = set()
    for m in sorted(results["matches"], key=lambda x: (x["tier"], x["pmid"])):
        pmid = m["pmid"]
        if pmid not in seen_pmids:
            seen_pmids.add(pmid)
            info = _article_info(pmid, articles_path)
            p(f"**{info}**")
        label = m["lha_title"] if m["lha_title"] else m["lha_id"]
        p(f"- Tier {m['tier']} — [{label}]({m['lha_url']}) `{m['match_basis']}`")
    p()

    h(2, "Methods")

    p(f"**Harvest (Module 1):** {atlas_name} catalog indexed via the SEEK JSON:API. "
      f"Data files and publications retrieved via paginated requests; per-record "
      f"detail pages fetched to resolve publications relationships. "
      f"Rate limited to 1 req/s. Raw responses cached under `.cache/{pk}/raw/`.")
    p()
    p("**Normalize (Module 2):** DOIs, accessions, and URLs normalised using "
      "`analysis/normalize.py` (108 unit tests).")
    p()
    p(f"**Match (Module 3):** Two tiers applied in order: "
      f"(1) PMID anchor — atlas `linked_pmids` ∩ {target_name} paper PMIDs; "
      f"(2) URL reference — `{host_display}` URLs extracted from "
      f"{target_name} paper evidence snippets and resolved to atlas record IDs.")
    p()
    p("**Report (Module 4):** This document, generated by `analysis/lha_report.py`.")
    p()

    out_md.write_text("".join(lines), encoding="utf-8")
    print(f"Report written → {out_md}")


if __name__ == "__main__":
    main()
