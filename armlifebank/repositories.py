"""
Repository / accession extraction for the ArmLifeBank pipeline.

Extraction sources (in priority order):
  1. PubMed DataBankList   – curated accessions in PubMed XML
  2. PMC JATS XML          – full text: data-availability, ext-link,
                             supplementary-material, methods, body text
  3. PubMed abstract       – last-resort keyword scan

Patterns are loaded from repository_patterns.yaml so they can be
edited without touching Python code.
"""

from __future__ import annotations

import logging
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml

logger = logging.getLogger(__name__)

# ── Pattern loading ───────────────────────────────────────────────────────────

@dataclass
class RepoPattern:
    name: str
    category: str
    id_type: str
    compiled: list[re.Pattern]
    confidence: str


def load_patterns(yaml_path: Path) -> list[RepoPattern]:
    with yaml_path.open(encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    patterns: list[RepoPattern] = []
    for entry in data.get("repositories", []):
        compiled = [
            re.compile(p, re.IGNORECASE | re.UNICODE)
            for p in entry.get("patterns", [])
        ]
        patterns.append(RepoPattern(
            name=entry["name"],
            category=entry.get("category", "other"),
            id_type=entry.get("id_type", "unknown"),
            compiled=compiled,
            confidence=entry.get("confidence", "medium"),
        ))
    return patterns


# ── Result dataclass ──────────────────────────────────────────────────────────

@dataclass
class RepoMatch:
    pmid: str
    pmcid: str
    doi: str
    repository: str
    repository_category: str
    identifier: str
    identifier_type: str
    evidence_source: str   # pubmed_databank | pmc_xml | abstract
    evidence_section: str  # data_availability | methods | ext_link | body | abstract | databank
    evidence_snippet: str  # ≤200 chars around the match
    confidence: str        # high | medium | low


# ── Snippet helper ────────────────────────────────────────────────────────────

def _snippet(text: str, match: re.Match, context: int = 100) -> str:
    start = max(0, match.start() - context)
    end   = min(len(text), match.end() + context)
    raw = text[start:end].replace("\n", " ").replace("\r", "")
    # collapse whitespace
    return re.sub(r"\s{2,}", " ", raw).strip()


# ── Deduplication key ─────────────────────────────────────────────────────────

def _dedup_key(pmid: str, repo: str, identifier: str) -> str:
    return f"{pmid}|{repo}|{identifier.upper()}"


# ── Source 1: PubMed DataBankList ─────────────────────────────────────────────

_PUBMED_DB_NORMALISE: dict[str, str] = {
    "GEO": "Gene Expression Omnibus", "GENE EXPRESSION OMNIBUS": "Gene Expression Omnibus",
    "SRA": "SRA", "SEQUENCE READ ARCHIVE": "SRA",
    "GENBANK": "GenBank", "NUCLEOTIDE": "GenBank",
    "BIOPROJECT": "BioProject",
    "BIOSAMPLE": "BioSample",
    "DBGAP": "dbGaP",
    "ARRAYEXPRESS": "ArrayExpress",
    "PRIDE": "PRIDE",
    "PROTEOMEXCHANGE": "PRIDE",
    "METABOLIGHTS": "MetaboLights",
    "EGA": "EGA",
    "PDB": "PDB",
    "DBSNP": "dbSNP",
    "CLINVAR": "ClinVar",
    "DRYAD": "Dryad",
    "FIGSHARE": "Figshare",
    "ZENODO": "Zenodo",
    "OSF": "OSF",
    "ENA": "ENA",
}

_REPO_CATEGORY: dict[str, str] = {
    "Gene Expression Omnibus": "transcriptomics", "SRA": "raw_reads", "GenBank": "nucleotide_sequence",
    "BioProject": "raw_reads", "BioSample": "raw_reads", "dbGaP": "variation",
    "ArrayExpress": "transcriptomics", "PRIDE": "proteomics", "MetaboLights": "metabolomics",
    "EGA": "controlled_access", "PDB": "structure", "dbSNP": "variation",
    "ClinVar": "variation", "Dryad": "general_repository", "Figshare": "general_repository",
    "Zenodo": "general_repository", "OSF": "general_repository", "ENA": "nucleotide_sequence",
    "GitHub": "code_repository", "GitLab": "code_repository",
    "Mendeley Data": "general_repository", "Dataverse": "general_repository",
}


def _extract_from_databanks(
    article: dict,
    patterns: list[RepoPattern],   # unused here but kept for signature consistency
) -> list[RepoMatch]:
    pmid  = article.get("pmid", "")
    pmcid = article.get("pmcid", "") or article.get("_ft", None) and article["_ft"].pmcid or ""
    doi   = article.get("doi", "")
    matches: list[RepoMatch] = []

    for db in article.get("databanks", []):
        raw_name = db.get("name", "").upper().strip()
        norm_name = _PUBMED_DB_NORMALISE.get(raw_name, db.get("name", raw_name))
        cat = _REPO_CATEGORY.get(norm_name, "other")
        for acc in db.get("accessions", []):
            if acc:
                matches.append(RepoMatch(
                    pmid=pmid, pmcid=pmcid, doi=doi,
                    repository=norm_name,
                    repository_category=cat,
                    identifier=acc,
                    identifier_type="accession",
                    evidence_source="pubmed_databank",
                    evidence_section="databank",
                    evidence_snippet=f"PubMed DataBankList: {raw_name} / {acc}",
                    confidence="high",
                ))
    return matches


# ── Source 2: PMC JATS XML ────────────────────────────────────────────────────

# JATS section tags that commonly contain data-availability text
_DATA_SECTION_TITLES: re.Pattern = re.compile(
    r"data\s+(availability|access|sharing|deposit(?:ion)?s?|statement)|"
    r"availability\s+of\s+data|accession\s+(number|code)s?|"
    r"code\s+availability|supplementary\s+(material|data|information)",
    re.IGNORECASE,
)

# Sections where data references appear with high confidence
_HIGH_CONF_SECTIONS = {"data_availability", "supplementary", "ext_link", "databank"}


def _iter_jats_text_blocks(xml_str: str) -> list[tuple[str, str]]:
    """
    Parse JATS XML and return a list of (section_label, text_content) tuples.

    section_label is one of:
      data_availability | methods | supplementary | body | ext_link | caption

    Real PMC JATS always declares xmlns:xlink; as a fallback for test fixtures
    or malformed XML we inject a synthetic declaration so the parser succeeds.
    """
    blocks: list[tuple[str, str]] = []

    def _parse(s: str) -> Optional[ET.Element]:
        try:
            return ET.fromstring(s.encode("utf-8", errors="replace"))
        except ET.ParseError:
            return None

    root = _parse(xml_str)
    if root is None:
        # Inject common namespace declarations and retry
        patched = xml_str.replace(
            "<article",
            '<article xmlns:xlink="http://www.w3.org/1999/xlink"'
            ' xmlns:mml="http://www.w3.org/1998/Math/MathML"',
            1,
        )
        root = _parse(patched)
    if root is None:
        logger.debug("JATS XML could not be parsed even after namespace injection.")
        return blocks

    def _inner_text(el: ET.Element) -> str:
        return " ".join((el.itertext()))

    # ── ext-link and related-object elements ─────────────────────────────
    for el in root.iter("ext-link"):
        href = el.get("{http://www.w3.org/1999/xlink}href") or el.get("href") or ""
        text = _inner_text(el).strip()
        combined = f"{href} {text}".strip()
        if combined:
            blocks.append(("ext_link", combined))

    for el in root.iter("related-object"):
        text = _inner_text(el).strip()
        source_id = el.get("source-id", "")
        combined = f"{source_id} {text}".strip()
        if combined:
            blocks.append(("ext_link", combined))

    # ── supplementary-material elements ──────────────────────────────────
    for el in root.iter("supplementary-material"):
        href = el.get("{http://www.w3.org/1999/xlink}href") or el.get("href") or ""
        text = _inner_text(el).strip()
        combined = f"{href} {text}".strip()
        if combined:
            blocks.append(("supplementary", combined))

    # ── named sections (data-availability, methods, body) ─────────────────
    for sec in root.iter("sec"):
        # Try to get section title
        title_el = sec.find("title")
        title = _inner_text(title_el).strip() if title_el is not None else ""
        text = _inner_text(sec).strip()
        if _DATA_SECTION_TITLES.search(title):
            blocks.append(("data_availability", text))
        elif re.search(r"\bmethod[s]?\b", title, re.IGNORECASE):
            blocks.append(("methods", text))
        elif re.search(r"\backnowledg", title, re.IGNORECASE):
            blocks.append(("acknowledgements", text))
        else:
            blocks.append(("body", text))

    # ── custom-meta / kwd-group / notes (sometimes hold accessions) ───────
    for el in root.iter("custom-meta"):
        text = _inner_text(el).strip()
        if text:
            blocks.append(("body", text))

    # ── article-meta (contains some accession fields) ─────────────────────
    for el in root.iter("article-meta"):
        for child in el:
            if child.tag in ("self-uri", "related-article"):
                href = child.get("{http://www.w3.org/1999/xlink}href") or ""
                text = _inner_text(child).strip()
                combined = f"{href} {text}".strip()
                if combined:
                    blocks.append(("ext_link", combined))

    return blocks


def _extract_from_jats(
    article: dict,
    ft_xml: str,
    patterns: list[RepoPattern],
) -> list[RepoMatch]:
    pmid  = article.get("pmid", "")
    pmcid_val = ""
    if article.get("_ft"):
        pmcid_val = article["_ft"].pmcid
    doi   = article.get("doi", "")

    matches: list[RepoMatch] = []
    seen: set[str] = set()

    blocks = _iter_jats_text_blocks(ft_xml)

    for section, text in blocks:
        for repo in patterns:
            # Boost confidence for high-signal sections
            effective_conf = repo.confidence
            if section in _HIGH_CONF_SECTIONS and effective_conf == "medium":
                effective_conf = "high"

            for pat in repo.compiled:
                for m in pat.finditer(text):
                    identifier = m.group(1) if m.lastindex and m.lastindex >= 1 else m.group(0)
                    identifier = identifier.strip()
                    if not identifier:
                        continue

                    # Skip very short / generic tokens for medium/low confidence patterns
                    if len(identifier) < 4 and effective_conf != "high":
                        continue

                    key = _dedup_key(pmid, repo.name, identifier)
                    if key in seen:
                        continue
                    seen.add(key)

                    matches.append(RepoMatch(
                        pmid=pmid, pmcid=pmcid_val, doi=doi,
                        repository=repo.name,
                        repository_category=repo.category,
                        identifier=identifier,
                        identifier_type=repo.id_type,
                        evidence_source="pmc_xml",
                        evidence_section=section,
                        evidence_snippet=_snippet(text, m),
                        confidence=effective_conf,
                    ))

    return matches


# ── Source 3: PubMed abstract fallback ───────────────────────────────────────

def _extract_from_abstract(
    article: dict,
    patterns: list[RepoPattern],
) -> list[RepoMatch]:
    pmid  = article.get("pmid", "")
    pmcid_val = ""
    if article.get("_ft"):
        pmcid_val = article["_ft"].pmcid
    doi   = article.get("doi", "")
    abstract = article.get("abstract", "")
    if not abstract:
        return []

    matches: list[RepoMatch] = []
    seen: set[str] = set()

    for repo in patterns:
        for pat in repo.compiled:
            for m in pat.finditer(abstract):
                identifier = m.group(1) if m.lastindex and m.lastindex >= 1 else m.group(0)
                identifier = identifier.strip()
                if not identifier or len(identifier) < 4:
                    continue
                key = _dedup_key(pmid, repo.name, identifier)
                if key in seen:
                    continue
                seen.add(key)
                matches.append(RepoMatch(
                    pmid=pmid, pmcid=pmcid_val, doi=doi,
                    repository=repo.name,
                    repository_category=repo.category,
                    identifier=identifier,
                    identifier_type=repo.id_type,
                    evidence_source="abstract",
                    evidence_section="abstract",
                    evidence_snippet=_snippet(abstract, m),
                    confidence=repo.confidence,
                ))
    return matches


# ── False-positive filters ────────────────────────────────────────────────────

# Phrases that indicate data-on-request rather than a real deposit
_DATA_ON_REQUEST: re.Pattern = re.compile(
    r"data\s+(are\s+)?available\s+(from\s+the\s+)?(?:upon|on)\s+(?:reasonable\s+)?request|"
    r"available\s+from\s+(?:the\s+)?(?:corresponding|first|senior)\s+author|"
    r"upon\s+request\s+from",
    re.IGNORECASE,
)

def _is_likely_false_positive(match: RepoMatch, article: dict) -> bool:
    """Return True for matches that should go to diagnostics instead of main output."""
    snip = match.evidence_snippet
    # Data-on-request phrases in snippet
    if _DATA_ON_REQUEST.search(snip):
        return True
    # Very generic 2-letter + 5-digit GenBank codes in body text can be noisy
    if match.repository == "GenBank" and match.confidence == "medium":
        if match.evidence_section == "body" and len(match.identifier) <= 7:
            return True
    return False


# ── Main per-article extractor ────────────────────────────────────────────────

def extract_repository_links(
    article: dict,
    patterns: list[RepoPattern],
) -> tuple[list[RepoMatch], list[RepoMatch]]:
    """
    Extract all repository/accession references from one article.

    Returns
    -------
    confirmed   : high/medium confidence matches for article_repository_links.csv
    diagnostics : low confidence or likely false-positives for manual review
    """
    all_matches: list[RepoMatch] = []
    seen_keys: set[str] = set()

    def _add(new_matches: list[RepoMatch]) -> None:
        for m in new_matches:
            key = _dedup_key(m.pmid, m.repository, m.identifier)
            if key not in seen_keys:
                seen_keys.add(key)
                all_matches.append(m)

    # 1. PubMed DataBankList (always available, highest trust)
    _add(_extract_from_databanks(article, patterns))

    # 2. PMC JATS full text (only if retrieved)
    ft = article.get("_ft")
    if ft and getattr(ft, "full_text_xml", ""):
        _add(_extract_from_jats(article, ft.full_text_xml, patterns))

    # 3. Abstract fallback (only if no full text was retrieved)
    if not (ft and getattr(ft, "full_text_xml", "")):
        _add(_extract_from_abstract(article, patterns))

    confirmed: list[RepoMatch] = []
    diagnostics: list[RepoMatch] = []
    for m in all_matches:
        if m.confidence == "low" or _is_likely_false_positive(m, article):
            diagnostics.append(m)
        else:
            confirmed.append(m)

    return confirmed, diagnostics


# ── Batch extractor ───────────────────────────────────────────────────────────

def extract_all(
    articles: list[dict],
    patterns_path: Path,
) -> tuple[list[RepoMatch], list[RepoMatch]]:
    """
    Run extraction over all validated articles.
    Returns (all_confirmed, all_diagnostics).
    """
    patterns = load_patterns(patterns_path)
    logger.info("Loaded %d repository patterns from %s.", len(patterns), patterns_path)

    all_confirmed: list[RepoMatch] = []
    all_diagnostics: list[RepoMatch] = []

    for article in articles:
        confirmed, diagnostics = extract_repository_links(article, patterns)
        all_confirmed.extend(confirmed)
        all_diagnostics.extend(diagnostics)

    n_articles_with_data = len({m.pmid for m in all_confirmed})
    repo_counts: dict[str, int] = {}
    for m in all_confirmed:
        repo_counts[m.repository] = repo_counts.get(m.repository, 0) + 1

    logger.info(
        "Extraction complete: %d links across %d articles | by repo: %s",
        len(all_confirmed), n_articles_with_data, repo_counts,
    )
    return all_confirmed, all_diagnostics
