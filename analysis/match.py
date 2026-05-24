#!/usr/bin/env python3
"""
Match — Module 3
================
Cross-references a SEEK-based data atlas catalog against a corpus of
affiliated publications to determine which papers are discoverable through
the atlas.

Configured via a YAML file (default: config/lha.yaml).  Pass --config to
target a different platform (e.g. config/arm.yaml for ArmLifeBank).

Two match tiers are applied in order of confidence:

  Tier 1 — PMID anchor (confirmed)
      An atlas record's linked_pmids contains a corpus paper PMID.
      Covers both data_file records (linked via SEEK's publications
      relationship) and publication records (own PMID stored directly).

  Tier 2 — URL reference (confirmed)
      A corpus paper's evidence snippet contains the atlas base URL,
      resolved to a specific record by path.

Outputs
-------
  <output.match_results>
      One row per (corpus PMID, atlas record) pair.
      Columns: pmid, lha_id, lha_url, lha_title, tier, match_basis

  <output.per_tier_json>
      Machine-readable summary with all counts and matched record lists.

Usage
-----
  python analysis/match.py
  python analysis/match.py --config config/arm.yaml
  python analysis/match.py --log-level DEBUG
"""

from __future__ import annotations

import argparse
import json
import logging
import re
from pathlib import Path
from urllib.parse import urlparse

import pandas as pd

logger = logging.getLogger(__name__)

_REPO_ROOT      = Path(__file__).resolve().parent.parent
_DEFAULT_CONFIG = _REPO_ROOT / "config" / "lha.yaml"


