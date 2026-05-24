"""
Unit tests for analysis/normalize.py

Covers every normalizer function with hand-computed expected values for:
  - normalize_doi:        4 prefix styles + bare + case + invalid
  - normalize_url:        www, trailing slash, query params, fragments,
                          utm removal, port stripping, LHA permalinks
  - normalize_accession:  GenBank with/without version, GEO, PDB, SRA,
                          BioProject, BioSample, PRIDE, EGA, dbGaP,
                          ArrayExpress, ClinicalTrials, general-purpose repos,
                          GitHub/GitLab, default fallback
  - extract_doi_from_url: doi.org, dx.doi.org, zenodo /doi/ path,
                          zenodo /record/ (no DOI), figshare, osf, None
"""

import sys
from pathlib import Path

# Allow running from repo root or tests/ directory
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from analysis.normalize import (
    extract_doi_from_url,
    normalize_accession,
    normalize_doi,
    normalize_url,
)


# ═════════════════════════════════════════════════════════════════════════════
# normalize_doi
# ═════════════════════════════════════════════════════════════════════════════

class TestNormalizeDoi:

    # ── Four prefix styles ────────────────────────────────────────────────────

    def test_https_doi_org(self):
        assert normalize_doi("https://doi.org/10.1234/example") == "10.1234/example"

    def test_http_doi_org(self):
        assert normalize_doi("http://doi.org/10.1234/example") == "10.1234/example"

    def test_https_dx_doi_org(self):
        assert normalize_doi("https://dx.doi.org/10.1234/example") == "10.1234/example"

    def test_http_dx_doi_org(self):
        assert normalize_doi("http://dx.doi.org/10.1234/example") == "10.1234/example"

    def test_doi_colon_prefix(self):
        assert normalize_doi("doi:10.1234/example") == "10.1234/example"

    def test_bare_doi(self):
        assert normalize_doi("10.1234/example") == "10.1234/example"

    # ── Case handling ─────────────────────────────────────────────────────────

    def test_uppercase_doi_is_lowercased(self):
        assert normalize_doi("10.1234/EXAMPLE-SUFFIX") == "10.1234/example-suffix"

    def test_mixed_case_prefix_doi_colon(self):
        # "DOI:" should still be stripped (prefix comparison is case-insensitive)
        assert normalize_doi("DOI:10.1234/foo") == "10.1234/foo"

    def test_leading_trailing_whitespace_stripped(self):
        assert normalize_doi("  10.1234/foo  ") == "10.1234/foo"

    def test_prefix_with_whitespace(self):
        assert normalize_doi("  https://doi.org/10.1234/foo  ") == "10.1234/foo"

    # ── Real-world DOI examples ───────────────────────────────────────────────

    def test_zenodo_doi(self):
        assert normalize_doi("https://doi.org/10.5281/zenodo.123456") == "10.5281/zenodo.123456"

    def test_journal_doi_with_special_chars(self):
        assert normalize_doi("10.1093/nar/gkab1135") == "10.1093/nar/gkab1135"

    def test_doi_with_parentheses(self):
        assert normalize_doi("10.1016/j.cell.2020.01.001(2020)") == "10.1016/j.cell.2020.01.001(2020)"

    # ── Invalid input → None ──────────────────────────────────────────────────

    def test_none_returns_none(self):
        assert normalize_doi(None) is None

    def test_empty_string_returns_none(self):
        assert normalize_doi("") is None

    def test_whitespace_only_returns_none(self):
        assert normalize_doi("   ") is None

    def test_not_a_doi_returns_none(self):
        assert normalize_doi("not-a-doi") is None

    def test_doi_fewer_than_4_digits_returns_none(self):
        # "10.123/" has only 3 digits after "10." — invalid
        assert normalize_doi("10.123/foo") is None

    def test_doi_no_suffix_returns_none(self):
        # Slash present but nothing after it
        assert normalize_doi("10.1234/") is None

    def test_plain_url_not_doi_returns_none(self):
        assert normalize_doi("https://example.com/paper") is None


# ═════════════════════════════════════════════════════════════════════════════
# normalize_url
# ═════════════════════════════════════════════════════════════════════════════

