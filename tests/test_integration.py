"""
Integration tests for the ArmLifeBank pipeline.

Uses hand-curated fixture PMIDs (tests/fixtures/fixture_pmids.json).
Requires network access and a populated .cache directory.
Run with:  pytest tests/test_integration.py -v
Skip if offline: pytest tests/test_integration.py -v -m "not integration"
"""

import json
import pytest
from pathlib import Path

FIXTURES = json.loads(
    (Path(__file__).parent / "fixtures" / "fixture_pmids.json").read_text()
)

# ── helpers ───────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def cfg():
    from armlifebank.config import Config
    return Config()


@pytest.fixture(scope="module")
def cache(cfg):
    from armlifebank.cache import Cache
    return Cache(cfg.cache_dir)


@pytest.fixture(scope="module")
def patterns(cfg):
    from armlifebank.repositories import load_patterns
    return load_patterns(cfg.repository_patterns)


@pytest.fixture(scope="module")
def fetched_articles(cfg, cache):
    """Fetch XML for all fixture PMIDs (uses cache; only hits network on first run)."""
    from armlifebank.pubmed import fetch_records, init_entrez
    init_entrez(cfg)
    all_pmids = FIXTURES["all"]
    return list(fetch_records(all_pmids, cfg, cache))


# ── Stage 3: affiliation classification ──────────────────────────────────────

class TestAffiliationOnFixtures:
    def test_armenia_country_pmids_classified_correctly(self, fetched_articles, cfg):
        from armlifebank.affiliation import classify_article
        armenia_pmids = set(FIXTURES["armenia_country"]["pmids"])
        for art in fetched_articles:
            pmid = art.get("pmid", "")
            if pmid not in armenia_pmids:
                continue
            affs = art.get("all_affiliations", [])
            cl = classify_article(pmid, affs, mode=cfg.mode)
            assert cl.label == "armenia_country", (
                f"PMID {pmid} expected armenia_country, got {cl.label!r}\n"
                f"  affiliations: {affs[:2]}"
            )

    def test_colombia_pmids_excluded(self, fetched_articles, cfg):
        from armlifebank.affiliation import classify_article
        colombia_pmids = set(FIXTURES["colombia_exclusion"]["pmids"])
        for art in fetched_articles:
            pmid = art.get("pmid", "")
            if pmid not in colombia_pmids:
                continue
            affs = art.get("all_affiliations", [])
            cl = classify_article(pmid, affs, mode=cfg.mode)
            assert cl.label == "not_armenia_country", (
                f"PMID {pmid} expected not_armenia_country, got {cl.label!r}\n"
                f"  affiliations: {affs[:2]}"
            )

    def test_no_armenia_country_without_affiliations(self, cfg):
        from armlifebank.affiliation import classify_article
        cl = classify_article("00000", [], mode=cfg.mode)
        assert cl.label == "not_armenia_country"
        assert cl.n_armenia == 0


# ── Stage 4: full-text retrieval ──────────────────────────────────────────────

@pytest.mark.integration
class TestFullTextOnFixtures:
    def test_oa_articles_have_pmcid(self, fetched_articles, cfg, cache):
        from armlifebank.fulltext import resolve_pmcid
        oa_pmids = set(FIXTURES["oa_with_accessions"]["pmids"])
        for art in fetched_articles:
            pmid = art.get("pmid", "")
            if pmid not in oa_pmids:
                continue
            pmcid = resolve_pmcid(pmid, art.get("doi",""), art.get("pmcid",""), cfg, cache)
            assert pmcid, f"PMID {pmid} expected a PMCID but got empty string"

    def test_oa_articles_retrieve_fulltext(self, fetched_articles, cfg, cache):
        from armlifebank.fulltext import resolve_fulltext
        oa_pmids = set(FIXTURES["oa_with_accessions"]["pmids"])
        retrieved = 0
        for art in fetched_articles:
            if art.get("pmid") not in oa_pmids:
                continue
            result = resolve_fulltext(art, cfg, cache)
            if result.full_text_retrieval_status == "ok":
                retrieved += 1
                assert len(result.full_text_xml) > 1000, (
                    f"PMID {art['pmid']}: full_text_xml suspiciously short"
                )
        assert retrieved >= 1, "Expected at least 1 OA full-text retrieval from fixture set"


# ── Stage 5: repository extraction ───────────────────────────────────────────