def _load_config(path: Path) -> dict:
    import yaml
    with path.open(encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def _platform_key(cfg: dict) -> str:
    structural = {"target", "output", "cache", "comparators"}
    for key in cfg:
        if key not in structural:
            return key
    raise KeyError("No platform key found in config.")


def _index_path(cfg: dict) -> Path:
    out = cfg["output"]
    rel = out.get("index") or out.get("lha_index")
    if not rel:
        raise KeyError("config['output'] must have an 'index' or 'lha_index' key.")
    return _REPO_ROOT / rel


# ── Load inputs ───────────────────────────────────────────────────────────────

def _load_atlas_index(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    df["_pmids"] = df["linked_pmids"].apply(json.loads)
    df["_dois"]  = df["external_dois"].apply(json.loads)
    df["_urls"]  = df["external_urls"].apply(json.loads)
    logger.info("Atlas index: %d records loaded", len(df))
    return df


def _load_articles(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    df["pmid"] = df["pmid"].astype(str)
    logger.info("Articles: %d loaded", len(df))
    return df


def _load_links(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    df["pmid"] = df["pmid"].astype(str)
    logger.info("Repository links: %d loaded", len(df))
    return df


# ── Match tiers ───────────────────────────────────────────────────────────────

def _tier1_pmid_anchor(atlas: pd.DataFrame, corpus_pmids: set[str]) -> list[dict]:
    """
    Tier 1: atlas record's linked_pmids intersects with corpus paper PMIDs.
    Covers both data_file records (linked via SEEK publications relationship)
    and publication records (own PMID stored directly in linked_pmids).
    """
    matches = []
    for _, row in atlas.iterrows():
        rec_type = str(row.get("record_type", ""))
        basis    = "pmid_anchor_publication" if rec_type == "publication" else "pmid_anchor"
        for pmid in row["_pmids"]:
            if str(pmid) in corpus_pmids:
                matches.append({
                    "pmid":        str(pmid),
                    "lha_id":      str(row["lha_id"]),
                    "lha_url":     row["lha_url"],
                    "lha_title":   row["title"],
                    "tier":        1,
                    "match_basis": basis,
                })
    logger.info("Tier 1 (PMID anchor): %d matches", len(matches))
    return matches


_ATLAS_PATH_RE = re.compile(
    r"/(data_files|models|studies|investigations|assays|publications|"
    r"datasets?|phenotypes?|tools?|cohorts?)/(\w[\w\-]*)(?:[/?]|$)",
    re.IGNORECASE,
)


def _atlas_type_and_id_from_url(url: str) -> tuple[str, str] | None:
    """Return (record_type, record_id) extracted from an atlas URL, or None."""
    try:
        parsed = urlparse(url)
        path   = parsed.path.rstrip("/")
        m      = _ATLAS_PATH_RE.search(path)
        if m:
            return m.group(1).lower(), m.group(2)
    except Exception:
        pass
    return None


def _tier2_url_reference(
    links: pd.DataFrame,
    atlas: pd.DataFrame,
    already_matched: set[tuple[str, str]],
    base_url: str,
) -> list[dict]:
    """
    Tier 2: A corpus paper's evidence snippet or identifier contains the
    atlas base URL, resolved to an atlas record by path.
    """
    atlas_by_id = {str(row["lha_id"]): row for _, row in atlas.iterrows()}
    harvested_types = set(atlas["record_type"].str.lower().unique()) if "record_type" in atlas.columns else set()

    # Build a regex pattern from the base_url hostname
    host = urlparse(base_url).hostname or ""
    host_escaped = re.escape(host.lstrip("www."))
    url_pattern  = re.compile(
        rf"https?://(?:www\.)?{host_escaped}/[^\s\"',>]+",
        re.IGNORECASE,
    )

    matches = []
    text_cols = [c for c in ("identifier", "evidence_snippet") if c in links.columns]

    for _, link_row in links.iterrows():
        pmid     = str(link_row["pmid"])
        combined = " ".join(str(link_row.get(c, "")) for c in text_cols)
        for url in url_pattern.findall(combined):
            parsed_url = _atlas_type_and_id_from_url(url)
            if not parsed_url:
                continue
            rec_type, record_id = parsed_url
            pair = (pmid, record_id)
            if pair in already_matched:
                continue
            already_matched.add(pair)
            if record_id in atlas_by_id:
                row = atlas_by_id[record_id]
                matches.append({
                    "pmid":        pmid,
                    "lha_id":      record_id,
                    "lha_url":     row["lha_url"],
                    "lha_title":   row["title"],
                    "tier":        2,
                    "match_basis": f"url_reference:{url}",
                })
            else:
                matches.append({
                    "pmid":        pmid,
                    "lha_id":      f"{rec_type}/{record_id}",
                    "lha_url":     url,
                    "lha_title":   f"(type '{rec_type}' not in harvest)",
                    "tier":        2,
                    "match_basis": f"url_reference_unresolved:{url}",
                })

    logger.info("Tier 2 (URL reference): %d matches", len(matches))
    return matches


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Match an atlas catalog against a corpus of publications."
    )
    parser.add_argument("--config", default=str(_DEFAULT_CONFIG), metavar="PATH",
                        help="Path to YAML config (default: config/lha.yaml).")
    parser.add_argument("--log-level", default="INFO",
                        choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    cfg_path = Path(args.config)
    cfg      = _load_config(cfg_path)
    pk       = _platform_key(cfg)
    base_url = cfg[pk]["base_url"]

    index_path    = _index_path(cfg)
    articles_path = _REPO_ROOT / cfg["target"]["input_articles"]
    links_path    = _REPO_ROOT / cfg["target"]["input_links"]
    out_csv       = _REPO_ROOT / cfg["output"]["match_results"]
    out_json      = _REPO_ROOT / cfg["output"]["per_tier_json"]
    out_csv.parent.mkdir(parents=True, exist_ok=True)

    # ── Load ──────────────────────────────────────────────────────────────
    atlas = _load_atlas_index(index_path)
    art   = _load_articles(articles_path)
    links = _load_links(links_path)

    corpus_pmids      = set(art["pmid"].astype(str))
    papers_with_repos = links["pmid"].nunique()

    # ── Run tiers ─────────────────────────────────────────────────────────
    t1_matches  = _tier1_pmid_anchor(atlas, corpus_pmids)
    already     = {(m["pmid"], m["lha_id"]) for m in t1_matches}
    t2_matches  = _tier2_url_reference(links, atlas, already, base_url)
    all_matches = t1_matches + t2_matches

    # ── Write match_results.csv ───────────────────────────────────────────
    df_matches = pd.DataFrame(
        all_matches if all_matches else [],
        columns=["pmid", "lha_id", "lha_url", "lha_title", "tier", "match_basis"],
    )
    df_matches.to_csv(out_csv, index=False)
    logger.info("match_results.csv: %d rows written", len(df_matches))

    # ── Compute summary stats ─────────────────────────────────────────────
    matched_pmids_t1  = {m["pmid"] for m in t1_matches}
    matched_pmids_t2  = {m["pmid"] for m in t2_matches}
    matched_pmids_all = matched_pmids_t1 | matched_pmids_t2

    atlas_records_t1  = {m["lha_id"] for m in t1_matches}
    atlas_records_t2  = {m["lha_id"] for m in t2_matches}
    atlas_records_all = atlas_records_t1 | atlas_records_t2

    n_atlas_total     = len(atlas)
    n_atlas_with_pmid = int((atlas["linked_pmids"] != "[]").sum())

    results = {
        "target":                        cfg["target"]["name"],
        "platform":                      pk,
        "base_url":                      base_url,
        "n_papers_total":                len(corpus_pmids),
        "n_papers_with_any_repo":        papers_with_repos,
        "n_atlas_records_total":         n_atlas_total,
        "n_atlas_records_with_pmid_link": n_atlas_with_pmid,
        # legacy key for backward compat with lha_report.py
        "n_lha_records_total":           n_atlas_total,
        "n_lha_records_with_pmid_link":  n_atlas_with_pmid,
        "tier1": {
            "name":             "PMID anchor",
            "n_matches":        len(t1_matches),
            "n_papers_matched": len(matched_pmids_t1),
            "n_lha_records":    len(atlas_records_t1),
            "pmids":            sorted(matched_pmids_t1),
            "lha_ids":          sorted(atlas_records_t1),
        },
        "tier2": {
            "name":             "URL reference",
            "n_matches":        len(t2_matches),
            "n_papers_matched": len(matched_pmids_t2),
            "n_lha_records":    len(atlas_records_t2),
            "pmids":            sorted(matched_pmids_t2),
            "lha_ids":          sorted(atlas_records_t2),
        },
        "combined": {
            "n_papers_matched":            len(matched_pmids_all),
            "n_lha_records_matched":       len(atlas_records_all),
            "pct_of_all_papers":           round(len(matched_pmids_all) / len(corpus_pmids) * 100, 3) if corpus_pmids else 0,
            "pct_of_papers_with_any_repo": round(len(matched_pmids_all) / papers_with_repos * 100, 3) if papers_with_repos else 0,
            "pmids":                       sorted(matched_pmids_all),
        },
        "matches": all_matches,
    }

    out_json.write_text(json.dumps(results, indent=2), encoding="utf-8")
    logger.info("results.json written")

    # ── Console summary ───────────────────────────────────────────────────
    target_name = cfg["target"]["name"]
    c = results["combined"]
    print(f"\n{'='*62}")
    print(f"  Discoverability — {target_name} via {pk.upper()}")
    print(f"{'='*62}")
    print(f"  Config                        : {cfg_path}")
    print(f"  Corpus papers total           : {len(corpus_pmids):>6,}")
    print(f"  Papers with any repo mention  : {papers_with_repos:>6,}")
    print(f"  Atlas catalog records         : {n_atlas_total:>6,}")
    print(f"")
    print(f"  Tier 1 (PMID anchor) matches  : {len(matched_pmids_t1):>6}  papers  "
          f"/ {len(atlas_records_t1)} atlas records")
    print(f"  Tier 2 (URL reference) matches: {len(matched_pmids_t2):>6}  papers  "
          f"/ {len(atlas_records_t2)} atlas records")
    print(f"")
    print(f"  Combined unique papers matched : {c['n_papers_matched']:>6}")
    print(f"  Combined atlas records matched : {c['n_lha_records_matched']:>6}")
    print(f"")
    print(f"  Discoverability rate")
    print(f"    of all corpus papers         : {c['pct_of_all_papers']:.3f}%")
    print(f"    of papers with any repo      : {c['pct_of_papers_with_any_repo']:.3f}%")
    print(f"{'='*62}")
    print(f"  Outputs: {out_csv}")
    print(f"           {out_json}")

    if all_matches:
        print(f"\n  Matched papers:")
        for m in sorted(all_matches, key=lambda x: (x["tier"], x["pmid"])):
            print(f"    [T{m['tier']}] PMID {m['pmid']}  →  "
                  f"[{m['lha_id']}]  {m['lha_title'][:50]}")


if __name__ == "__main__":
    main()
