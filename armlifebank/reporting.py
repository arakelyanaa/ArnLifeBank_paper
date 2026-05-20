"""
Aggregation and reporting for the ArmLifeBank pipeline.

Produces:
  articles.csv                  – one row per validated Armenia-country article
  article_repository_links.csv  – one row per repository/identifier per article
  repository_counts.csv         – one row per repository with aggregate counts
  yearly_repository_counts.csv  – counts broken down by publication year
  run_summary.json              – machine-readable run metadata
  report.md                     – human-readable Markdown summary
"""

from __future__ import annotations

import json
import logging
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

from armlifebank.affiliation import ArticleClassification
from armlifebank.fulltext import FullTextResult
from armlifebank.repositories import RepoMatch

logger = logging.getLogger(__name__)

# ── articles.csv ──────────────────────────────────────────────────────────────

def build_articles_df(
    articles: list[dict],
    classifications: list[ArticleClassification],
    ft_results: list[FullTextResult],
    confirmed_links: list[RepoMatch],
) -> pd.DataFrame:
    """One row per validated Armenia-country article with all pipeline columns."""

    cl_by_pmid   = {c.pmid: c  for c in classifications}
    ft_by_pmid   = {r.pmid: r  for r in ft_results}
    # repo links per article
    links_by_pmid: dict[str, list[RepoMatch]] = defaultdict(list)
    for m in confirmed_links:
        links_by_pmid[m.pmid].append(m)

    rows = []
    for art in articles:
        pmid = art.get("pmid", "")
        cl   = cl_by_pmid.get(pmid)
        ft   = ft_by_pmid.get(pmid)
        links = links_by_pmid.get(pmid, [])

        # ── bibliographic ─────────────────────────────────────────────
        pub_types = "; ".join(art.get("pub_types", []))
        mesh      = "; ".join(art.get("mesh_terms", []))
        keywords  = "; ".join(art.get("keywords", []))
        authors   = art.get("authors", [])
        n_authors = len(authors)
        affiliations_flat = " | ".join(art.get("all_affiliations", []))

        # ── affiliation classification ────────────────────────────────
        aff_label = cl.label if cl else "unknown"

        # ── full-text / OA ────────────────────────────────────────────
        has_pmcid    = ft.has_pmcid    if ft else False
        pmcid        = ft.pmcid        if ft else art.get("pmcid", "")
        is_pmc_oa    = ft.is_pmc_oa    if ft else False
        oa_license   = ft.oa_license   if ft else ""
        ft_source    = ft.full_text_source            if ft else ""
        ft_status    = ft.full_text_retrieval_status  if ft else "not_processed"

        # ── repository / data references ─────────────────────────────
        repos_set = {m.repository for m in links}
        n_raw_accessions  = sum(
            1 for m in links
            if m.repository_category in (
                "raw_reads", "nucleotide_sequence", "transcriptomics",
                "proteomics", "metabolomics",
            )
        )
        n_general_repo    = sum(
            1 for m in links
            if m.repository_category == "general_repository"
        )

        rows.append({
            # Identifiers
            "pmid":             pmid,
            "doi":              art.get("doi", ""),
            "pmcid":            pmcid,
            # Bibliographic
            "title":            art.get("title", ""),
            "journal":          art.get("journal", ""),
            "journal_abbrev":   art.get("journal_abbrev", ""),
            "volume":           art.get("volume", ""),
            "issue":            art.get("issue", ""),
            "pages":            art.get("pages", ""),
            "pub_year":         art.get("pub_year", ""),
            "pub_month":        art.get("pub_month", ""),
            "pub_types":        pub_types,
            "mesh_terms":       mesh,
            "keywords":         keywords,
            "n_authors":        n_authors,
            "affiliations":     affiliations_flat,
            # Affiliation classification
            "affiliation_label": aff_label,
            # OA / full-text
            "has_pmcid":                  has_pmcid,
            "is_pmc_oa":                  is_pmc_oa,
            "oa_license":                 oa_license,
            "full_text_source":           ft_source,
            "full_text_retrieval_status": ft_status,
            # Data references
            "has_any_data_reference":     len(links) > 0,
            "n_repository_links":         len(links),
            "repositories_detected":      "; ".join(sorted(repos_set)),
            "n_raw_data_accessions":      n_raw_accessions,
            "n_general_repository_dois":  n_general_repo,
        })

    return pd.DataFrame(rows)


