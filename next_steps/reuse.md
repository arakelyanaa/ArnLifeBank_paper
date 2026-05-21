# Reuse & Citation Analysis Strategy

Implements section 4 of `fragmentation_analysis.md`.

## Scope (implemented)

**DOI-bearing datasets only.** Identifiers matching `^10\.\d{4,}/` are included;
accession-only identifiers (GenBank, SRA, PDB, GEO, BioProject) and bare URLs
(GitHub, OSF without DOI) are excluded. This covers general-purpose repositories
(Zenodo, Figshare, Dryad, Mendeley Data, Dataverse) and any domain-standard repo
that happens to surface a DOI in the links CSV.

EuropePMC accession-mention counting (the path for non-DOI identifiers) is out of
scope for this implementation but documented below for a future extension.

---

## Pipeline (`analysis/reuse.py`)

### Stage 1 — DOI extraction & normalisation

- Load `article_repository_links.csv` for all countries.
- Extract rows where `identifier` matches `^10\.\d{4,}/` regardless of the
  `identifier_type` label (the label is sometimes wrong).
- Normalise:
  - Figshare: strip `.v{N}` version suffix → `10.6084/m9.figshare.{id}`
  - All others: lowercase, strip trailing punctuation.
- Deduplicate by normalised DOI (same dataset may link from multiple articles /
  countries); keep a `country` column for aggregation.

### Stage 2 — DataCite metadata fetch

Endpoint: `GET https://api.datacite.org/dois/{doi}`

Returns per DOI:
- `data.attributes.registered` — deposition date (ISO-8601)
- `data.attributes.citationCount` — Make Data Count lifetime citation total
- `data.attributes.viewCount`, `data.attributes.downloadCount` — engagement proxies

Uses the existing `.cache/` disk cache (key prefix `datacite:`).
Rate-limited to 5 req/s (DataCite allows ~100 unauthenticated, but we stay
conservative). 4xx errors are not retried; 5xx and connection errors retry ×3
with exponential back-off.

### Stage 3 — 24-month windowed citations (optional, `--windowed` flag)

Endpoint: `GET https://api.datacite.org/events?obj-id={doi}&relation-type-id=references`

Each event has a `occurred-at` timestamp. Filter to events within 730 days of
`registered`. This is slower (~1 extra request per DOI) and DataCite event
coverage is patchy for pre-2021 deposits, so it is opt-in.

### Stage 4 — Aggregation

Group by `country × repo_class`. Compute:
- `n_datasets` — unique DOIs
- `n_with_citation_data` — DOIs where `citationCount` is not null
- `coverage_pct` — n_with_citation_data / n_datasets
- `median_citations`, `mean_citations`, `p25`, `p75`

### Outputs

```
output/reuse_citations.csv    — one row per unique DOI
output/reuse_summary.csv      — median / mean / n per country × repo_class
output/reuse_report.md        — narrative with tables
```

---

## Future extension: non-DOI accessions (EuropePMC)

For GenBank / SRA / BioProject / GEO / PDB accessions, EuropePMC's full-text
search surfaces papers that mention the accession string:

```
GET https://www.ebi.ac.uk/europepmc/webservices/rest/search
    ?query=REF:"{accession}"&resultType=lite&format=json
```

`hitCount` ≈ citation proxy. Deposition date from NCBI E-utilities (`efetch`
on the accession). Rate-limit: ~10 req/s. The existing NCBI cache can be
reused for E-utils calls; EuropePMC responses need their own cache prefix.

This path is excluded from the current implementation because:
1. ~20,000 accessions across three countries → long runtime even with caching.
2. EuropePMC text-mining mentions include self-citations and co-deposition
   mentions, making the "reuse" signal noisier than DOI-based citation counts.

---

## Limitations (to include in paper)

- Make Data Count citation data has uneven coverage; many GP-repo deposits
  registered before 2020 have `citationCount = 0` even if cited.
- `citationCount` is a lifetime total; the 24-month window (`--windowed`) is
  more meaningful but relies on DataCite event data, which is less complete.
- Self-citations are not filtered.
- Scope is limited to datasets with DOIs; accession-only deposits (the majority
  of domain-standard archives) are excluded from this analysis.
