Add aggregation and reporting.

Required tables:
1. articles.csv:
   One row per validated Armenia-country PubMed article, with bibliographic metadata, affiliation validation status, OA/full-text status, and data-reference summary.

2. article_repository_links.csv:
   One row per detected repository/database identifier per article.

3. repository_counts.csv:
   Columns:
   - repository
   - repository_category: general_repository / nucleotide_sequence / transcriptomics / raw_reads / proteomics / metabolomics / variation / structure / other
   - n_articles_with_repository
   - n_unique_identifiers
   - n_total_mentions
   - example_identifiers
   - evidence_sources_used
   - notes

4. yearly_repository_counts.csv:
   Columns:
   - publication_year
   - repository
   - n_articles
   - n_identifiers

5. run_summary.json:
   Include:
   - run date/time
   - PubMed query
   - number of candidate PubMed hits
   - number of validated Armenia-country articles
   - number excluded as Colombia/other
   - number uncertain
   - number with PMCID
   - number with OA full text checked
   - number with at least one repository/database reference
   - counts by repository
   - limitations

Add a CLI command such as:
python armlifebank_pubmed_data_audit.py --start-year 2000 --end-year 2025 --mode strict --sample-size 100

Also add:
- --resume
- --force-refresh-cache
- --output-dir
- --log-level
- --config

Generate a Markdown report file summarizing the run, with tables and caveats.
