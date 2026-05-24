#!/usr/bin/env python3
"""
LHA Normalize — Module 2
========================
Pure normalization functions that bring every identifier into a canonical
form before any comparison.  Matching is exact-string after normalization;
no fuzzy logic here.

Public API
----------
normalize_doi(s)                    -> str | None
normalize_url(s)                    -> str | None
normalize_accession(repository, s)  -> str | None
extract_doi_from_url(url)           -> str | None

All functions accept None / empty string and return None for invalid input.
No function raises — errors are signalled by returning None.
"""

from __future__ import annotations

import re
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

# ── DOI helpers ───────────────────────────────────────────────────────────────

# Recognised DOI URL / textual prefixes (checked case-insensitively)
_DOI_PREFIXES: list[str] = [
    "https://doi.org/",
    "http://doi.org/",
    "https://dx.doi.org/",
    "http://dx.doi.org/",
    "doi:",
]

# A valid DOI begins with "10." followed by ≥4 digits, a slash, and ≥1 non-space chars
_DOI_RE = re.compile(r"^10\.\d{4,}/.+$")

# Version suffix on accessions: ".1", ".12", etc.
_VERSION_RE = re.compile(r"\.\d+$")

# ClinicalTrials.gov identifier
_NCT_RE = re.compile(r"^NCT\d{8}$", re.IGNORECASE)


# ── normalize_doi ─────────────────────────────────────────────────────────────

def normalize_doi(s: str | None) -> str | None:
    """
    Strip common DOI prefixes and return a lowercase canonical DOI string.

    Handled prefixes (case-insensitive):
      https://doi.org/<doi>
      http://doi.org/<doi>
      https://dx.doi.org/<doi>
      http://dx.doi.org/<doi>
      doi:<doi>
      10.XXXX/...  (bare — no prefix)

    Returns None if the stripped result does not match ^10\\.\\d{4,}/.+$
    or if the input is empty / None.
    """
    if not s:
        return None
    s = s.strip()
    if not s:
        return None

    lower = s.lower()
    for prefix in _DOI_PREFIXES:
        if lower.startswith(prefix):
            s = s[len(prefix):]
            break

    s = s.strip().lower()
    if _DOI_RE.match(s):
        return s
    return None


# ── normalize_url ─────────────────────────────────────────────────────────────

def normalize_url(s: str | None) -> str | None:
    """
    Return a canonical URL suitable for exact-string comparison.

    Transformations applied:
      - Strip leading / trailing whitespace
      - Lowercase scheme and host
      - Remove 'www.' prefix from host
      - Strip default ports (80 for http, 443 for https)
      - Strip trailing slash(es) from path (except bare root '/')
      - Remove query parameters whose key starts with 'utm_'
      - Sort remaining query parameters alphabetically by key
      - Drop URL fragment (#...)
      - Path case is preserved (paths can be case-sensitive)

    Returns None for empty input or if urlparse cannot extract a scheme.
    """
    if not s:
        return None
    s = s.strip()
    if not s:
        return None

    try:
        parsed = urlparse(s)
        if not parsed.scheme:
            return None

        scheme = parsed.scheme.lower()

        # Hostname — lowercase, strip www.
        hostname = (parsed.hostname or "").lower()
        if hostname.startswith("www."):
            hostname = hostname[4:]

        # Port — strip default ports
        port = parsed.port
        if (scheme == "http" and port == 80) or (scheme == "https" and port == 443):
            port = None
        netloc = f"{hostname}:{port}" if port else hostname

        # Path — strip trailing slashes (keep bare "/" as "")
        path = parsed.path
        if len(path) > 1:
            path = path.rstrip("/")

        # Query — remove utm_* params, sort the rest
        qparams = parse_qsl(parsed.query, keep_blank_values=True)
        qparams = [(k, v) for k, v in qparams if not k.lower().startswith("utm_")]
        qparams.sort(key=lambda kv: kv[0])
        query = urlencode(qparams)

        # Fragment dropped (pass "" as fragment arg to urlunparse)
        return urlunparse((scheme, netloc, path, "", query, ""))

    except Exception:
        return None


# ── normalize_accession ───────────────────────────────────────────────────────