class TestNormalizeUrl:

    # ── www. stripping ────────────────────────────────────────────────────────

    def test_strips_www(self):
        assert normalize_url("https://www.example.com/path") == "https://example.com/path"

    def test_no_www_unchanged(self):
        assert normalize_url("https://example.com/path") == "https://example.com/path"

    # ── Trailing slash ────────────────────────────────────────────────────────

    def test_trailing_slash_stripped(self):
        assert normalize_url("https://example.com/path/") == "https://example.com/path"

    def test_multiple_trailing_slashes_stripped(self):
        assert normalize_url("https://example.com/path///") == "https://example.com/path"

    def test_root_path_preserved(self):
        # Bare root "/" should not become empty string
        result = normalize_url("https://example.com/")
        assert result in ("https://example.com", "https://example.com/")

    # ── Default port stripping ────────────────────────────────────────────────

    def test_http_port_80_stripped(self):
        assert normalize_url("http://example.com:80/path") == "http://example.com/path"

    def test_https_port_443_stripped(self):
        assert normalize_url("https://example.com:443/path") == "https://example.com/path"

    def test_non_default_port_retained(self):
        assert normalize_url("https://example.com:8080/path") == "https://example.com:8080/path"

    # ── UTM parameter removal ─────────────────────────────────────────────────

    def test_utm_source_removed(self):
        result = normalize_url("https://example.com/p?utm_source=email&foo=bar")
        assert "utm_source" not in result
        assert "foo=bar" in result

    def test_utm_medium_removed(self):
        result = normalize_url("https://example.com/p?utm_medium=social")
        assert "utm_medium" not in result

    def test_only_utm_params_gives_no_query(self):
        result = normalize_url("https://example.com/p?utm_source=x&utm_campaign=y")
        assert "?" not in result

    # ── Query parameter sorting ───────────────────────────────────────────────

    def test_query_params_sorted(self):
        a = normalize_url("https://example.com/p?b=2&a=1")
        b = normalize_url("https://example.com/p?a=1&b=2")
        assert a == b
        assert "a=1" in a
        assert "b=2" in a

    # ── Fragment stripping ────────────────────────────────────────────────────

    def test_fragment_stripped(self):
        assert normalize_url("https://example.com/page#section") == "https://example.com/page"

    def test_fragment_and_query_fragment_stripped(self):
        result = normalize_url("https://example.com/page?a=1#anchor")
        assert "#" not in result
        assert "a=1" in result

    # ── Case rules ────────────────────────────────────────────────────────────

    def test_scheme_lowercased(self):
        assert normalize_url("HTTPS://example.com/path").startswith("https://")

    def test_host_lowercased(self):
        assert "EXAMPLE" not in normalize_url("https://EXAMPLE.COM/path")

    def test_path_case_preserved(self):
        # Path must NOT be lowercased (paths are case-sensitive on most servers)
        result = normalize_url("https://example.com/Path/To/File")
        assert "/Path/To/File" in result

    # ── LHA permalink ─────────────────────────────────────────────────────────

    def test_lha_permalink_www_stripped(self):
        result = normalize_url("https://www.health-atlas.de/lha/abc123")
        assert result == "https://health-atlas.de/lha/abc123"

    def test_lha_permalink_no_www(self):
        result = normalize_url("https://health-atlas.de/lha/abc123")
        assert result == "https://health-atlas.de/lha/abc123"

    def test_lha_permalink_trailing_slash(self):
        result = normalize_url("https://www.health-atlas.de/lha/abc123/")
        assert result == "https://health-atlas.de/lha/abc123"

    # ── Invalid input → None ──────────────────────────────────────────────────

    def test_none_returns_none(self):
        assert normalize_url(None) is None

    def test_empty_string_returns_none(self):
        assert normalize_url("") is None

    def test_no_scheme_returns_none(self):
        assert normalize_url("example.com/path") is None


# ═════════════════════════════════════════════════════════════════════════════
# normalize_accession
# ═════════════════════════════════════════════════════════════════════════════

