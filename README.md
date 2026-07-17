# ArmLifeBank – PubMed Armenia Affiliation Audit

A reproducible pipeline that searches PubMed for publications with **Armenia-country** author affiliations (2020–2025), resolves Open Access full text, and detects references to deposited datasets and raw-data repositories.

---

## Data

The dataset produced by this pipeline is archived on Zenodo:

> Arakelyan A. A. (2026). *ArmLifeBank – PubMed Armenia Affiliation Audit: Dataset* (v1.0).
> Zenodo. https://doi.org/10.5281/zenodo.XXXXXXX

The archive contains all CSV/JSON/Markdown outputs for Armenia and the three comparison cohorts (Estonia, Georgia, Leipzig University), including affiliation validation tables, repository mention counts, fragmentation indices, search findability scores, and reuse/citation records.

---

## Quick start

```bash
# Install (preferred)
pip install .

# Or install dependencies only
pip install -r requirements.txt

# Sample run (50 articles, for testing)
armlifebank --sample-size 50 --mode strict

# Full run (2020–2025)
armlifebank --start-year 2020 --end-year 2025 --mode strict

# Resume an interrupted run
armlifebank --resume

# Force re-fetch all API responses
armlifebank --force-refresh-cache
```

Set your NCBI API key in `NCBI_API.txt` (one line) or via environment variable:

```bash
export NCBI_API_KEY=your_key_here
```

---

## Why PubMed query counts alone are insufficient

A raw `Armenia[Affiliation]` query on PubMed returns every article where the word "Armenia" appears anywhere in any affiliation string. This conflates:

- Publications from the **country Armenia** (target)
- Publications from the **city Armenia, Quindío, Colombia** (false positive)
- Any institution whose name contains the word "Armenian" with no country context

In our validation sample of 50 broad-query results, **20% were Colombia false-positives**. Relying on raw counts would substantially overstate Armenian scientific output. The pipeline fetches full PubMed XML, parses every affiliation string individually, and classifies each one before counting.

---

## How affiliations are classified

`armlifebank/affiliation.py` implements a layered rule classifier returning one of:

| Label | Meaning |
|---|---|
| `armenia_country` | Confident this affiliation is in the country Armenia |
| `not_armenia_country` | Confident this is NOT in Armenia (incl. Colombia) |
| `uncertain` | Cannot determine with confidence |

**Negative rules (applied first, unconditionally):**
- Tokens: "Colombia", "Quindío", "Quindio"
- Colombian cities: Bogotá, Medellín, Cali, Pereira, Bucaramanga, …
- Colombian institutions: Universidad del Quindío, Fundación Universitaria, …

**Positive rules (strict mode):**
- "Republic of Armenia" anywhere in the string
- "Armenia" as the trailing country token (e.g., `…, Yerevan, Armenia`)
- `.am` email or web domain
- Known Armenian institutions + city or "Armenia" token

**Broad mode** additionally accepts:
- Armenian city names (Yerevan, Gyumri, Vanadzor, …) without an explicit country token
- Known Armenian institutions without a city confirmation

An article is `armenia_country` if **at least one** of its affiliations is classified as such. Uncertain affiliations are written to `affiliations_uncertain.csv` for manual review.

---

## Why full-text analysis is limited

Full text is retrieved only through legally approved, machine-readable routes:

| Source | When used |
|---|---|
| PMC `efetch` (db=pmc) | Primary: all PMC Open Access articles |
| PMC OA direct JATS link | Non-tgz links only |
| NCBI BioC API | Fallback if efetch fails |
| Europe PMC full-text XML | Last-resort fallback |

**Publisher HTML and PDFs are never scraped.** This means:
- Articles not in the PMC OA subset cannot have their full text analysed
- Repository accessions mentioned only in publisher-hosted supplementary files are missed
- Subscription-access articles are assessed only from PubMed abstract and DataBankList

Typically 60–70% of validated Armenia-country articles have a PMC OA full text available.

---

## How repository/database references are extracted

Patterns are defined in `repository_patterns.yaml` and compiled at runtime. Three extraction sources are used in priority order:

1. **PubMed DataBankList** – curator-verified accession numbers embedded in PubMed XML. Highest confidence.
2. **PMC JATS XML full text** – searched in dedicated sections first:
   - `<sec>` with title matching "data availability", "accession numbers", "code availability", etc.
   - `<supplementary-material>` and `<ext-link>` elements
   - Methods and acknowledgements sections
   - General body text (lower confidence)