# ── repository_counts.csv ─────────────────────────────────────────────────────

def build_repository_counts_df(confirmed_links: list[RepoMatch]) -> pd.DataFrame:
    """One row per repository with aggregate counts."""
    if not confirmed_links:
        return pd.DataFrame()

    repo_articles:     dict[str, set[str]]  = defaultdict(set)
    repo_identifiers:  dict[str, set[str]]  = defaultdict(set)
    repo_mentions:     dict[str, int]        = defaultdict(int)
    repo_category:     dict[str, str]        = {}
    repo_sources:      dict[str, set[str]]  = defaultdict(set)
    repo_examples:     dict[str, list[str]] = defaultdict(list)

    for m in confirmed_links:
        r = m.repository
        repo_articles[r].add(m.pmid)
        repo_identifiers[r].add(m.identifier)
        repo_mentions[r] += 1
        repo_category[r] = m.repository_category
        repo_sources[r].add(m.evidence_source)
        if len(repo_examples[r]) < 3:
            repo_examples[r].append(m.identifier)

    rows = []
    for repo in sorted(repo_articles.keys()):
        rows.append({
            "repository":               repo,
            "repository_category":      repo_category[repo],
            "n_articles_with_repository": len(repo_articles[repo]),
            "n_unique_identifiers":     len(repo_identifiers[repo]),
            "n_total_mentions":         repo_mentions[repo],
            "example_identifiers":      "; ".join(repo_examples[repo]),
            "evidence_sources_used":    "; ".join(sorted(repo_sources[repo])),
            "notes":                    "",
        })

    df = pd.DataFrame(rows)
    return df.sort_values("n_articles_with_repository", ascending=False).reset_index(drop=True)


# ── yearly_repository_counts.csv ─────────────────────────────────────────────

def build_yearly_repo_df(
    confirmed_links: list[RepoMatch],
    articles: list[dict],
) -> pd.DataFrame:
    """Counts broken down by publication year and repository."""
    if not confirmed_links:
        return pd.DataFrame()

    year_by_pmid = {a["pmid"]: a.get("pub_year", "") for a in articles}

    yearly: dict[tuple[str, str], dict[str, Any]] = defaultdict(
        lambda: {"n_articles": set(), "n_identifiers": set()}
    )
    for m in confirmed_links:
        year = year_by_pmid.get(m.pmid, "unknown")
        key  = (year, m.repository)
        yearly[key]["n_articles"].add(m.pmid)
        yearly[key]["n_identifiers"].add(m.identifier)

    rows = [
        {
            "publication_year":  year,
            "repository":        repo,
            "n_articles":        len(v["n_articles"]),
            "n_identifiers":     len(v["n_identifiers"]),
        }
        for (year, repo), v in sorted(yearly.items())
    ]
    return pd.DataFrame(rows)


# ── run_summary.json ──────────────────────────────────────────────────────────