class TestNormalizeAccession:

    # ── GenBank ───────────────────────────────────────────────────────────────

    def test_genbank_strips_version(self):
        assert normalize_accession("GenBank", "MK123456.1") == "MK123456"

    def test_genbank_strips_two_digit_version(self):
        assert normalize_accession("GenBank", "MK123456.12") == "MK123456"

    def test_genbank_no_version_unchanged(self):
        assert normalize_accession("GenBank", "MK123456") == "MK123456"

    def test_genbank_lowercased_input_uppercased(self):
        assert normalize_accession("GenBank", "mk123456.1") == "MK123456"

    def test_genbank_whole_genome_shotgun(self):
        assert normalize_accession("GenBank", "JABC01000001.1") == "JABC01000001"

    # ── RefSeq ────────────────────────────────────────────────────────────────

    def test_refseq_strips_version(self):
        assert normalize_accession("RefSeq", "NM_000001.3") == "NM_000001"

    def test_refseq_no_version(self):
        assert normalize_accession("RefSeq", "NM_000001") == "NM_000001"

    # ── ENA ───────────────────────────────────────────────────────────────────

    def test_ena_strips_version(self):
        assert normalize_accession("ENA", "ERS123456.1") == "ERS123456"

    def test_ena_uppercase(self):
        assert normalize_accession("ENA", "ers123456") == "ERS123456"

    # ── Gene Expression Omnibus ───────────────────────────────────────────────

    def test_geo_uppercase(self):
        assert normalize_accession("Gene Expression Omnibus", "gse148736") == "GSE148736"

    def test_geo_already_upper(self):
        assert normalize_accession("Gene Expression Omnibus", "GSE148736") == "GSE148736"

    def test_geo_gsm(self):
        assert normalize_accession("Gene Expression Omnibus", "gsm123456") == "GSM123456"

    # ── PDB ───────────────────────────────────────────────────────────────────

    def test_pdb_lowercase_uppercased(self):
        assert normalize_accession("PDB", "2cuu") == "2CUU"

    def test_pdb_already_upper(self):
        assert normalize_accession("PDB", "2CUU") == "2CUU"

    def test_pdb_too_short_returns_none(self):
        assert normalize_accession("PDB", "2cu") is None

    def test_pdb_too_long_returns_none(self):
        assert normalize_accession("PDB", "2CUUU") is None

    def test_pdb_exactly_4_chars(self):
        assert normalize_accession("PDB", "5lwo") == "5LWO"

    # ── SRA ───────────────────────────────────────────────────────────────────

    def test_sra_uppercase(self):
        assert normalize_accession("SRA", "srr123456") == "SRR123456"

    def test_sra_already_upper(self):
        assert normalize_accession("SRA", "SRR123456") == "SRR123456"

    # ── BioProject ────────────────────────────────────────────────────────────

    def test_bioproject_uppercase(self):
        assert normalize_accession("BioProject", "prjna123456") == "PRJNA123456"

    def test_bioproject_prjeb(self):
        assert normalize_accession("BioProject", "prjeb69274") == "PRJEB69274"

    # ── BioSample ─────────────────────────────────────────────────────────────

    def test_biosample_uppercase(self):
        assert normalize_accession("BioSample", "samn12345678") == "SAMN12345678"

    # ── PRIDE ─────────────────────────────────────────────────────────────────

    def test_pride_uppercase(self):
        assert normalize_accession("PRIDE", "pxd000001") == "PXD000001"

    # ── EGA ───────────────────────────────────────────────────────────────────

    def test_ega_uppercase(self):
        assert normalize_accession("EGA", "egad00001000001") == "EGAD00001000001"

    # ── dbGaP ─────────────────────────────────────────────────────────────────

    def test_dbgap_uppercase(self):
        assert normalize_accession("dbGaP", "phs000001") == "PHS000001"

    # ── ArrayExpress ──────────────────────────────────────────────────────────

    def test_arrayexpress_uppercase(self):
        assert normalize_accession("ArrayExpress", "e-mtab-1234") == "E-MTAB-1234"

    # ── ClinicalTrials.gov ────────────────────────────────────────────────────

    def test_clinicaltrials_valid(self):
        assert normalize_accession("ClinicalTrials.gov", "NCT12345678") == "NCT12345678"

    def test_clinicaltrials_lowercase_input(self):
        assert normalize_accession("ClinicalTrials.gov", "nct12345678") == "NCT12345678"

    def test_clinicaltrials_too_few_digits_returns_none(self):
        assert normalize_accession("ClinicalTrials.gov", "NCT1234567") is None  # 7 digits

    def test_clinicaltrials_too_many_digits_returns_none(self):
        assert normalize_accession("ClinicalTrials.gov", "NCT123456789") is None  # 9 digits

    def test_clinicaltrials_wrong_prefix_returns_none(self):
        assert normalize_accession("ClinicalTrials.gov", "ISRCTN12345678") is None

    # ── General-purpose repos: DOI path ──────────────────────────────────────

    def test_zenodo_doi_identifier(self):
        result = normalize_accession("Zenodo", "10.5281/zenodo.123456")
        assert result == "10.5281/zenodo.123456"

    def test_zenodo_doi_with_prefix(self):
        result = normalize_accession("Zenodo", "https://doi.org/10.5281/zenodo.123456")
        assert result == "10.5281/zenodo.123456"

    def test_osf_opaque_id(self):
        result = normalize_accession("OSF", "K6W3B")
        assert result == "K6W3B"

    def test_figshare_doi(self):
        result = normalize_accession("Figshare", "10.6084/m9.figshare.12345678")
        assert result == "10.6084/m9.figshare.12345678"

    def test_dryad_doi(self):
        result = normalize_accession("Dryad", "10.5061/dryad.abc123")
        assert result == "10.5061/dryad.abc123"

    def test_mendeley_data_opaque(self):
        result = normalize_accession("Mendeley Data", "abc123xyz")
        assert result == "abc123xyz"

    # ── GitHub / GitLab ───────────────────────────────────────────────────────

    def test_github_lowercased(self):
        assert normalize_accession("GitHub", "Owner/Repo") == "owner/repo"

    def test_github_strips_git_suffix(self):
        assert normalize_accession("GitHub", "Owner/Repo.git") == "owner/repo"

    def test_github_strips_url_prefix(self):
        assert normalize_accession("GitHub", "https://github.com/Owner/Repo") == "owner/repo"

    def test_github_strips_url_prefix_with_git(self):
        assert normalize_accession("GitHub", "https://github.com/Owner/Repo.git") == "owner/repo"

    def test_gitlab_lowercased(self):
        assert normalize_accession("GitLab", "Group/Project") == "group/project"

    def test_gitlab_strips_url_prefix(self):
        assert normalize_accession("GitLab", "https://gitlab.com/Group/Project") == "group/project"

    # ── Default fallback ──────────────────────────────────────────────────────

    def test_unknown_repo_strips_whitespace(self):
        assert normalize_accession("SomeOtherRepo", "  ABC123  ") == "ABC123"

    def test_unknown_repo_no_transformation(self):
        assert normalize_accession("SomeOtherRepo", "MixedCase") == "MixedCase"

    # ── Invalid / empty input → None ─────────────────────────────────────────

    def test_none_returns_none(self):
        assert normalize_accession("GenBank", None) is None

    def test_empty_string_returns_none(self):
        assert normalize_accession("GenBank", "") is None

    def test_whitespace_only_returns_none(self):
        assert normalize_accession("GenBank", "   ") is None

    def test_pdb_empty_after_processing_returns_none(self):
        assert normalize_accession("PDB", "   ") is None


