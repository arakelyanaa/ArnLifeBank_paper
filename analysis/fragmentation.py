#!/usr/bin/env python3
"""
Fragmentation analysis for the ArmLifeBank pipeline.

Computes:
  - Deposition rates (overall and within PMC-OA subset)
  - Repository classification: domain-standard / general-purpose / code-other
  - Shannon entropy and HHI over the article-to-repository distribution
  - Long-tail ratio
  - Article→repository bipartite graph metrics (cross-linkage, orphan rate)

dbSNP is excluded from all indices: its entries are references to known
variant IDs, not new data deposits, and would distort the fragmentation signal.

Usage:
  python analysis/fragmentation.py --country armenia
  python analysis/fragmentation.py --country latvia --longtail-threshold 5
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import pandas as pd

# ── Repository classification ─────────────────────────────────────────────────

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

# Excluded from all fragmentation indices
EXCLUDED_REPOS: set[str] = {"dbSNP"}

# Repositories known to cross-link to each other.
# A paper depositing in ≥2 repos from the same group is "discoverable"
# from either entry point.
CROSS_LINK_GROUPS: list[set[str]] = [
    {"GenBank", "ENA", "SRA", "BioProject", "BioSample"},   # INSDC family
    {"Gene Expression Omnibus", "SRA"},                      # GEO–SRA
]


# ── Helpers ───────────────────────────────────────────────────────────────────

def classify_repo(name: str) -> str:
    for cls, members in REPO_CLASSES.items():
        if name in members:
            return cls
    return "unclassified"


def is_cross_linked(repos: set[str]) -> bool:
    """Return True if ≥2 repos in the set belong to the same cross-link group."""
    return any(len(repos & group) >= 2 for group in CROSS_LINK_GROUPS)


def shannon_entropy(counts: list[int]) -> float:
    total = sum(counts)
    if total == 0:
        return 0.0
    return -sum((n / total) * math.log2(n / total) for n in counts if n > 0)


def hhi(counts: list[int]) -> float:
    """Herfindahl–Hirschman Index: sum of squared market shares."""
    total = sum(counts)
    if total == 0:
        return 0.0
    return sum((n / total) ** 2 for n in counts)


def normalise_hhi(raw: float, n: int) -> float:
    """Normalise HHI to [0, 1]: 0 = perfectly even, 1 = monopoly."""
    if n <= 1:
        return 1.0
    return (raw - 1 / n) / (1 - 1 / n)


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Compute fragmentation indices from pipeline output."
    )
    parser.add_argument("--country", default="armenia",
                        help="Country code matching output/{country}/ directory.")
    parser.add_argument("--output-dir", default=None, metavar="DIR",
                        help="Override output directory path.")
    parser.add_argument("--longtail-threshold", type=int, default=10, metavar="N",
                        help="Repos with fewer than N articles are counted as long-tail (default: 10).")
    args = parser.parse_args()

    root = Path(__file__).resolve().parent.parent
    out_dir = Path(args.output_dir) if args.output_dir else root / "output" / args.country

    # ── Load data ─────────────────────────────────────────────────────────────
    repo_df  = pd.read_csv(out_dir / "repository_counts.csv")
    links_df = pd.read_csv(out_dir / "article_repository_links.csv")
    arts_df  = pd.read_csv(out_dir / "articles.csv")
    summary  = json.loads((out_dir / "run_summary.json").read_text(encoding="utf-8"))

    # Apply exclusions
    repo_df  = repo_df[~repo_df["repository"].isin(EXCLUDED_REPOS)].copy()
    links_df = links_df[~links_df["repository"].isin(EXCLUDED_REPOS)].copy()

    # ── Deposition rates ──────────────────────────────────────────────────────
    aff = summary["affiliation_classification"]
    # Handle both old key (pre-refactor runs) and new key
    n_validated = int(aff.get("n_country_match") or aff.get("n_armenia_country", 0))
    n_oa        = int(summary["fulltext_retrieval"]["n_fulltext_retrieved"])

    # Unique articles that have ≥1 confirmed link (after dbSNP exclusion)
    n_depositing = links_df["pmid"].nunique()

    # Depositing articles within the OA full-text subset
    oa_pmids = set(
        arts_df.loc[arts_df["full_text_retrieval_status"] == "ok", "pmid"].astype(str)
    )
    n_depositing_oa = links_df.loc[
        links_df["pmid"].astype(str).isin(oa_pmids), "pmid"
    ].nunique()

    rate_overall = n_depositing    / n_validated if n_validated else 0.0
    rate_oa      = n_depositing_oa / n_oa        if n_oa        else 0.0

    # ── Repository classification ─────────────────────────────────────────────
    repo_df["class"] = repo_df["repository"].map(classify_repo)

    class_agg = (
        repo_df.groupby("class", sort=False)
        .agg(n_repos=("repository", "count"),
             n_articles=("n_articles_with_repository", "sum"))
        .reset_index()
    )
    total_article_mentions = int(class_agg["n_articles"].sum())
    class_agg["share"] = class_agg["n_articles"] / total_article_mentions

    # ── Fragmentation indices ─────────────────────────────────────────────────
    counts   = repo_df["n_articles_with_repository"].tolist()
    n_repos  = len(counts)

    H        = shannon_entropy(counts)
    H_max    = math.log2(n_repos) if n_repos > 1 else 1.0
    H_norm   = H / H_max

    HHI_raw  = hhi(counts)
    HHI_norm = normalise_hhi(HHI_raw, n_repos)

    lt_n     = args.longtail_threshold
    lt_mask  = repo_df["n_articles_with_repository"] < lt_n
    lt_articles = int(repo_df.loc[lt_mask, "n_articles_with_repository"].sum())
    lt_ratio = lt_articles / sum(counts) if counts else 0.0

    # ── Bipartite graph ───────────────────────────────────────────────────────
    article_repos: dict[str, set[str]] = (
        links_df.groupby("pmid")["repository"]
        .apply(set)
        .to_dict()
    )

    multi     = {p: r for p, r in article_repos.items() if len(r) > 1}
    n_multi   = len(multi)
    n_xlinked = sum(1 for repos in multi.values() if is_cross_linked(repos))
    n_orphan  = n_multi - n_xlinked
    xlink_rate  = n_xlinked / n_multi if n_multi else 0.0
    orphan_rate = n_orphan  / n_multi if n_multi else 0.0

    # ── Output: indices CSV ───────────────────────────────────────────────────
    rows = [
        ("deposition_rate_overall",           rate_overall,
         f"{n_depositing} / {n_validated} validated articles (dbSNP excluded)"),
        ("deposition_rate_oa_subset",         rate_oa,
         f"{n_depositing_oa} / {n_oa} OA full-text articles"),
        ("n_repositories_analysed",           n_repos,
         "after excluding dbSNP"),
        ("shannon_entropy_bits",              H,
         f"max possible = {H_max:.3f} bits for {n_repos} repos"),
        ("shannon_entropy_normalised",        H_norm,
         "0 = monopoly · 1 = perfectly even"),
        ("hhi_raw",                           HHI_raw,
         "sum of squared article-share; lower = more spread"),
        ("hhi_normalised",                    HHI_norm,
         "0 = perfectly even · 1 = monopoly"),
        (f"longtail_ratio_lt{lt_n}",          lt_ratio,
         f"share of depositing-article-mentions in repos with <{lt_n} articles"),
        ("n_articles_multi_repo",             n_multi,
         "articles depositing in >1 repository"),
        ("cross_link_rate",                   xlink_rate,
         f"fraction of multi-repo articles where repos cross-link ({n_xlinked}/{n_multi})"),
        ("orphan_rate",                       orphan_rate,
         f"fraction of multi-repo articles with no cross-linked pair ({n_orphan}/{n_multi})"),
    ]
    indices_df = pd.DataFrame(rows, columns=["metric", "value", "note"])
    indices_path = out_dir / "fragmentation_indices.csv"
    indices_df.to_csv(indices_path, index=False)

    # ── Output: Markdown report ───────────────────────────────────────────────
    country_name = (
        summary.get("country", {}).get("name")
        or args.country.capitalize()
    )
    cfg  = summary["config"]
    year_range = f"{cfg['start_year']}–{cfg['end_year']}"

    lines: list[str] = [
        f"# Fragmentation Analysis – {country_name} ({year_range})",
        "",
        f"*Generated from full pipeline run — {summary['run_datetime']}*  ",
        f"*dbSNP excluded from all indices (variant IDs, not deposited datasets)*",
        "",
        "---",
        "",
        "## 1. Deposition Rates",
        "",
        "| Scope | Depositing articles | Total | Rate |",
        "|-------|--------------------:|------:|-----:|",
        f"| All validated articles | {n_depositing} | {n_validated:,} | **{rate_overall:.1%}** |",
        f"| PMC OA (full-text accessible) | {n_depositing_oa} | {n_oa:,} | **{rate_oa:.1%}** |",
        "",
        "---",
        "",
        "## 2. Repository Classification",
        "",
        "| Class | Repositories | Article-mentions | Share |",
        "|-------|-------------:|-----------------:|------:|",
    ]
    class_order = ["domain_standard", "general_purpose", "code_other", "unclassified"]
    for cls in class_order:
        row = class_agg[class_agg["class"] == cls]
        if row.empty:
            continue
        r = row.iloc[0]
        lines.append(
            f"| {cls.replace('_', '-')} | {int(r['n_repos'])} "
            f"| {int(r['n_articles'])} | {r['share']:.1%} |"
        )

    lines += ["", "### Repositories by class", ""]
    for cls in class_order:
        subset = repo_df[repo_df["class"] == cls].sort_values(
            "n_articles_with_repository", ascending=False
        )
        if subset.empty:
            continue
        lines.append(f"**{cls.replace('_', '-')}**")
        lines.append("")
        lines.append("| Repository | Articles | Unique IDs |")
        lines.append("|------------|--------:|----------:|")
        for _, r in subset.iterrows():
            lines.append(
                f"| {r['repository']} | {r['n_articles_with_repository']} "
                f"| {r['n_unique_identifiers']} |"
            )
        lines.append("")

    lines += [
        "---",
        "",
        "## 3. Fragmentation Indices",
        "",
        f"> Computed over **{n_repos} repositories** "
        f"(article-count distribution; dbSNP excluded).",
        "",
        "| Index | Value | Interpretation |",
        "|-------|------:|----------------|",
        f"| Shannon entropy (H) | {H:.3f} bits | max = {H_max:.3f} bits for {n_repos} repos |",
        f"| H normalised | {H_norm:.3f} | 0 = monopoly · 1 = perfectly even |",
        f"| HHI | {HHI_raw:.4f} | lower = more fragmented |",
        f"| HHI normalised | {HHI_norm:.4f} | 0 = perfectly even · 1 = monopoly |",
        f"| Long-tail ratio (< {lt_n} articles) | {lt_ratio:.1%} "
        f"| share of deposit-mentions in repos used by < {lt_n} papers |",
        "",
        "---",
        "",
        "## 4. Article × Repository Bipartite Graph",
        "",
        "| Metric | n | Rate |",
        "|--------|--:|-----:|",
        f"| Articles with ≥1 deposit | {n_depositing} | {rate_overall:.1%} of validated |",
        f"| Articles depositing in > 1 repo | {n_multi} | {n_multi/n_depositing:.1%} of depositing |",
        f"| Multi-repo: repos cross-link | {n_xlinked} | {xlink_rate:.1%} of multi-repo |",
        f"| Multi-repo: orphaned (no cross-link) | {n_orphan} | {orphan_rate:.1%} of multi-repo |",
        "",
        "> **Cross-link groups:** INSDC (GenBank / ENA / SRA / BioProject / BioSample);",
        "> GEO–SRA (Gene Expression Omnibus / SRA).",
        "",
        "---",
        "",
        "## 5. Narrative Summary",
        "",
        f"Of {n_validated:,} Armenia-affiliated articles ({year_range}), "
        f"**{rate_overall:.1%}** ({n_depositing}) deposit data in any tracked repository "
        f"(after excluding dbSNP). "
        f"Within the PMC Open Access subset the rate rises to **{rate_oa:.1%}**, "
        f"suggesting that OA publication correlates with data sharing.",
        "",
        f"Deposits are spread across **{n_repos} repositories** "
        f"(H = {H:.2f} bits, H_norm = {H_norm:.2f}; HHI = {HHI_raw:.4f}). "
        f"A long-tail ratio of **{lt_ratio:.1%}** means that {lt_ratio:.0%} of depositing-article "
        f"mentions sit in repositories used by fewer than {lt_n} Armenian papers — "
        f"those datasets are effectively invisible to any country-level discovery query.",
        "",
        f"Of the {n_multi} articles that deposit in more than one repository, "
        f"only **{xlink_rate:.1%}** ({n_xlinked}) do so in repositories that cross-link "
        f"(INSDC family or GEO–SRA). "
        f"The remaining **{orphan_rate:.1%}** ({n_orphan}) are deposited across isolated silos "
        f"with no automatic discovery path between them — "
        f"exactly the gap a national-level catalogue would close.",
    ]

    md_path = out_dir / "fragmentation_report.md"
    md_path.write_text("\n".join(lines), encoding="utf-8")

    # ── Console summary ───────────────────────────────────────────────────────
    print(f"\nFragmentation analysis — {country_name} ({year_range})")
    print(f"  Repositories analysed : {n_repos}  (dbSNP excluded)")
    print(f"  Deposition rate       : {rate_overall:.1%} overall  |  {rate_oa:.1%} within OA")
    print(f"  Shannon H (normalised): {H:.3f} bits  ({H_norm:.3f} normalised)")
    print(f"  HHI (normalised)      : {HHI_raw:.4f}  ({HHI_norm:.4f} normalised)")
    print(f"  Long-tail ratio       : {lt_ratio:.1%}  (repos < {lt_n} articles)")
    print(f"  Cross-link rate       : {xlink_rate:.1%}  |  orphan rate: {orphan_rate:.1%}")
    print(f"\n  Outputs:")
    print(f"    {indices_path}")
    print(f"    {md_path}")


if __name__ == "__main__":
    main()
