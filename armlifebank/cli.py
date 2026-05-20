"""
Command-line entry point for the ArmLifeBank pipeline.

Usage:
  python -m armlifebank.cli [options]

Examples:
  python -m armlifebank.cli --sample-size 20 --mode strict
  python -m armlifebank.cli --start-year 2020 --end-year 2025 --output-dir results/
  python -m armlifebank.cli --resume --log-level DEBUG
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="armlifebank",
        description="Audit PubMed for country-affiliated papers and data-sharing references.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("--country", default=None, metavar="CODE",
                   help="Country profile to use (e.g. armenia, latvia). "
                        "Must match a file in country_profiles/.")
    p.add_argument("--start-year", type=int, default=None,
                   help="First publication year to query.")
    p.add_argument("--end-year", type=int, default=None,
                   help="Last publication year to query (inclusive).")
    p.add_argument("--mode", choices=["strict", "broad"], default=None,
                   help="Affiliation classification strictness.")
    p.add_argument("--sample-size", type=int, default=None, metavar="N",
                   help="Process only the first N validated articles (for testing).")
    p.add_argument("--resume", action="store_true", default=False,
                   help="Skip articles already present in output CSV.")
    p.add_argument("--force-refresh-cache", action="store_true", default=False,
                   help="Ignore cached API responses and re-fetch everything.")
    p.add_argument("--output-dir", default=None, metavar="DIR",
                   help="Directory for all output files.")
    p.add_argument("--config", default=None, metavar="FILE",
                   help="Path to a custom config.yaml.")
    p.add_argument("--log-level",
                   choices=["DEBUG", "INFO", "WARNING", "ERROR"],
                   default="INFO",
                   help="Logging verbosity.")
    return p


def setup_logging(level: str, log_dir: Path) -> None:
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "pipeline.log"
    fmt = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    handlers: list[logging.Handler] = [
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(log_file, encoding="utf-8"),
    ]
    logging.basicConfig(level=getattr(logging, level), format=fmt, handlers=handlers)


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    # ── Stage 1: Config ──────────────────────────────────────────────────
    from armlifebank.config import Config
    cfg = Config(
        config_file=Path(args.config) if args.config else None,
        country=args.country,
    )
    cfg.apply_cli_overrides(
        start_year=args.start_year,
        end_year=args.end_year,
        mode=args.mode,
        sample_size=args.sample_size,
        resume=args.resume,
        force_refresh_cache=args.force_refresh_cache,
        output_dir=args.output_dir,
        log_level=args.log_level,
    )
    cfg.ensure_dirs()
    setup_logging(args.log_level, cfg.log_dir)

    logger = logging.getLogger(__name__)
    logger.info("Starting ArmLifeBank pipeline. %r", cfg)

    if not cfg.ncbi_api_key:
        logger.warning(
            "No NCBI API key found. Rate limited to 3 req/s. "
            "Add key to NCBI_API.txt or set NCBI_API_KEY env var."
        )

    # ── Stage 2: PubMed search & XML fetch ──────────────────────────────
    from armlifebank.cache import Cache
    from armlifebank.pubmed import fetch_all_years, init_entrez, search_year

    import pandas as pd

    cache = Cache(cfg.cache_dir, force_refresh=cfg.force_refresh_cache)

    # Collect per-year PMID counts before sample truncation (for run_summary)
    init_entrez(cfg)
    year_pmid_counts: dict[int, int] = {}
    for yr in range(cfg.start_year, cfg.end_year + 1):
        ids = search_year(yr, cfg, cache)
        year_pmid_counts[yr] = len(ids)

    articles = fetch_all_years(cfg, cache)
    logger.info("Stage 2 complete – fetched %d article records.", len(articles))

    # ── Stage 3: Affiliation classification ─────────────────────────────
    from armlifebank.affiliation import CountryClassifier

    classifier = CountryClassifier(cfg.country_profile)
    classifications, output_rows = classifier.classify_articles(articles, mode=cfg.mode)

    n_validated = sum(1 for c in classifications if c.label == classifier.MATCH)
    n_uncertain = sum(1 for c in classifications if c.label == classifier.UNCERTAIN)
    n_excluded  = sum(1 for c in classifications if c.label == classifier.NO_MATCH)

    logger.info(
        "Stage 3 complete – %s: %d | uncertain: %d | excluded: %d",
        classifier.MATCH, n_validated, n_uncertain, n_excluded,
    )
    for name, rows in output_rows.items():
        if rows:
            path = cfg.output_dir / f"affiliations_{name}.csv"
            pd.DataFrame(rows).to_csv(path, index=False)
            logger.info("Wrote %d rows → %s", len(rows), path)

    # ── Stage 4: OA full-text retrieval ─────────────────────────────────
    from armlifebank.fulltext import resolve_fulltext_batch

    cl_by_pmid = {c.pmid: c for c in classifications}
    validated_articles = [
        a for a in articles
        if cl_by_pmid.get(a.get("pmid", "")) is not None
        and cl_by_pmid[a["pmid"]].label == classifier.MATCH
    ]
    logger.info("Stage 4: resolving full text for %d validated articles.", len(validated_articles))

    ft_results = resolve_fulltext_batch(validated_articles, cfg, cache)

    n_ft_pmcid = sum(1 for r in ft_results if r.has_pmcid)
    n_ft_oa    = sum(1 for r in ft_results if r.is_pmc_oa)
    n_ft_ok    = sum(1 for r in ft_results if r.full_text_retrieval_status == "ok")

    logger.info(
        "Stage 4 complete – PMCID: %d | PMC OA: %d | full text retrieved: %d",
        n_ft_pmcid, n_ft_oa, n_ft_ok,
    )

    # Attach ft result onto each validated article dict for downstream use
    ft_by_pmid = {r.pmid: r for r in ft_results}
    for a in validated_articles:
        r = ft_by_pmid.get(a["pmid"])
        if r:
            a["_ft"] = r

    # ── Stage 5: Repository / accession extraction ───────────────────────
    from armlifebank.repositories import extract_all

    confirmed_links, diag_links = extract_all(validated_articles, cfg.repository_patterns)

    n_articles_with_data = len({m.pmid for m in confirmed_links})
    repo_counts: dict[str, int] = {}
    for m in confirmed_links:
        repo_counts[m.repository] = repo_counts.get(m.repository, 0) + 1

    logger.info(
        "Stage 5 complete – %d links in %d articles | repositories: %s",
        len(confirmed_links), n_articles_with_data, repo_counts,
    )

    # ── Stage 6: Aggregation & reporting ────────────────────────────────
    from armlifebank.reporting import (
        build_articles_df,
        build_repository_counts_df,
        build_yearly_repo_df,
        build_run_summary,
        write_all_outputs,
    )

    articles_df = build_articles_df(
        validated_articles, classifications, ft_results, confirmed_links
    )
    repo_counts_df  = build_repository_counts_df(confirmed_links)
    yearly_df       = build_yearly_repo_df(confirmed_links, validated_articles)
    summary         = build_run_summary(
        cfg, articles, classifications, ft_results,
        confirmed_links, diag_links, year_pmid_counts,
    )

    write_all_outputs(
        cfg.output_dir,
        articles_df, repo_counts_df, yearly_df,
        confirmed_links, diag_links, summary,
    )

    logger.info("Stage 6 complete – all outputs written to %s", cfg.output_dir)

    # ── Final summary ────────────────────────────────────────────────────
    pct_oa   = 100 * n_ft_oa   / max(n_validated, 1)
    pct_data = 100 * n_articles_with_data / max(n_validated, 1)

    country_name = cfg.country_profile.get("name", cfg.country_code.capitalize())
    print(
        f"\n{'='*60}\n"
        f"  ArmLifeBank pipeline complete\n"
        f"{'='*60}\n"
        f"  Country:        {country_name}\n"
        f"  Years:          {cfg.start_year}–{cfg.end_year}  |  Mode: {cfg.mode}\n"
        f"  Candidates:     {sum(year_pmid_counts.values())}\n"
        f"  {country_name}-country:{n_validated:>5}  |  excluded: {n_excluded}  |  uncertain: {n_uncertain}\n"
        f"  PMC OA:         {n_ft_oa:>5} / {n_validated} ({pct_oa:.0f}%)\n"
        f"  Full text:      {n_ft_ok:>5} / {n_validated}\n"
        f"  Data references:{n_articles_with_data:>5} / {n_validated} ({pct_data:.0f}%)\n"
        f"  Repo links:     {len(confirmed_links)}\n"
        f"{'='*60}\n"
        f"  Outputs → {cfg.output_dir}\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