def build_run_summary(
    cfg,                             # Config object
    articles_all: list[dict],        # all fetched articles (pre-classification)
    classifications: list[ArticleClassification],
    ft_results: list[FullTextResult],
    confirmed_links: list[RepoMatch],
    diag_links: list[RepoMatch],
    year_pmid_counts: dict[int, int],
) -> dict:
    country_code  = getattr(cfg, "country_code", "armenia")
    country_name  = cfg.country_profile.get("name", country_code.capitalize()) if hasattr(cfg, "country_profile") else "Armenia"
    match_label   = f"{country_code}_country"
    no_match_label = f"not_{country_code}_country"

    n_candidates  = sum(year_pmid_counts.values())
    n_validated   = sum(1 for c in classifications if c.label == match_label)
    n_excluded    = sum(1 for c in classifications if c.label == no_match_label)
    n_uncertain   = sum(1 for c in classifications if c.label == "uncertain")
    n_pmcid       = sum(1 for r in ft_results if r.has_pmcid)
    n_oa          = sum(1 for r in ft_results if r.is_pmc_oa)
    n_ft_ok       = sum(1 for r in ft_results if r.full_text_retrieval_status == "ok")
    n_with_data   = len({m.pmid for m in confirmed_links})

    repo_counts: dict[str, int] = {}
    for m in confirmed_links:
        repo_counts[m.repository] = repo_counts.get(m.repository, 0) + 1

    return {
        "run_datetime":         datetime.now().isoformat(timespec="seconds"),
        "pipeline_version":     "1.0.0",
        "country": {
            "code": country_code,
            "name": country_name,
        },
        "config": {
            "start_year":  cfg.start_year,
            "end_year":    cfg.end_year,
            "mode":        cfg.mode,
            "sample_size": cfg.sample_size,
        },
        "pubmed_query_template": cfg.query_template,
        "pubmed_hits_per_year":  {str(k): v for k, v in year_pmid_counts.items()},
        "n_candidate_pmids":     n_candidates,
        "n_fetched_articles":    len(articles_all),
        "affiliation_classification": {
            "n_country_match":  n_validated,
            "n_excluded":       n_excluded,
            "n_uncertain":      n_uncertain,
            "mode":             cfg.mode,
        },
        "fulltext_retrieval": {
            "n_articles_processed": len(ft_results),
            "n_with_pmcid":         n_pmcid,
            "n_pmc_oa":             n_oa,
            "n_fulltext_retrieved": n_ft_ok,
        },
        "repository_extraction": {
            "n_confirmed_links":            len(confirmed_links),
            "n_diagnostic_links":           len(diag_links),
            "n_articles_with_data_reference": n_with_data,
            "counts_by_repository":         repo_counts,
        },
        "limitations": [
            "Affiliation classification is rule-based; edge cases may be misclassified.",
            "Full-text analysis limited to PMC Open Access subset (~{:.0f}% of validated articles).".format(
                100 * n_oa / max(n_validated, 1)
            ),
            "Repository detection relies on regex; accessions in figures/tables may be missed.",
            "GenBank accession patterns have medium confidence and may include false positives.",
            "Sample mode was{} used; results may not represent the full corpus.".format(
                "" if cfg.sample_size else " not"
            ),
        ],
    }


# ── Markdown report ───────────────────────────────────────────────────────────

