Now improve validation and reproducibility.

Tasks:
1. Add unit tests and integration tests.
2. Create a small fixture dataset of 10–20 PMIDs covering:
   - true Armenia country affiliations
   - Armenia, Colombia false positives
   - ambiguous affiliations
   - articles with PMCID
   - OA articles with known repository/database accessions
3. Add manual-review outputs:
   - uncertain_affiliations_for_review.csv
   - low_confidence_repository_matches.csv
4. Add a README section explaining:
   - why PubMed query counts alone are insufficient
   - how affiliations are classified
   - why OA/full-text analysis is limited to machine-readable legally accessible full text
   - how repository/database references are extracted
   - how to rerun the pipeline
   - known limitations and likely false negatives
5. Add requirements.txt or pyproject.toml updates.
6. Make the pipeline deterministic:
   - fixed config
   - versioned regex patterns
   - cached API responses
   - run metadata
7. Run tests and a sample pipeline execution.
8. Show final output file examples and a short interpretation of counts.

Do not run the full dataset until the sample mode passes.
