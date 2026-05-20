"""
Affiliation country classifier for the ArmLifeBank pipeline.

Primary API:
  classifier = CountryClassifier(profile)          # profile from load_country_profile()
  classifier.classify_affiliation(raw, mode)  -> "<code>_country" | "not_<code>_country" | "uncertain"
  classifier.classify_article(pmid, affs, mode) -> ArticleClassification
  classifier.classify_articles(articles, mode) -> (classifications, output_rows)

Backward-compatible module-level wrappers (default to Armenia profile):
  classify_affiliation(raw, mode)
  classify_article(pmid, affiliations, mode)
  classify_articles(articles, mode)

Classification modes (controlled by Config.mode):
  strict – requires explicit country-level evidence (country as trailing token,
            "Republic of <Country>", or strong institution + city evidence)
  broad  – additionally accepts city / institution alone
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


# ── CountryClassifier ────────────────────────────────────────────────────────

class CountryClassifier:
    """
    Rule-driven affiliation classifier built from a country profile dict.

    Instantiate with the dict returned by ``config.load_country_profile()``.
    """

    def __init__(self, profile: dict) -> None:
        self.code: str = profile["code"]
        self.name: str = profile.get("name", self.code.capitalize())

        domain_suffix = profile.get("domain_suffix", "")
        self._domain_re: Optional[re.Pattern] = (
            re.compile(
                r"\b[\w.\-]+@[\w.\-]+" + re.escape(domain_suffix) + r"\b",
                re.I,
            )
            if domain_suffix
            else None
        )

        self._country_name_re: re.Pattern = re.compile(
            profile["country_name_pattern"], re.I
        )
        adjective_pat = profile.get("adjective_pattern")
        self._adjective_re: Optional[re.Pattern] = (
            re.compile(adjective_pat, re.I) if adjective_pat else None
        )
        self._negative:        list[re.Pattern] = [
            re.compile(p, re.I) for p in profile.get("negative_patterns", [])
        ]
        self._strong_positive: list[re.Pattern] = [
            re.compile(p, re.I) for p in profile.get("strong_positive_patterns", [])
        ]
        self._institutions:    list[re.Pattern] = [
            re.compile(p, re.I) for p in profile.get("institution_patterns", [])
        ]
        self._cities:          list[re.Pattern] = [
            re.compile(p, re.I) for p in profile.get("city_patterns", [])
        ]

        # Label constants — callers can use these instead of string literals
        self.MATCH:     str = f"{self.code}_country"
        self.NO_MATCH:  str = f"not_{self.code}_country"
        self.UNCERTAIN: str = "uncertain"

    # ── internal helpers ──────────────────────────────────────────────────────

    def _has_negative(self, text: str) -> bool:
        return any(p.search(text) for p in self._negative)

    def _has_domain(self, text: str) -> bool:
        return bool(self._domain_re and self._domain_re.search(text))

    def _has_country_name(self, text: str) -> bool:
        return bool(self._country_name_re.search(text))

    def _has_city(self, text: str) -> bool:
        return any(p.search(text) for p in self._cities)

    def _has_institution(self, text: str) -> bool:
        return any(p.search(text) for p in self._institutions)

    # ── public classification API ─────────────────────────────────────────────

    def classify_affiliation(self, raw: str, mode: str = "strict") -> str:
        """
        Classify a single affiliation string.

        Returns
        -------
        "<code>_country"      – confident this affiliation is in the target country
        "not_<code>_country"  – confident it is NOT in the target country
        "uncertain"           – cannot determine with confidence
        """
        # Step 1: reject false-positive signals unconditionally
        if self._has_negative(raw):
            return self.NO_MATCH

        # Step 2: strong positive signals (sufficient in both modes)
        for pat in self._strong_positive:
            if pat.search(raw):
                return self.MATCH
        if self._has_domain(raw):
            return self.MATCH

        has_country = self._has_country_name(raw)
        has_city    = self._has_city(raw)

        # Step 3: institution present
        if self._has_institution(raw):
            if has_country or has_city:
                return self.MATCH
            if mode == "broad":
                return self.MATCH
            return self.UNCERTAIN

        # Step 4: city present
        if has_city:
            if has_country:
                return self.MATCH
            if mode == "broad":
                return self.MATCH
            return self.UNCERTAIN

        # Step 5: bare country name, no geographic confirmation
        if has_country:
            return self.UNCERTAIN

        # Step 6: country adjective alone (e.g. "Armenian", "Latvian") — weak signal
        if self._adjective_re and self._adjective_re.search(raw):
            return self.UNCERTAIN

        return self.NO_MATCH

    def classify_article(
        self,
        pmid: str,
        affiliations: list[str],
        mode: str = "strict",
    ) -> "ArticleClassification":
        """
        Classify all affiliations for one article and derive an article-level label.

        Article label:
          <code>_country      – at least one affiliation is <code>_country
          not_<code>_country  – zero matches, zero uncertain
          uncertain           – zero matches, at least one uncertain
        """
        per_aff: list[dict] = []
        for raw in affiliations:
            result = self.classify_affiliation(raw, mode)
            per_aff.append({"raw": raw, "result": result})

        n_match     = sum(1 for d in per_aff if d["result"] == self.MATCH)
        n_excluded  = sum(1 for d in per_aff if d["result"] == self.NO_MATCH)
        n_uncertain = sum(1 for d in per_aff if d["result"] == self.UNCERTAIN)

        if n_match > 0:
            label = self.MATCH
        elif n_uncertain > 0:
            label = self.UNCERTAIN
        else:
            label = self.NO_MATCH

        return ArticleClassification(
            pmid=pmid,
            label=label,
            per_affiliation=per_aff,
            n_armenia=n_match,       # kept as n_armenia for CSV column compat
            n_excluded=n_excluded,
            n_uncertain=n_uncertain,
        )

    def classify_articles(
        self,
        articles: list[dict],
        mode: str = "strict",
    ) -> tuple[list["ArticleClassification"], dict[str, list[dict]]]:
        """
        Classify all articles.

        Returns
        -------
        classifications : list of ArticleClassification (one per article)
        output_rows     : dict with keys
            "validated"  – rows for affiliations_validated.csv
            "uncertain"  – rows for affiliations_uncertain.csv
            "excluded"   – rows for affiliations_excluded.csv
        """
        classifications: list[ArticleClassification] = []
        validated_rows: list[dict] = []
        uncertain_rows: list[dict] = []
        excluded_rows:  list[dict] = []

        for art in articles:
            pmid = art.get("pmid", "")
            affs = art.get("all_affiliations", [])
            cl   = self.classify_article(pmid, affs, mode)
            classifications.append(cl)

            for d in cl.per_affiliation:
                row = {
                    "pmid":        pmid,
                    "affiliation": d["raw"],
                    "result":      d["result"],
                }
                if d["result"] == self.MATCH:
                    validated_rows.append(row)
                elif d["result"] == self.UNCERTAIN:
                    uncertain_rows.append(row)
                else:
                    excluded_rows.append(row)

        return classifications, {
            "validated": validated_rows,
            "uncertain": uncertain_rows,
            "excluded":  excluded_rows,
        }


# ── ArticleClassification dataclass ─────────────────────────────────────────

@dataclass
class ArticleClassification:
    pmid:  str
    label: str   # "<code>_country" | "not_<code>_country" | "uncertain"
    per_affiliation: list[dict] = field(default_factory=list)
    # counts — n_armenia kept for backward compat with CSV column name
    n_armenia:   int = 0
    n_excluded:  int = 0
    n_uncertain: int = 0


# ── Backward-compatible module-level wrappers (default to Armenia) ───────────
# These are used by the existing test suite (test_affiliation.py) which will be
# updated in Stage 5.  New code should instantiate CountryClassifier directly.

def _default_armenia_classifier() -> CountryClassifier:
    """Return a CountryClassifier for Armenia using the bundled profile."""
    from armlifebank.config import load_country_profile
    profile = load_country_profile("armenia")
    return CountryClassifier(profile)


def classify_affiliation(raw: str, mode: str = "strict") -> str:
    """Classify a single affiliation string using the Armenia profile."""
    return _default_armenia_classifier().classify_affiliation(raw, mode)


def classify_article(
    pmid: str,
    affiliations: list[str],
    mode: str = "strict",
) -> ArticleClassification:
    """Classify article affiliations using the Armenia profile."""
    return _default_armenia_classifier().classify_article(pmid, affiliations, mode)


def classify_articles(
    articles: list[dict],
    mode: str = "strict",
) -> tuple[list[ArticleClassification], dict[str, list[dict]]]:
    """Classify all articles using the Armenia profile."""
    return _default_armenia_classifier().classify_articles(articles, mode)
