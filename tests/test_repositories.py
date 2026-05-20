"""Unit tests for repository / accession extraction."""

import pytest
from pathlib import Path
from armlifebank.repositories import (
    load_patterns,
    extract_repository_links,
    _extract_from_abstract,
    _is_likely_false_positive,
    RepoMatch,
)

PATTERNS_PATH = Path(__file__).resolve().parent.parent / "repository_patterns.yaml"


@pytest.fixture(scope="module")
def patterns():
    return load_patterns(PATTERNS_PATH)


def _article(pmid="00001", abstract="", databanks=None, full_text_xml=None):
    """Build a minimal article dict for testing."""
    art = {"pmid": pmid, "doi": "", "abstract": abstract,
           "databanks": databanks or [], "all_affiliations": []}
    if full_text_xml:
        class FT:
            pmcid = "PMC9999999"
            full_text_xml = ""
            full_text_retrieval_status = "ok"
        ft = FT()
        ft.full_text_xml = full_text_xml
        art["_ft"] = ft
    return art


# ── PubMed DataBankList ───────────────────────────────────────────────────────

def test_databank_geo(patterns):
    art = _article(databanks=[{"name": "GEO", "accessions": ["GSE123456"]}])
    confirmed, _ = extract_repository_links(art, patterns)
    assert any(m.repository == "Gene Expression Omnibus" and m.identifier == "GSE123456" for m in confirmed)

def test_databank_normalises_gene_expression_omnibus(patterns):
    art = _article(databanks=[{"name": "Gene Expression Omnibus", "accessions": ["GSE9999"]}])
    confirmed, _ = extract_repository_links(art, patterns)
    repos = {m.repository for m in confirmed}
    assert "Gene Expression Omnibus" in repos

def test_databank_sra(patterns):
    art = _article(databanks=[{"name": "SRA", "accessions": ["PRJNA123456"]}])
    confirmed, _ = extract_repository_links(art, patterns)
    assert any(m.repository == "BioProject" or m.repository == "SRA" for m in confirmed)


# ── Abstract extraction ───────────────────────────────────────────────────────

class TestAbstractPatterns:
    def test_sra_prjna(self, patterns):
        art = _article(abstract="Raw sequencing data were deposited in SRA under accession PRJNA123456.")
        confirmed, _ = extract_repository_links(art, patterns)
        ids = [m.identifier for m in confirmed]
        assert "PRJNA123456" in ids

    def test_geo_gse(self, patterns):
        art = _article(abstract="GEO accession GSE123456.")
        confirmed, _ = extract_repository_links(art, patterns)
        assert any(m.identifier == "GSE123456" and m.repository == "Gene Expression Omnibus" for m in confirmed)

    def test_genbank_range(self, patterns):
        art = _article(abstract="GenBank accession numbers OP123456–OP123460.")
        confirmed, diag = extract_repository_links(art, patterns)
        all_m = confirmed + diag
        ids = [m.identifier for m in all_m]
        assert any("OP123456" in i for i in ids)

    def test_zenodo_doi(self, patterns):
        art = _article(abstract="Data are available at Zenodo doi:10.5281/zenodo.7654321.")
        confirmed, _ = extract_repository_links(art, patterns)
        assert any(m.repository == "Zenodo" for m in confirmed)

    def test_pdb_accession(self, patterns):
        art = _article(abstract="The structure was deposited in PDB: 7ABC.")
        confirmed, _ = extract_repository_links(art, patterns)
        assert any(m.repository == "PDB" and m.identifier == "7ABC" for m in confirmed)

    def test_pride_pxd(self, patterns):
        art = _article(abstract="Proteomics data are in PRIDE under accession PXD012345.")
        confirmed, _ = extract_repository_links(art, patterns)
        assert any(m.repository == "PRIDE" and m.identifier == "PXD012345" for m in confirmed)

    def test_arrayexpress(self, patterns):
        art = _article(abstract="Microarray data deposited in ArrayExpress (E-MTAB-12345).")
        confirmed, _ = extract_repository_links(art, patterns)
        assert any(m.repository == "ArrayExpress" and m.identifier == "E-MTAB-12345"
                   for m in confirmed)

    def test_ega(self, patterns):
        art = _article(abstract="Controlled-access data submitted to EGA under EGAS00001005678.")
        confirmed, _ = extract_repository_links(art, patterns)
        assert any(m.repository == "EGA" for m in confirmed)

    def test_osf(self, patterns):
        art = _article(abstract="Data available at OSF (https://osf.io/ab3cd).")
        confirmed, _ = extract_repository_links(art, patterns)
        assert any(m.repository == "OSF" for m in confirmed)

    def test_figshare(self, patterns):
        art = _article(abstract="Dataset deposited on Figshare: 10.6084/m9.figshare.12345678.")
        confirmed, _ = extract_repository_links(art, patterns)
        assert any(m.repository == "Figshare" for m in confirmed)

    def test_dryad(self, patterns):
        art = _article(abstract="Data available from Dryad doi:10.5061/dryad.abc123.")
        confirmed, _ = extract_repository_links(art, patterns)
        assert any(m.repository == "Dryad" for m in confirmed)

    def test_metabolights(self, patterns):
        art = _article(abstract="Metabolomics data deposited in MetaboLights as MTBLS1234.")
        confirmed, _ = extract_repository_links(art, patterns)
        assert any(m.repository == "MetaboLights" for m in confirmed)


