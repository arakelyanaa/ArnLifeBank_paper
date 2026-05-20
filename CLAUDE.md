# ArmLifeBank PubMed/Data Repository Audit

This project analyzes PubMed articles with Armenia-country author affiliations and checks open-access full text for references to deposited datasets and raw data repositories.

Important requirements:
- Do not rely only on PubMed Armenia[ad] counts.
- Fetch PubMed XML and validate individual affiliation strings.
- Exclude Armenia, Colombia / Armenia, Quindío false positives.
- Use NCBI E-utilities responsibly with batching, caching, retries, and rate limiting.
- Do not scrape publisher websites.
- Prefer PMC OA, PMC BioC, ELink, ID Converter, and Europe PMC when appropriate.
- Produce reproducible CSV/JSON outputs.
- Add tests before running the full dataset.