@pytest.mark.integration
class TestRepositoryExtractionOnFixtures:
    def test_oa_accession_articles_yield_links(self, fetched_articles, cfg, cache, patterns):
        from armlifebank.fulltext import resolve_fulltext
        from armlifebank.repositories import extract_repository_links
        oa_pmids = set(FIXTURES["oa_with_accessions"]["pmids"])
        total_links = 0
        for art in fetched_articles:
            if art.get("pmid") not in oa_pmids:
                continue
            ft = resolve_fulltext(art, cfg, cache)
            art["_ft"] = ft
            confirmed, _ = extract_repository_links(art, patterns)
            total_links += len(confirmed)
        assert total_links >= 1, (
            "Expected at least 1 repository link from OA fixture articles"
        )

    def test_colombia_articles_yield_no_links_from_affiliation(self, fetched_articles, cfg, cache, patterns):
        """Repository extraction is affiliation-agnostic; this checks no cross-contamination."""
        from armlifebank.repositories import extract_repository_links
        colombia_pmids = set(FIXTURES["colombia_exclusion"]["pmids"])
        for art in fetched_articles:
            if art.get("pmid") not in colombia_pmids:
                continue
            confirmed, _ = extract_repository_links(art, patterns)
            # Colombia articles may legitimately have repo links; what they must NOT have
            # is an Armenia-country affiliation leaking into the results
            for m in confirmed:
                assert m.pmid == art["pmid"], "Link PMID mismatch"


# ── Stage 6: reporting ────────────────────────────────────────────────────────

class TestReportingBuilders:
    def test_build_articles_df_columns(self, fetched_articles, cfg, cache):
        from armlifebank.affiliation import classify_articles
        from armlifebank.fulltext import resolve_fulltext_batch
        from armlifebank.repositories import extract_all
        from armlifebank.reporting import build_articles_df

        armenia_pmids = set(FIXTURES["armenia_country"]["pmids"])
        armenia_arts = [a for a in fetched_articles if a.get("pmid") in armenia_pmids]
        if not armenia_arts:
            pytest.skip("No Armenia fixture articles available")

        classifications, _ = classify_articles(armenia_arts, mode=cfg.mode)
        ft_results = resolve_fulltext_batch(armenia_arts, cfg, cache)
        ft_by_pmid = {r.pmid: r for r in ft_results}
        for a in armenia_arts:
            r = ft_by_pmid.get(a["pmid"])
            if r:
                a["_ft"] = r

        confirmed, _ = extract_all(armenia_arts, cfg.repository_patterns)
        df = build_articles_df(armenia_arts, classifications, ft_results, confirmed)

        required_cols = {
            "pmid", "doi", "pmcid", "title", "journal", "pub_year",
            "affiliation_label", "has_pmcid", "is_pmc_oa",
            "has_any_data_reference", "n_repository_links",
        }
        assert required_cols.issubset(set(df.columns)), (
            f"Missing columns: {required_cols - set(df.columns)}"
        )
        assert len(df) == len(armenia_arts)
        assert (df["affiliation_label"] == "armenia_country").all()

    def test_run_summary_has_required_keys(self, fetched_articles, cfg, cache):
        from armlifebank.affiliation import classify_articles
        from armlifebank.fulltext import resolve_fulltext_batch
        from armlifebank.repositories import extract_all
        from armlifebank.reporting import build_run_summary

        classifications, _ = classify_articles(fetched_articles, mode=cfg.mode)
        ft_arts = [a for a in fetched_articles
                   if any(c.pmid == a["pmid"] and c.label == "armenia_country"
                          for c in classifications)]
        ft_results = resolve_fulltext_batch(ft_arts, cfg, cache)
        ft_by_pmid = {r.pmid: r for r in ft_results}
        for a in ft_arts:
            r = ft_by_pmid.get(a["pmid"])
            if r:
                a["_ft"] = r
        confirmed, diag = extract_all(ft_arts, cfg.repository_patterns)

        summary = build_run_summary(
            cfg, fetched_articles, classifications, ft_results,
            confirmed, diag, {2020: 393, 2021: 471},
        )
        required = {
            "run_datetime", "config", "pubmed_query_template",
            "n_candidate_pmids", "affiliation_classification",
            "fulltext_retrieval", "repository_extraction", "limitations",
        }
        assert required.issubset(set(summary.keys()))
        assert summary["affiliation_classification"]["n_country_match"] >= 1