3. **PubMed abstract** – used only when no full text is available.

**What counts as a repository reference:**
- An explicit accession number (e.g., `GSE123456`, `PRJNA654321`, `PMC…`)
- A repository DOI (e.g., `10.5281/zenodo.7654321`)
- A repository URL with an identifier path component

**What is excluded:**
- "Data available upon request" phrases
- Generic mentions of a repository name without an identifier
- Low-confidence GenBank single-accession codes in body text (sent to `extraction_diagnostics.csv`)

---

## Output files

| File | Description |
|---|---|
| `output/articles.csv` | One row per validated Armenia-country article, 27 columns |
| `output/article_repository_links.csv` | One row per detected repository/identifier per article |
| `output/repository_counts.csv` | Aggregate counts per repository |
| `output/yearly_repository_counts.csv` | Year × repository breakdown |
| `output/run_summary.json` | Machine-readable run metadata and all counts |
| `output/report.md` | Human-readable Markdown summary with tables |
| `output/affiliations_validated.csv` | Armenia-country affiliation strings |
| `output/affiliations_excluded.csv` | Colombia/other exclusion strings |
| `output/affiliations_uncertain.csv` | Strings requiring manual review |
| `output/extraction_diagnostics.csv` | Low-confidence repository matches for review |
| `logs/pipeline.log` | Full run log |

---

## Known limitations and likely false negatives

- **Affiliation classification is rule-based.** Novel institutional names or unusual formatting may be missed or misclassified. Check `affiliations_uncertain.csv` after each run.
- **~30–40% of articles have no PMC full text.** Repository accessions in these articles are invisible to the pipeline unless they appear in the PubMed DataBankList or abstract.
- **Accessions in figures, tables, and supplementary files** hosted on publisher sites are not captured.
- **GenBank short accessions** (e.g., `MN123456`) are flagged at medium confidence; some matches in body text may be false positives. Review `extraction_diagnostics.csv`.
- **Code repositories (GitHub/GitLab)** are detected but may represent tool citations rather than data deposits. Treat these counts separately.
- **Preprints indexed in PubMed** may have different PMCID status than the final published version.
- **Year of publication** is taken from PubMed metadata; articles published late in a year may be indexed the following year.

---

## Re-running the pipeline

The `.cache/` directory stores all API responses. A second run with the same parameters uses cached data entirely (no network calls). To re-fetch:

```bash
python -m armlifebank.cli --force-refresh-cache
```

To run only a specific year range:

```bash
python -m armlifebank.cli --start-year 2023 --end-year 2025
```

To test classification changes without re-fetching:

```bash
python -m pytest tests/ -v
```

---

## Project structure

```
armlifebank/
├── cli.py              Entry point and pipeline orchestration
├── config.py           Configuration loader (config.yaml, env vars, NCBI_API.txt)
├── cache.py            Disk-based JSON cache for all API responses
├── pubmed.py           PubMed search and XML fetch (E-utilities)
├── affiliation.py      Armenia-country affiliation classifier
├── fulltext.py         PMC OA full-text retrieval
├── repositories.py     Repository/accession extraction
└── reporting.py        Aggregation and CSV/JSON/Markdown output
analysis/
├── harvest.py          Bulk harvest helper scripts
├── normalize.py        Post-processing and normalisation utilities
├── match.py            Cross-cohort matching
├── combine_results.py  Merge multi-country outputs into comparison tables
├── fragmentation.py    Repository fragmentation index computation
├── fragmentation_armlifebank.py  ArmLifeBank-subset fragmentation
├── reuse.py            Reuse and citation analysis for DOI-bearing datasets
├── search_findability.py  Metadata search findability audit
├── lha_report.py       LHA-specific reporting
└── alb_stats.py        ArmLifeBank access statistics
repository_patterns.yaml   Editable regex patterns for repository detection
config.yaml                Runtime configuration
country_profiles/          Per-country YAML profiles (armenia, estonia, georgia, …)
tests/
├── test_affiliation.py    Unit tests for affiliation classifier
├── test_repositories.py   Unit tests for repository extraction
├── test_integration.py    Integration tests using fixture PMIDs
└── fixtures/
    └── fixture_pmids.json Hand-curated PMIDs for integration tests
```