# ═════════════════════════════════════════════════════════════════════════════
# extract_doi_from_url
# ═════════════════════════════════════════════════════════════════════════════

class TestExtractDoiFromUrl:

    # ── doi.org ───────────────────────────────────────────────────────────────

    def test_https_doi_org(self):
        assert extract_doi_from_url("https://doi.org/10.1234/foo") == "10.1234/foo"

    def test_http_doi_org(self):
        assert extract_doi_from_url("http://doi.org/10.1234/foo") == "10.1234/foo"

    def test_www_doi_org(self):
        assert extract_doi_from_url("https://www.doi.org/10.1234/foo") == "10.1234/foo"

    # ── dx.doi.org ────────────────────────────────────────────────────────────

    def test_https_dx_doi_org(self):
        assert extract_doi_from_url("https://dx.doi.org/10.5281/zenodo.123456") == "10.5281/zenodo.123456"

    def test_http_dx_doi_org(self):
        assert extract_doi_from_url("http://dx.doi.org/10.1093/nar/gkab001") == "10.1093/nar/gkab001"

    # ── zenodo.org/doi/ path ──────────────────────────────────────────────────

    def test_zenodo_doi_path(self):
        assert extract_doi_from_url("https://zenodo.org/doi/10.5281/zenodo.123456") == "10.5281/zenodo.123456"

    def test_zenodo_doi_path_www(self):
        assert extract_doi_from_url("https://www.zenodo.org/doi/10.5281/zenodo.123456") == "10.5281/zenodo.123456"

    # ── zenodo.org/record/ — no DOI in URL ───────────────────────────────────

    def test_zenodo_record_returns_none(self):
        assert extract_doi_from_url("https://zenodo.org/record/123456") is None

    def test_zenodo_records_returns_none(self):
        assert extract_doi_from_url("https://zenodo.org/records/123456") is None

    # ── figshare — no extractable DOI ────────────────────────────────────────

    def test_figshare_returns_none(self):
        assert extract_doi_from_url("https://figshare.com/articles/dataset/title/12345678") is None

    # ── osf.io — opaque short IDs, no DOI ────────────────────────────────────

    def test_osf_returns_none(self):
        assert extract_doi_from_url("https://osf.io/K6W3B") is None

    # ── Case: doi.org with uppercase DOI — should be lowercased ──────────────

    def test_doi_org_uppercase_doi_lowercased(self):
        assert extract_doi_from_url("https://doi.org/10.1234/FOO") == "10.1234/foo"

    # ── Invalid input → None ─────────────────────────────────────────────────

    def test_none_returns_none(self):
        assert extract_doi_from_url(None) is None

    def test_empty_returns_none(self):
        assert extract_doi_from_url("") is None

    def test_non_doi_url_returns_none(self):
        assert extract_doi_from_url("https://pubmed.ncbi.nlm.nih.gov/12345678/") is None

    def test_plain_string_returns_none(self):
        assert extract_doi_from_url("not-a-url") is None
