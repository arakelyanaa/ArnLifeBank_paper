# ArmLifeBank – Change Log

---

## 2026-05-20 – Initial pipeline + multi-country refactor

### Pipeline built (Stages 1–7)
- `armlifebank/config.py` – runtime config, API key loading, CLI override support
- `armlifebank/cache.py` – disk-based JSON cache keyed by PMID/PMCID
- `armlifebank/cli.py` – full argparse entry point chaining all pipeline stages
- `armlifebank/pubmed.py` – PubMed esearch + efetch with batching, caching, retries
- `armlifebank/affiliation.py` – layered affiliation classifier (Armenia/Colombia rules)
- `armlifebank/fulltext.py` – PMC OA full-text retrieval (efetch primary, BioC/EuropePMC fallback)
- `armlifebank/repositories.py` – repository/accession extraction from DataBankList, JATS XML, abstracts
- `armlifebank/reporting.py` – CSV/JSON/Markdown report generation
- `repository_patterns.yaml` – 22 repository regex patterns (editable without code changes)
- `tests/` – 70 unit + integration tests (pytest)
- `README.md` – full documentation

### Multi-country refactor (Stages 1–5)
- `country_profiles/armenia.yaml` – Armenia affiliation rules extracted from hardcoded logic
- `country_profiles/latvia.yaml` – Latvia profile (new country support)
- `armlifebank/affiliation.py` – replaced hardcoded rules with `CountryClassifier` class driven by country profile; backward-compat module-level wrappers retained
- `armlifebank/config.py` – added `load_country_profile()`, `country_code`, `country_profile` attributes; default `output_dir` is now `output/{country}/`
- `armlifebank/cli.py` – added `--country CODE` flag; country-aware labels and summary
- `armlifebank/reporting.py` – all "Armenia" hardcoded strings replaced with country name from summary dict; summary keys renamed `n_country_match` / `n_excluded`
- `config.yaml` – added `country: armenia` key
- `tests/test_affiliation.py` – added `CountryClassifier` direct API tests + Latvia smoke tests (92 tests total)
- `tests/test_integration.py` – updated `n_armenia_country` → `n_country_match`

---

## 2026-05-20 – Fragmentation analysis script

- `analysis/fragmentation.py` – standalone script computing fragmentation indices from pipeline output
  - Deposition rates (overall and within PMC-OA subset)
  - Repository classification: domain-standard / general-purpose / code-other
  - Shannon entropy and HHI (raw + normalised) over article-to-repository distribution
  - Long-tail ratio (configurable threshold, default <10 articles)
  - Article×repository bipartite graph: cross-link rate and orphan rate
  - Outputs: `fragmentation_indices.csv` + `fragmentation_report.md` in `output/{country}/`
  - dbSNP excluded from all indices by design
- Usage: `python analysis/fragmentation.py --country armenia`

**Armenia (2020–2025) results:**
- Deposition rate: 26.8% overall | 35.9% within OA
- 21 repositories analysed (dbSNP excluded)
- Shannon H_norm = 0.552 | HHI_norm = 0.317 (moderate fragmentation, GenBank-dominated)
- Long-tail ratio: 3.4% (< 10 articles threshold)
- Cross-link rate: 18.5% | Orphan rate: 81.5% (most multi-repo deposits are in isolated silos)

---

### Git
- Initialized local repository
- Initial commit `2015af1` (32 files, 4446 lines)
- `.gitignore` excludes: `.cache/`, `output/`, `logs/`, `NCBI_API.txt`, `output-Armenia/`, `.claude/`
- Remote push to `https://github.com/arakelyanaa/ArnLifeBank_paper.git` pending (authentication required)