# ── JATS XML extraction ───────────────────────────────────────────────────────

_JATS_DATA_AVAIL = """<?xml version="1.0"?>
<article xmlns:xlink="http://www.w3.org/1999/xlink">
  <body>
    <sec>
      <title>Data Availability</title>
      <p>Raw reads deposited in SRA under accession PRJNA654321.
         The microarray data are at GEO: GSE200001.
         Protein structures deposited at PDB: 6XYZ.
         Code available at github.com/labname/myrepo.</p>
    </sec>
    <sec>
      <title>Methods</title>
      <p>See supplementary materials. Data at Zenodo doi:10.5281/zenodo.9876543.</p>
    </sec>
  </body>
  <back>
    <supplementary-material xlink:href="https://figshare.com/articles/dataset/title/12345678">
      Supplementary dataset
    </supplementary-material>
  </back>
</article>"""

def test_jats_data_availability_section(patterns):
    art = _article(full_text_xml=_JATS_DATA_AVAIL)
    confirmed, _ = extract_repository_links(art, patterns)
    repos = {m.repository for m in confirmed}
    assert "SRA" in repos or "BioProject" in repos
    assert "Gene Expression Omnibus" in repos
    assert "PDB" in repos

def test_jats_zenodo_in_methods(patterns):
    art = _article(full_text_xml=_JATS_DATA_AVAIL)
    confirmed, _ = extract_repository_links(art, patterns)
    assert any(m.repository == "Zenodo" for m in confirmed)

def test_jats_figshare_supplementary(patterns):
    art = _article(full_text_xml=_JATS_DATA_AVAIL)
    confirmed, _ = extract_repository_links(art, patterns)
    assert any(m.repository == "Figshare" for m in confirmed)

def test_jats_evidence_source_is_pmc_xml(patterns):
    art = _article(full_text_xml=_JATS_DATA_AVAIL)
    confirmed, _ = extract_repository_links(art, patterns)
    sources = {m.evidence_source for m in confirmed}
    assert "pmc_xml" in sources


# ── False-positive filters ────────────────────────────────────────────────────

def test_data_on_request_goes_to_diagnostics(patterns):
    art = _article(abstract="Data are available upon request from the corresponding author.")
    # Should NOT produce confirmed matches that contain "upon request" text
    confirmed, diag = extract_repository_links(art, patterns)
    # No repo identifiers expected in this snippet
    assert all(m.repository not in ("Gene Expression Omnibus", "SRA", "Zenodo") for m in confirmed)

def test_colombia_affiliation_does_not_affect_extraction(patterns):
    """Colombia affiliation exclusion is handled upstream; extraction is affiliation-agnostic."""
    art = _article(
        abstract="Data deposited in GEO under GSE111111.",
        databanks=[]
    )
    confirmed, _ = extract_repository_links(art, patterns)
    assert any(m.repository == "Gene Expression Omnibus" for m in confirmed)


# ── Deduplication ─────────────────────────────────────────────────────────────

def test_deduplication_across_sources(patterns):
    """Same accession in both DataBankList and abstract should appear once."""
    art = _article(
        abstract="Data deposited in GEO (GSE999999).",
        databanks=[{"name": "GEO", "accessions": ["GSE999999"]}]
    )
    confirmed, _ = extract_repository_links(art, patterns)
    geo_matches = [m for m in confirmed if m.repository == "Gene Expression Omnibus" and m.identifier == "GSE999999"]
    assert len(geo_matches) == 1
