"""Unit tests for the affiliation country classifier."""

import pytest
from armlifebank.affiliation import (
    classify_affiliation,
    classify_article,
    CountryClassifier,
)
from armlifebank.config import load_country_profile


# ── Armenia-country: should be "armenia_country" ─────────────────────────────

@pytest.mark.parametrize("raw", [
    # Classic country-as-last-token patterns
    "Department of Biology, Yerevan State University, Yerevan, Armenia",
    "Institute of Molecular Biology, NAS RA, Yerevan, Armenia.",
    "National Center of Oncology, Yerevan, Armenia",
    "Republican Medical Center, Yerevan, Armenia,",

    # Republic of Armenia explicit
    "State Committee of Science, Republic of Armenia",

    # .am email domain
    "YSU Faculty of Medicine, info@ysu.am",
    "author@sci.am, Institute of Fine Organic Chemistry, Yerevan",

    # Armenian institutions with city
    "Yerevan State Medical University, Yerevan, Armenia",
    "American University of Armenia, Yerevan, Armenia",
    "National Polytechnic University of Armenia, Yerevan",

    # Armenian cities alone (broad mode tested separately)
    "Gyumri Medical Centre, Gyumri, Armenia",
    "Vanadzor Children's Hospital, Vanadzor, Armenia",

    # Trailing whitespace / punctuation variants
    "Laboratory of Genetics, Yerevan State University, Armenia. ",
    "Erebuni Medical Center, Yerevan, Armenia;",
])
def test_armenia_country_strict(raw):
    assert classify_affiliation(raw, mode="strict") == "armenia_country", repr(raw)


# ── Colombia exclusions: should be "not_armenia_country" ─────────────────────

@pytest.mark.parametrize("raw", [
    # Direct Colombia tokens
    "Universidad del Quindío, Armenia, Colombia",
    "Facultad de Medicina, Armenia, Quindío, Colombia",
    "Fundación Universitaria del Área Andina, Armenia, Quindío",
    "Hospital San Juan de Dios, Armenia, Colombia",

    # Quindío alone
    "Programa de Enfermería, Universidad del Quindío, Quindío, Colombia",
    "Universidad Antonio Nariño, Armenia, Quindío",

    # Colombian city co-occurrence
    "Grupo de Investigación, Bogotá, Colombia",
    "Universidad Nacional de Colombia, Medellín",

    # Fundación Universitaria (Colombian pattern)
    "Fundación Universitaria del Área Andina, Pereira",
])
def test_colombia_exclusion(raw):
    assert classify_affiliation(raw, mode="strict") == "not_armenia_country", repr(raw)

@pytest.mark.parametrize("raw", [
    "Universidad del Quindío, Armenia, Quindío, Colombia",
    "Armenia, Quindío",
    "Armenia, Colombia",
])
def test_colombia_exclusion_broad(raw):
    """Colombia exclusions must hold even in broad mode."""
    assert classify_affiliation(raw, mode="broad") == "not_armenia_country", repr(raw)


# ── Uncertain cases ───────────────────────────────────────────────────────────

@pytest.mark.parametrize("raw", [
    # "Armenian" adjective without country
    "Armenian Medical Institute, unspecified location",
    "Armenian Cardiology Association",

    # "Armenia" without strong geographic anchor (strict mode)
    "South Armenia Industrial Zone, unspecified",
])
def test_uncertain_strict(raw):
    result = classify_affiliation(raw, mode="strict")
    assert result in ("uncertain", "not_armenia_country"), repr(raw)


# ── Broad mode: city or institution alone → armenia_country ──────────────────

@pytest.mark.parametrize("raw", [
    "Institute of Biochemistry, Yerevan",
    "Gyumri State Medical Institute",
    "NAS RA, Institute of Radiophysics and Electronics",
    "Muratsan Hospital Complex",
])
def test_broad_mode_city_or_institution(raw):
    assert classify_affiliation(raw, mode="broad") == "armenia_country", repr(raw)


# ── .am domain is always armenia_country ─────────────────────────────────────

def test_am_domain_strict():
    assert classify_affiliation(
        "researcher@nias.am, National Institute, unspecified", mode="strict"
    ) == "armenia_country"

def test_am_domain_no_other_signal():
    assert classify_affiliation(
        "contact@example.am", mode="strict"
    ) == "armenia_country"


# ── Article-level classification ──────────────────────────────────────────────

def test_article_armenia_country_one_of_many():
    """Article is armenia_country if at least one affiliation is."""
    affs = [
        "Universidad del Quindío, Armenia, Colombia",     # excluded
        "Yerevan State University, Yerevan, Armenia",     # armenia_country
        "Imperial College London, London, UK",            # not
    ]
    cl = classify_article("12345", affs, mode="strict")
    assert cl.label == "armenia_country"
    assert cl.n_armenia == 1
    # n_excluded counts all not_armenia_country affiliations (Colombia + UK affil)
    assert cl.n_excluded == 2


def test_article_all_colombia():
    affs = [
        "Universidad del Quindío, Armenia, Colombia",
        "Hospital Armenia, Quindío, Colombia",
    ]
    cl = classify_article("99999", affs, mode="strict")
    assert cl.label == "not_armenia_country"
    assert cl.n_armenia == 0


