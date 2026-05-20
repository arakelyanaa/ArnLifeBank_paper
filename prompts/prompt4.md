Implement extraction of dataset/repository/database references from PubMed metadata, PMC XML full text, and supplementary-material metadata.

Core idea:
For each validated Armenia-country article, detect references to deposited datasets or raw data in repositories/databases. We need both article-level evidence and aggregate repository counts.

Extraction sources:
1. PubMed XML:
   - DataBankList
   - SecondarySourceID / SI fields if present
   - Article IDs and DOI
2. PMC/JATS XML full text:
   - data availability statements
   - supplementary-material tags
   - ext-link tags
   - related-object tags
   - methods, acknowledgements, references, footnotes
   - tables or captions where dataset accessions may appear
3. Europe PMC annotations API can be optionally used as a cross-check for database accessions if feasible.
4. NCBI ELink from PMC to other NCBI databases can be optionally used to find linked NCBI records referenced by PMC articles.

Repositories/databases to detect initially:
- Zenodo
- Figshare
- Dryad
- OSF
- Mendeley Data
- Dataverse
- GEO
- SRA
- GenBank / Nucleotide / ENA / DDBJ
- BioProject
- BioSample
- dbGaP
- ArrayExpress / Expression Atlas
- PRIDE / ProteomeXchange
- MetaboLights
- EGA
- PDB
- ClinVar
- dbSNP
- Sequence Read Archive / ENA Run / DRA

For each detection, capture:
- pmid
- pmcid
- doi
- repository/database normalized name
- identifier/accession/DOI/URL
- identifier_type
- evidence_source: pubmed_metadata, pmc_xml, supplementary_metadata, europepmc_annotation, ncbi_elink
- evidence_section if available
- short evidence_snippet
- confidence: high / medium / low

Important:
- Avoid counting generic mentions like “data available upon request” as repository submissions.
- Count only explicit repository/database identifiers, DOIs, accession numbers, or URLs.
- Normalize repository names. For example, “Gene Expression Omnibus” and “GEO” should both be GEO.
- Deduplicate the same identifier within the same article.
- Keep raw evidence for manual checking.
- Implement conservative regex patterns and tests. Make the patterns easy to edit in a YAML/JSON config file.

Outputs:
1. article_repository_links.csv: one row per unique article-repository-identifier.
2. articles.csv: add boolean and count columns:
   - has_any_data_reference
   - n_repository_links
   - repositories_detected
   - n_raw_data_accessions
   - n_general_repository_dois
3. extraction_diagnostics.csv: false-positive-prone matches and low-confidence evidence for review.

Add tests with example strings:
- “Raw sequencing data were deposited in SRA under accession PRJNAxxxxxx.”
- “GEO accession GSE123456.”
- “GenBank accession numbers OP123456–OP123460.”
- “Data are available at Zenodo doi:10.5281/zenodo.xxxxx.”
- “Armenia, Colombia” should not affect repository extraction but should remain excluded by affiliation logic.
