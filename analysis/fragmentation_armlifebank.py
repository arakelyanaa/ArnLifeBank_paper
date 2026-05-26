#!/usr/bin/env python3
"""
Fragmentation analysis restricted to papers indexed in ArmLifeBank.

Reads the 36 PMIDs discoverable via ArmLifeBank from
  output/arm_discoverability/results.json
then filters Armenia's article_repository_links.csv to those PMIDs,
recomputes repository counts for the subset, and runs all the same
fragmentation indices as analysis/fragmentation.py.

Usage:
  python analysis/fragmentation_armlifebank.py
  python analysis/fragmentation_armlifebank.py --longtail-threshold 5
  python analysis/fragmentation_armlifebank.py --classes general_purpose,code_other
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import pandas as pd

# ── Repository classification (same as fragmentation.py) ──────────────────────

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

EXCLUDED_REPOS: set[str] = {"dbSNP"}

CROSS_LINK_GROUPS: list[set[str]] = [
    {"GenBank", "ENA", "SRA", "BioProject", "BioSample"},
    {"Gene Expression Omnibus", "SRA"},
]


# ── Helpers ───────────────────────────────────────────────────────────────────

def classify_repo(name: str) -> str:
    for cls, members in REPO_CLASSES.items():
        if name in members:
            return cls
    return "unclassified"


def is_cross_linked(repos: set[str]) -> bool:
    return any(len(repos & group) >= 2 for group in CROSS_LINK_GROUPS)


def shannon_entropy(counts: list[int]) -> float:
    total = sum(counts)
    if total == 0:
        return 0.0
    return -sum((n / total) * math.log2(n / total) for n in counts if n > 0)


def hhi(counts: list[int]) -> float:
    total = sum(counts)
    if total == 0:
        return 0.0
    return sum((n / total) ** 2 for n in counts)


def normalise_hhi(raw: float, n: int) -> float:
    if n <= 1:
        return 1.0
    return (raw - 1 / n) / (1 - 1 / n)


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Fragmentation indices for the ArmLifeBank-indexed subset."
    )
    parser.add_argument("--longtail-threshold", type=int, default=10, metavar="N")
    parser.add_argument(
        "--classes", default=None, metavar="CLASS[,CLASS...]",
        help="Comma-separated repo classes to include "
             "(domain_standard, general_purpose, code_other). Default: all.",
    )
    args = parser.parse_args()

    root = Path(__file__).resolve().parent.parent
    arm_dir  = root / "output" / "armenia"
    disc_dir = root / "output" / "arm_discoverability"

    # ── Resolve requested classes ─────────────────────────────────────────────
    all_classes = set(REPO_CLASSES.keys())
    if args.classes:
        requested_classes = {c.strip() for c in args.classes.split(",")}
        unknown = requested_classes - all_classes
        if unknown:
            parser.error(f"Unknown class(es): {', '.join(sorted(unknown))}. "
                         f"Valid: {', '.join(sorted(all_classes))}")
    else:
        requested_classes = all_classes

    _short = {"domain_standard": "domain", "general_purpose": "gp", "code_other": "code"}
    if requested_classes == all_classes:
        file_suffix = ""
    else:
        file_suffix = "_" + "_".join(
            _short[c] for c in ["domain_standard", "general_purpose", "code_other"]
            if c in requested_classes
        )

    # ── Load ArmLifeBank PMIDs ────────────────────────────────────────────────
    disc = json.loads((disc_dir / "results.json").read_text(encoding="utf-8"))
    arm_pmids: set[str] = set(disc["combined"]["pmids"])
    n_validated = len(arm_pmids)   # 36

    # ── Load Armenia pipeline outputs ─────────────────────────────────────────
    links_df = pd.read_csv(arm_dir / "article_repository_links.csv",
                           dtype={"pmid": str})
    arts_df  = pd.read_csv(arm_dir / "articles.csv", dtype={"pmid": str})

    # ── Filter to ArmLifeBank subset ──────────────────────────────────────────
    links_df = links_df[links_df["pmid"].isin(arm_pmids)].copy()
    arts_df  = arts_df[arts_df["pmid"].isin(arm_pmids)].copy()

    # ── Recompute repository_counts for this subset ───────────────────────────
    links_df = links_df[~links_df["repository"].isin(EXCLUDED_REPOS)].copy()

    if links_df.empty:
        repo_df = pd.DataFrame(columns=["repository",
                                         "n_articles_with_repository",
                                         "n_unique_identifiers"])
    else:
        repo_df = (
            links_df.groupby("repository", as_index=False)
            .agg(
                n_articles_with_repository=("pmid", "nunique"),
                n_unique_identifiers=("identifier", "nunique"),
            )
        )

    # ── Apply class filter (if requested) ─────────────────────────────────────
    if requested_classes != all_classes:
        included_repos = {
            repo for cls, members in REPO_CLASSES.items()
            if cls in requested_classes
            for repo in members
        }
        repo_df  = repo_df[repo_df["repository"].isin(included_repos)].copy()
        links_df = links_df[links_df["repository"].isin(included_repos)].copy()

    # ── Deposition rates ──────────────────────────────────────────────────────
    n_oa = int(arts_df["full_text_retrieval_status"].eq("ok").sum())

    n_depositing = links_df["pmid"].nunique()

    oa_pmids = set(arts_df.loc[arts_df["full_text_retrieval_status"] == "ok", "pmid"])
    n_depositing_oa = links_df.loc[links_df["pmid"].isin(oa_pmids), "pmid"].nunique()

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
    class_agg["share"] = class_agg["n_articles"] / total_article_mentions if total_article_mentions else 0.0

    # ── Fragmentation indices ─────────────────────────────────────────────────
    counts  = repo_df["n_articles_with_repository"].tolist()
    n_repos = len(counts)

    H       = shannon_entropy(counts)
    H_max   = math.log2(n_repos) if n_repos > 1 else 1.0
    H_norm  = H / H_max if H_max else 0.0

    HHI_raw  = hhi(counts)
    HHI_norm = normalise_hhi(HHI_raw, n_repos)

    lt_n     = args.longtail_threshold
    lt_mask  = repo_df["n_articles_with_repository"] < lt_n
    lt_articles = int(repo_df.loc[lt_mask, "n_articles_with_repository"].sum())
    lt_ratio = lt_articles / sum(counts) if counts else 0.0

    # ── Bipartite graph ───────────────────────────────────────────────────────
    article_repos: dict[str, set[str]] = (
        links_df.groupby("pmid")["repository"].apply(set).to_dict()
    )
    multi     = {p: r for p, r in article_repos.items() if len(r) > 1}
    n_multi   = len(multi)
    n_xlinked = sum(1 for repos in multi.values() if is_cross_linked(repos))
    n_orphan  = n_multi - n_xlinked
    xlink_rate  = n_xlinked / n_multi if n_multi else 0.0
    orphan_rate = n_orphan  / n_multi if n_multi else 0.0

    # ── Output: indices CSV ───────────────────────────────────────────────────
    rows = [
        ("n_armlifebank_papers",                n_validated,
         "ArmLifeBank-indexed papers (all tiers)"),
        ("n_oa_papers",                         n_oa,
         "ArmLifeBank papers with PMC OA full text retrieved"),
        ("deposition_rate_overall",             rate_overall,
         f"{n_depositing} / {n_validated} ArmLifeBank papers (dbSNP excluded)"),
        ("deposition_rate_oa_subset",           rate_oa,
         f"{n_depositing_oa} / {n_oa} OA full-text papers"),
        ("n_repositories_analysed",             n_repos,
         "after excluding dbSNP"),
        ("shannon_entropy_bits",                H,
         f"max possible = {H_max:.3f} bits for {n_repos} repos"),
        ("shannon_entropy_normalised",          H_norm,
         "0 = monopoly · 1 = perfectly even"),
        ("hhi_raw",                             HHI_raw,
         "sum of squared article-share; lower = more spread"),
        ("hhi_normalised",                      HHI_norm,
         "0 = perfectly even · 1 = monopoly"),
        (f"longtail_ratio_lt{lt_n}",            lt_ratio,
         f"share of depositing-article-mentions in repos with <{lt_n} articles"),
        ("n_articles_multi_repo",               n_multi,
         "articles depositing in >1 repository"),
        ("cross_link_rate",                     xlink_rate,
         f"fraction of multi-repo articles where repos cross-link ({n_xlinked}/{n_multi})"),
        ("orphan_rate",                         orphan_rate,
         f"fraction of multi-repo articles with no cross-linked pair ({n_orphan}/{n_multi})"),
    ]
    indices_df = pd.DataFrame(rows, columns=["metric", "value", "note"])

    out_dir = arm_dir
    indices_path = out_dir / f"fragmentation_armlifebank{file_suffix}_indices.csv"
    indices_df.to_csv(indices_path, index=False)

    # ── Output: Markdown report ───────────────────────────────────────────────
    lines: list[str] = [
        f"# Fragmentation Analysis – ArmLifeBank-indexed subset (Armenia 2020–2025)",
        "",
        f"*Subset: {n_validated} papers discoverable via ArmLifeBank "
        f"(output/arm_discoverability/results.json — combined tier)*  ",
        f"*dbSNP excluded from all indices*",
        "",
        "---",
        "",
        "## 1. Deposition Rates",
        "",
        "| Scope | Depositing articles | Total | Rate |",
        "|-------|--------------------:|------:|-----:|",
        f"| ArmLifeBank-indexed papers | {n_depositing} | {n_validated} | **{rate_overall:.1%}** |",
        f"| PMC OA (full-text accessible) | {n_depositing_oa} | {n_oa} | **{rate_oa:.1%}** |",
        "",
        f"> Note: {n_validated - n_depositing} of {n_validated} ArmLifeBank-indexed papers "
        f"have no detected repository link in the pipeline output (indexed via publication-anchor "
        f"without a detected external repo reference).",
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
        f"> Computed over **{n_repos} repositories** (article-count distribution; dbSNP excluded).",
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
        f"| Articles with ≥1 deposit | {n_depositing} | {rate_overall:.1%} of ArmLifeBank papers |",
        f"| Articles depositing in > 1 repo | {n_multi} | {n_multi/n_depositing:.1%} of depositing |" if n_depositing else
        f"| Articles depositing in > 1 repo | 0 | n/a |",
        f"| Multi-repo: repos cross-link | {n_xlinked} | {xlink_rate:.1%} of multi-repo |",
        f"| Multi-repo: orphaned (no cross-link) | {n_orphan} | {orphan_rate:.1%} of multi-repo |",
        "",
        "> **Cross-link groups:** INSDC (GenBank / ENA / SRA / BioProject / BioSample); GEO–SRA.",
    ]

    md_path = out_dir / f"fragmentation_armlifebank{file_suffix}_report.md"
    md_path.write_text("\n".join(lines), encoding="utf-8")

    # ── Console summary ───────────────────────────────────────────────────────
    print(f"\nFragmentation analysis — ArmLifeBank-indexed subset (Armenia 2020–2025)")
    print(f"  ArmLifeBank papers       : {n_validated}  (OA: {n_oa})")
    print(f"  With detected repo links : {n_depositing}  (no detected link: {n_validated - n_depositing})")
    print(f"  Repositories analysed    : {n_repos}  (dbSNP excluded)")
    print(f"  Deposition rate          : {rate_overall:.1%} overall  |  {rate_oa:.1%} within OA")
    print(f"  Shannon H (normalised)   : {H:.3f} bits  ({H_norm:.3f} normalised)")
    print(f"  HHI (normalised)         : {HHI_raw:.4f}  ({HHI_norm:.4f} normalised)")
    print(f"  Long-tail ratio          : {lt_ratio:.1%}  (repos < {lt_n} articles)")
    print(f"  Cross-link rate          : {xlink_rate:.1%}  |  orphan rate: {orphan_rate:.1%}")
    print(f"\n  Outputs:")
    print(f"    {indices_path}")
    print(f"    {md_path}")


if __name__ == "__main__":
    main()
