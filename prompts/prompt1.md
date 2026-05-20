You are helping me extend an existing Python script (pubmed_armenia_stats.py) for a bibliometric/data-sharing analysis for a paper about ArmLifeBank.

Current goal:
The existing script uses the NCBI API to search PubMed and count publications where Armenia appears in author affiliations. I want to extend it into a reproducible pipeline that:

1. Counts PubMed papers with at least one author affiliation corresponding to the country Armenia.
2. Avoids false positives where “Armenia” refers to the city Armenia in Colombia.
3. For papers with Open Access full text available through PMC/PMC OA or equivalent machine-readable sources, detects references to deposited datasets and raw data in repositories/databases such as Zenodo, Figshare, Dryad, OSF, GEO, SRA, GenBank/ENA/DDBJ, BioProject, BioSample, dbGaP, ArrayExpress, PRIDE/ProteomeXchange, MetaboLights, EGA, and similar resources.
4. Produces article-level and repository-level output tables.

Please first inspect the current repository and script. Do not rewrite everything unless necessary. Produce a short implementation plan before editing code.

Technical requirements:
- Use NCBI E-utilities responsibly with batching, retries, local caching, and rate limiting.
- Read NCBI configuration from environment variables or a config file: NCBI_EMAIL, NCBI_TOOL, optional NCBI_API_KEY.
- Use PubMed XML, not just PubMed query counts, to parse all available affiliation strings.
- Implement a strict Armenia-country affiliation validator and mark uncertain cases separately.
- Detect PMCID using PubMed XML, PMC ID Converter API, or ELink from PubMed to PMC.
- For OA papers, retrieve full text only through approved machine-readable routes such as PMC OA service, PMC BioC API, E-utilities, or Europe PMC API if appropriate.
- Cache fetched PubMed XML, PMC metadata, and OA full text locally to avoid repeated API calls.
- Produce CSV/TSV outputs and a machine-readable JSON summary.
- Add tests for affiliation classification and accession/repository detection.
- Add a README section explaining limitations.

Expected outputs:
1. articles.csv: one row per PubMed article.
2. article_repository_links.csv: one row per detected repository/database identifier per article.
3. repository_counts.csv: one row per repository/database with article counts and identifier counts.
4. run_summary.json: query, date, total PubMed hits, validated Armenia-country articles, OA articles checked, articles with data links, counts by repository.
5. logs/warnings for uncertain affiliations and failed full-text retrievals.

Start by auditing the existing script and proposing a file/module structure. Then wait for my approval before making major changes.
