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

### Git
- Initialized local repository
- Initial commit `2015af1` (32 files, 4446 lines)
- `.gitignore` excludes: `.cache/`, `output/`, `logs/`, `NCBI_API.txt`, `output-Armenia/`, `.claude/`
- Remote push to `https://github.com/arakelyanaa/ArnLifeBank_paper.git` pending (authentication required)