def build_markdown_report(summary: dict, repo_counts_df: pd.DataFrame) -> str:
    cfg          = summary["config"]
    aff          = summary["affiliation_classification"]
    ft           = summary["fulltext_retrieval"]
    repos        = summary["repository_extraction"]
    hits         = summary["pubmed_hits_per_year"]
    country_name = summary.get("country", {}).get("name", "Country")

    lines: list[str] = [
        f"# ArmLifeBank – PubMed {country_name} Affiliation Audit",
        "",
        f"**Run date:** {summary['run_datetime']}  ",
        f"**Country:** {country_name}  ",
        f"**Years:** {cfg['start_year']}–{cfg['end_year']}  ",
        f"**Mode:** {cfg['mode']}  ",
        f"**Sample size:** {cfg['sample_size'] or 'full run'}  ",
        "",
        "---",
        "",
        "## 1. PubMed Search",
        "",
        f"Query template: `{summary['pubmed_query_template']}`",
        "",
        "| Year | Candidate PMIDs |",
        "|------|----------------|",
    ]
    for yr, cnt in sorted(hits.items()):
        lines.append(f"| {yr} | {cnt} |")
    lines += [
        "",
        f"**Total candidates:** {summary['n_candidate_pmids']}  ",
        f"**Fetched:** {summary['n_fetched_articles']}  ",
        "",
        "---",
        "",
        "## 2. Affiliation Classification",
        "",
        f"| Label | Count |",
        f"|-------|-------|",
        f"| {country_name} country | {aff['n_country_match']} |",
        f"| Not {country_name} (excluded) | {aff['n_excluded']} |",
        f"| Uncertain | {aff['n_uncertain']} |",
        "",
        "---",
        "",
        "## 3. Open Access Full-Text Retrieval",
        "",
        f"| Metric | Count |",
        f"|--------|-------|",
        f"| Validated {country_name} articles | {aff['n_country_match']} |",
        f"| With PMCID | {ft['n_with_pmcid']} |",
        f"| PMC Open Access | {ft['n_pmc_oa']} |",
        f"| Full text retrieved | {ft['n_fulltext_retrieved']} |",
        "",
        "---",
        "",
        "## 4. Data Repository References",
        "",
        f"**Articles with ≥1 repository link:** {repos['n_articles_with_data_reference']}  ",
        f"**Total confirmed links:** {repos['n_confirmed_links']}  ",
        f"**Diagnostic (low-confidence) links:** {repos['n_diagnostic_links']}  ",
        "",
    ]

    if not repo_counts_df.empty:
        lines += [
            "### Repository breakdown",
            "",
            "| Repository | Category | Articles | Unique IDs |",
            "|------------|----------|----------|------------|",
        ]
        for _, row in repo_counts_df.iterrows():
            lines.append(
                f"| {row['repository']} | {row['repository_category']} "
                f"| {row['n_articles_with_repository']} | {row['n_unique_identifiers']} |"
            )
        lines.append("")

    lines += [
        "---",
        "",
        "## 5. Limitations",
        "",
    ]
    for lim in summary["limitations"]:
        lines.append(f"- {lim}")
    lines += [
        "",
        "---",
        "",
        "*Generated by ArmLifeBank pipeline v{}*".format(summary["pipeline_version"]),
    ]

    return "\n".join(lines)


# ── Master write function ─────────────────────────────────────────────────────

def write_all_outputs(
    output_dir: Path,
    articles_df: pd.DataFrame,
    repo_counts_df: pd.DataFrame,
    yearly_df: pd.DataFrame,
    confirmed_links: list[RepoMatch],
    diag_links: list[RepoMatch],
    summary: dict,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)

    # articles.csv
    p = output_dir / "articles.csv"
    articles_df.to_csv(p, index=False)
    logger.info("Wrote %d rows → %s", len(articles_df), p)

    # article_repository_links.csv
    if confirmed_links:
        p = output_dir / "article_repository_links.csv"
        pd.DataFrame([vars(m) for m in confirmed_links]).to_csv(p, index=False)
        logger.info("Wrote %d rows → %s", len(confirmed_links), p)

    # extraction_diagnostics.csv
    if diag_links:
        p = output_dir / "extraction_diagnostics.csv"
        pd.DataFrame([vars(m) for m in diag_links]).to_csv(p, index=False)
        logger.info("Wrote %d rows → %s", len(diag_links), p)

    # repository_counts.csv
    if not repo_counts_df.empty:
        p = output_dir / "repository_counts.csv"
        repo_counts_df.to_csv(p, index=False)
        logger.info("Wrote %d rows → %s", len(repo_counts_df), p)

    # yearly_repository_counts.csv
    if not yearly_df.empty:
        p = output_dir / "yearly_repository_counts.csv"
        yearly_df.to_csv(p, index=False)
        logger.info("Wrote %d rows → %s", len(yearly_df), p)

    # run_summary.json
    p = output_dir / "run_summary.json"
    p.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    logger.info("Wrote → %s", p)

    # report.md
    md = build_markdown_report(summary, repo_counts_df)
    p = output_dir / "report.md"
    p.write_text(md, encoding="utf-8")
    logger.info("Wrote → %s", p)
