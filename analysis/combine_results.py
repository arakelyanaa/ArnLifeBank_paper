#!/usr/bin/env python3
"""
Combine fragmentation and discoverability results across all countries/atlases
into unified comparison tables (CSV + Markdown).

Outputs written to output/ (top-level, not per-country):
  country_comparison.csv          -- fragmentation + deposition, all 4 countries
  country_comparison_gp_code.csv  -- same, general-purpose + code repos only
  discoverability_comparison.csv  -- atlas coverage for Armenia vs Leipzig
  combined_report.md              -- human-readable summary of all tables

Usage:
  python analysis/combine_results.py
  python analysis/combine_results.py --output-dir output/
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

# ── Configuration ─────────────────────────────────────────────────────────────

COUNTRIES = [
    ("armenia",           "Armenia"),
    ("georgia",           "Georgia"),
    ("estonia",           "Estonia"),
    ("leipzig_university","Leipzig University"),
]

DISC_SOURCES = [
    # (results_json_path, atlas_name, country_label)
    ("output/arm_discoverability/results.json", "ArmLifeBank",         "Armenia"),
    ("output/lha_discoverability/results.json", "Leipzig Health Atlas", "Leipzig University"),
]

# Fragmentation metrics to pull and their display names
FRAG_METRICS = [
    ("deposition_rate_overall",    "Deposition rate – all articles (%)"),
    ("deposition_rate_oa_subset",  "Deposition rate – OA articles (%)"),
    ("n_repositories_analysed",    "Repositories used"),
    ("shannon_entropy_bits",       "Shannon entropy H (bits)"),
    ("shannon_entropy_normalised", "Shannon H normalised"),
    ("hhi_raw",                    "HHI (raw)"),
    ("hhi_normalised",             "HHI normalised"),
    ("longtail_ratio_lt10",        "Long-tail ratio (< 10 articles) (%)"),
    ("n_articles_multi_repo",      "Articles depositing in > 1 repo"),
    ("cross_link_rate",            "Cross-link rate (%)"),
    ("orphan_rate",                "Multi-repo orphaned silos (%)"),
]

# Metrics that should be shown as percentages (multiplied by 100)
PCT_METRICS = {
    "deposition_rate_overall",
    "deposition_rate_oa_subset",
    "longtail_ratio_lt10",
    "cross_link_rate",
    "orphan_rate",
}


# ── Helpers ───────────────────────────────────────────────────────────────────

def load_fragmentation(country_dir: Path) -> dict[str, float]:
    idx = pd.read_csv(country_dir / "fragmentation_indices.csv")
    return dict(zip(idx["metric"], idx["value"]))


def load_fragmentation_gp_code(country_dir: Path) -> dict[str, float]:
    # File may be named fragmentation_gp_code_indices.csv or fragmentation_gp_indices.csv
    for name in ("fragmentation_gp_code_indices.csv", "fragmentation_gp_indices.csv"):
        p = country_dir / name
        if p.exists():
            idx = pd.read_csv(p)
            return dict(zip(idx["metric"], idx["value"]))
    return {}


def load_run_summary(country_dir: Path) -> dict:
    return json.loads((country_dir / "run_summary.json").read_text(encoding="utf-8"))


def pmc_oa_rate(summary: dict) -> float:
    ft = summary["fulltext_retrieval"]
    processed = ft["n_articles_processed"]
    retrieved = ft["n_fulltext_retrieved"]
    return retrieved / processed if processed else 0.0


def n_validated(summary: dict) -> int:
    aff = summary["affiliation_classification"]
    n = int(aff.get("n_country_match") or aff.get("n_armenia_country", 0))
    if n == 0:
        n = summary["fulltext_retrieval"]["n_articles_processed"]
    return n


def fmt(val: float, metric: str, decimals: int = 3) -> str:
    if metric in PCT_METRICS:
        return f"{val * 100:.1f}"
    if metric == "n_repositories_analysed" or metric == "n_articles_multi_repo":
        return str(int(val))
    return f"{val:.{decimals}f}"


# ── Table builders ────────────────────────────────────────────────────────────

def build_fragmentation_table(root: Path, suffix: str = "") -> pd.DataFrame:
    """
    Build a wide comparison table: rows = metrics, columns = countries.
    suffix: "" for all-repos, "_gp_code" for GP+code subset.
    """
    loader = load_fragmentation if suffix == "" else load_fragmentation_gp_code

    rows = []
    col_names = ["Metric"] + [label for _, label in COUNTRIES]

    # Header rows: corpus stats from run_summary
    for code, label in COUNTRIES:
        d = root / "output" / code
        s = load_run_summary(d)
        n_val = n_validated(s)
        n_oa  = s["fulltext_retrieval"]["n_fulltext_retrieved"]
        oa_rt = pmc_oa_rate(s)
        # Store for later; we'll add them as first rows
        if code == COUNTRIES[0][0]:
            # initialise header rows on first country
            header_rows = {
                "Validated articles":  [],
                "PMC OA articles":     [],
                "PMC OA rate (%)":     [],
            }
        header_rows["Validated articles"].append(f"{n_val:,}")
        header_rows["PMC OA articles"].append(f"{n_oa:,}")
        header_rows["PMC OA rate (%)"].append(f"{oa_rt * 100:.1f}")

    for metric_key, metric_label in FRAG_METRICS:
        row = {"Metric": metric_label}
        for code, label in COUNTRIES:
            d = root / "output" / code
            vals = loader(d)
            v = vals.get(metric_key)
            row[label] = fmt(v, metric_key) if v is not None else "—"
        rows.append(row)

    df_frag = pd.DataFrame(rows, columns=col_names)

    # Prepend corpus-level header rows
    header_df = pd.DataFrame(
        [{"Metric": k, **dict(zip([lab for _, lab in COUNTRIES], v))}
         for k, v in header_rows.items()],
        columns=col_names,
    )
    return pd.concat([header_df, df_frag], ignore_index=True)


def build_discoverability_table(root: Path) -> pd.DataFrame:
    rows = []
    for json_path, atlas_name, country_label in DISC_SOURCES:
        d = json.loads((root / json_path).read_text(encoding="utf-8"))
        t1 = d.get("tier1", {})
        t2 = d.get("tier2", {})
        combined = d.get("combined", {})
        rows.append({
            "Country / corpus":          country_label,
            "Atlas":                     atlas_name,
            "Total papers (2020–2025)":  d["n_papers_total"],
            "Papers citing any repo":    d["n_papers_with_any_repo"],
            "Atlas records harvested":   d["n_atlas_records_total"],
            "Records linked to PMIDs":   d["n_atlas_records_with_pmid_link"],
            "Papers discoverable (Tier 1 – PMID anchor)":  t1.get("n_papers_matched", 0),
            "Papers discoverable (Tier 2 – URL ref)":      t2.get("n_papers_matched", 0),
            "Papers discoverable (any tier)":              combined.get("n_papers_matched", 0),
            "% of papers with any repo (any tier)":        f"{combined.get('pct_of_papers_with_any_repo', 0):.2f}",
            "% of all papers (any tier)":                  f"{combined.get('pct_of_all_papers', 0):.3f}",
        })
    return pd.DataFrame(rows)


# ── Markdown rendering ────────────────────────────────────────────────────────

def df_to_md(df: pd.DataFrame) -> str:
    """Render a DataFrame as a GitHub-flavoured Markdown table."""
    col_widths = [max(len(str(df[c].max() if df[c].dtype != object else max(df[c], key=len))),
                      len(c)) + 2
                  for c in df.columns]
    lines = []
    header = "| " + " | ".join(c.ljust(col_widths[i]) for i, c in enumerate(df.columns)) + " |"
    sep    = "| " + " | ".join("-" * col_widths[i] for i in range(len(df.columns))) + " |"
    lines.append(header)
    lines.append(sep)
    for _, row in df.iterrows():
        lines.append(
            "| " + " | ".join(str(row[c]).ljust(col_widths[i]) for i, c in enumerate(df.columns)) + " |"
        )
    return "\n".join(lines)


def build_combined_report(
    frag_df: pd.DataFrame,
    frag_gp_df: pd.DataFrame,
    disc_df: pd.DataFrame,
) -> str:
    country_labels = [label for _, label in COUNTRIES]
    lines = [
        "# Combined Results — Fragmentation & Discoverability",
        "",
        "*Generated by `analysis/combine_results.py`*",
        "",
        "---",
        "",
        "## Table 1. Fragmentation and Deposition — All Repository Classes",
        "",
        "> Rows: corpus-level statistics + 11 fragmentation indices.  ",
        "> Deposition rates, long-tail ratio, cross-link rate, and orphan rate shown as %.  ",
        "> dbSNP excluded from all fragmentation indices.",
        "",
        df_to_md(frag_df),
        "",
        "---",
        "",
        "## Table 2. Fragmentation — General-Purpose and Code Repositories Only",
        "",
        "> Restricted to: Zenodo, Figshare, OSF, Mendeley Data, Dryad, Dataverse, GitHub, GitLab, ClinicalTrials.gov.  ",
        "> Isolates repository-choice fragmentation from discipline-specific domain-archive constraints.",
        "",
        df_to_md(frag_gp_df),
        "",
        "---",
        "",
        "## Table 3. Atlas Discoverability — ArmLifeBank vs Leipzig Health Atlas",
        "",
        "> **Tier 1 (PMID anchor):** an atlas record's linked publication list contains the paper's PMID.  ",
        "> **Tier 2 (URL reference):** the paper's full text contains a resolvable atlas URL.  ",
        "> Match methods are mutually exclusive; a paper is counted once at its highest tier.",
        "",
        df_to_md(disc_df),
        "",
        "---",
        "",
    ]
    return "\n".join(lines)


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Combine per-country fragmentation and discoverability results."
    )
    parser.add_argument("--output-dir", default="output", metavar="DIR",
                        help="Top-level output directory (default: output/)")
    args = parser.parse_args()

    root = Path(__file__).resolve().parent.parent
    out_dir = root / args.output_dir

    print("Building fragmentation comparison (all repos)…")
    frag_df = build_fragmentation_table(root, suffix="")

    print("Building fragmentation comparison (GP + code repos)…")
    frag_gp_df = build_fragmentation_table(root, suffix="_gp_code")

    print("Building discoverability comparison…")
    disc_df = build_discoverability_table(root)

    # ── Write CSVs ────────────────────────────────────────────────────────────
    frag_csv = out_dir / "country_comparison.csv"
    frag_df.to_csv(frag_csv, index=False)
    print(f"  Wrote {frag_csv}")

    frag_gp_csv = out_dir / "country_comparison_gp_code.csv"
    frag_gp_df.to_csv(frag_gp_csv, index=False)
    print(f"  Wrote {frag_gp_csv}")

    disc_csv = out_dir / "discoverability_comparison.csv"
    disc_df.to_csv(disc_csv, index=False)
    print(f"  Wrote {disc_csv}")

    # ── Write combined Markdown report ────────────────────────────────────────
    md = build_combined_report(frag_df, frag_gp_df, disc_df)
    md_path = out_dir / "combined_report.md"
    md_path.write_text(md, encoding="utf-8")
    print(f"  Wrote {md_path}")

    # ── Console preview ───────────────────────────────────────────────────────
    print()
    print("=== Fragmentation comparison (all repos) ===")
    print(frag_df.to_string(index=False))
    print()
    print("=== Discoverability comparison ===")
    print(disc_df[["Country / corpus", "Atlas", "Papers citing any repo",
                    "Papers discoverable (any tier)",
                    "% of papers with any repo (any tier)"]].to_string(index=False))


if __name__ == "__main__":
    main()