def test_article_uncertain_only():
    affs = [
        "Armenian Medical Institute",
        "Armenian Research Foundation",
    ]
    cl = classify_article("77777", affs, mode="strict")
    assert cl.label == "uncertain"
    assert cl.n_uncertain == 2


def test_article_empty_affiliations():
    cl = classify_article("00000", [], mode="strict")
    assert cl.label == "not_armenia_country"


# ── CountryClassifier direct API (Armenia profile) ───────────────────────────

@pytest.fixture(scope="module")
def armenia_classifier():
    return CountryClassifier(load_country_profile("armenia"))


def test_classifier_labels(armenia_classifier):
    """Label constants reflect the country code."""
    assert armenia_classifier.MATCH     == "armenia_country"
    assert armenia_classifier.NO_MATCH  == "not_armenia_country"
    assert armenia_classifier.UNCERTAIN == "uncertain"


def test_classifier_match(armenia_classifier):
    result = armenia_classifier.classify_affiliation(
        "Yerevan State University, Yerevan, Armenia", mode="strict"
    )
    assert result == "armenia_country"


def test_classifier_no_match(armenia_classifier):
    result = armenia_classifier.classify_affiliation(
        "Harvard Medical School, Boston, MA, USA", mode="strict"
    )
    assert result == "not_armenia_country"


def test_classifier_uncertain_adjective(armenia_classifier):
    result = armenia_classifier.classify_affiliation(
        "Armenian Cardiology Association", mode="strict"
    )
    assert result == "uncertain"


def test_classifier_article_level(armenia_classifier):
    affs = [
        "Universidad del Quindío, Armenia, Colombia",
        "Yerevan State Medical University, Armenia",
    ]
    cl = armenia_classifier.classify_article("55555", affs, mode="strict")
    assert cl.label == "armenia_country"
    assert cl.n_armenia == 1
    assert cl.n_excluded == 1


def test_classifier_classify_articles_output_rows(armenia_classifier):
    articles = [
        {"pmid": "A1", "all_affiliations": ["Yerevan State University, Armenia"]},
        {"pmid": "A2", "all_affiliations": ["Armenia, Colombia"]},
        {"pmid": "A3", "all_affiliations": ["Armenian Medical Institute"]},
    ]
    classifications, rows = armenia_classifier.classify_articles(articles, mode="strict")
    labels = {c.pmid: c.label for c in classifications}
    assert labels["A1"] == "armenia_country"
    assert labels["A2"] == "not_armenia_country"
    assert labels["A3"] == "uncertain"
    assert len(rows["validated"]) == 1
    assert len(rows["excluded"])  == 1
    assert len(rows["uncertain"]) == 1


# ── Latvia classifier smoke tests ─────────────────────────────────────────────

@pytest.fixture(scope="module")
def latvia_classifier():
    return CountryClassifier(load_country_profile("latvia"))


def test_latvia_classifier_labels(latvia_classifier):
    assert latvia_classifier.MATCH     == "latvia_country"
    assert latvia_classifier.NO_MATCH  == "not_latvia_country"
    assert latvia_classifier.UNCERTAIN == "uncertain"


@pytest.mark.parametrize("raw", [
    "University of Latvia, Riga, Latvia",
    "Riga Stradins University, Riga, Latvia",
    "Riga Technical University, Latvia",
    "Institute of Biology, University of Latvia, Riga, Latvia",
    "Pauls Stradins Clinical University Hospital, Riga, Latvia",
    "researcher@rsu.lv",
    "Republic of Latvia",
    "Latvian Institute of Organic Chemistry, Riga, Latvia",
])
def test_latvia_country_strict(raw, latvia_classifier):
    result = latvia_classifier.classify_affiliation(raw, mode="strict")
    assert result == "latvia_country", repr(raw)


@pytest.mark.parametrize("raw", [
    "Harvard Medical School, Boston, MA, USA",
    "University of Helsinki, Helsinki, Finland",
    "Johns Hopkins University, Baltimore, MD",
])
def test_not_latvia_country(raw, latvia_classifier):
    result = latvia_classifier.classify_affiliation(raw, mode="strict")
    assert result == "not_latvia_country", repr(raw)


def test_latvia_uncertain_adjective(latvia_classifier):
    result = latvia_classifier.classify_affiliation(
        "Latvian Research Foundation, unspecified", mode="strict"
    )
    assert result == "uncertain"


def test_latvia_city_alone_strict_uncertain(latvia_classifier):
    """City alone in strict mode is uncertain (no country name present)."""
    result = latvia_classifier.classify_affiliation(
        "Institute of Cardiology, Riga", mode="strict"
    )
    assert result == "uncertain"


def test_latvia_city_alone_broad_match(latvia_classifier):
    """City alone in broad mode yields latvia_country."""
    result = latvia_classifier.classify_affiliation(
        "Institute of Cardiology, Riga", mode="broad"
    )
    assert result == "latvia_country"


def test_latvia_article_level(latvia_classifier):
    affs = [
        "Harvard Medical School, Boston, USA",
        "University of Latvia, Riga, Latvia",
    ]
    cl = latvia_classifier.classify_article("LV001", affs, mode="strict")
    assert cl.label == "latvia_country"
    assert cl.n_armenia == 1   # n_armenia stores match count (kept for compat)
    assert cl.n_excluded == 1