def normalize_accession(repository: str, s: str | None) -> str | None:
    """
    Apply per-repository normalization rules and return a canonical accession.

    Per-repository rules
    --------------------
    GenBank          : strip version suffix (.1, .2 …), uppercase
                       e.g.  MK123456.1  →  MK123456
    RefSeq           : same as GenBank
    ENA              : strip version suffix, uppercase
    Gene Expression
      Omnibus (GEO)  : uppercase
                       e.g.  gse148736   →  GSE148736
    PDB              : uppercase; return None if result is not exactly 4 chars
                       e.g.  2cuu        →  2CUU
    SRA              : uppercase
    BioProject       : uppercase   e.g.  prjna123    →  PRJNA123
    BioSample        : uppercase   e.g.  samn123     →  SAMN123
    PRIDE            : uppercase   e.g.  pxd000001   →  PXD000001
    EGA              : uppercase   e.g.  egad00001   →  EGAD00001
    dbGaP            : uppercase   e.g.  phs000001   →  PHS000001
    ArrayExpress     : uppercase   e.g.  e-mtab-1234 →  E-MTAB-1234
    ClinicalTrials   : uppercase; return None if result does not match NCT\\d{8}
    MetaboLights     : uppercase   e.g.  mtbls123    →  MTBLS123
    OSF / Zenodo /
    Figshare / Dryad /
    Mendeley Data /
    Dataverse        : if identifier contains '10.' treat as DOI → normalize_doi();
                       otherwise return stripped as-is (opaque short ID)
    GitHub / GitLab  : lowercase; strip leading github.com/ or gitlab.com/ URL
                       prefix if present; strip trailing .git; strip leading /
                       e.g.  Owner/Repo.git  →  owner/repo
    default          : strip whitespace, return as-is

    Returns None if the result is empty or fails repository-specific validation.
    """
    if s is None:
        return None
    s = s.strip()
    if not s:
        return None

    # ── Sequence / structure archives ────────────────────────────────────────
    if repository in ("GenBank", "RefSeq", "ENA"):
        return _VERSION_RE.sub("", s).upper() or None

    if repository == "Gene Expression Omnibus":
        return s.upper() or None

    if repository == "PDB":
        result = s.upper()
        return result if len(result) == 4 else None

    if repository in ("SRA", "BioProject", "BioSample",
                      "PRIDE", "EGA", "dbGaP",
                      "ArrayExpress", "MetaboLights"):
        return s.upper() or None

    if repository == "ClinicalTrials.gov":
        result = s.upper()
        return result if _NCT_RE.match(result) else None

    # ── General-purpose repositories ─────────────────────────────────────────
    if repository in ("OSF", "Zenodo", "Figshare",
                      "Dryad", "Mendeley Data", "Dataverse"):
        if "10." in s:
            return normalize_doi(s)
        return s or None

    # ── Code repositories ─────────────────────────────────────────────────────
    if repository in ("GitHub", "GitLab"):
        # Strip full URL prefix if present
        for prefix in ("https://github.com/", "http://github.com/",
                       "https://gitlab.com/", "http://gitlab.com/"):
            if s.lower().startswith(prefix):
                s = s[len(prefix):]
                break
        s = s.lower().strip("/")
        if s.endswith(".git"):
            s = s[:-4]
        return s or None

    # ── Default: strip whitespace ─────────────────────────────────────────────
    return s or None


# ── extract_doi_from_url ──────────────────────────────────────────────────────

def extract_doi_from_url(url: str | None) -> str | None:
    """
    If a URL is a known DOI redirector, extract and return the normalized DOI.

    Handled patterns
    ----------------
    doi.org/<doi>             →  normalize the path as a DOI
    dx.doi.org/<doi>          →  same
    zenodo.org/doi/<doi>      →  normalize the path segment after /doi/
    zenodo.org/record/<id>    →  None (record ID ≠ DOI)
    zenodo.org/records/<id>   →  None
    figshare.com/...          →  None (no DOI embedded in URL)
    osf.io/...                →  None (short IDs, not DOIs)

    Returns normalize_doi(extracted_doi) or None.
    """
    if not url:
        return None
    url = url.strip()
    if not url:
        return None

    try:
        parsed = urlparse(url)
        host = (parsed.hostname or "").lower()
        if host.startswith("www."):
            host = host[4:]
        path = parsed.path

        # doi.org / dx.doi.org — path IS the DOI
        if host in ("doi.org", "dx.doi.org"):
            return normalize_doi(path.lstrip("/"))

        # zenodo.org/doi/<doi>
        if host == "zenodo.org" and path.startswith("/doi/"):
            return normalize_doi(path[5:])

        # All other hosts: no extractable DOI
        return None

    except Exception:
        return None
