# Claude Code Instructions — LHA Discoverability Analysis

## Context

This is an extension to the **ArmLifeBank pipeline**. It produces one concrete, quotable finding for the paper:

> "Of all data products referenced in Leipzig-affiliated biomedical publications (2020–2025), X% are discoverable through the Leipzig Health Atlas (LHA)."

This is a **coverage analysis**, not a causal analysis. We are measuring whether a dataset would be findable to a researcher entering the LHA portal, not whether LHA caused better deposition behaviour.

The analysis must match **three categories of LHA content**:

1. **Externally identified datasets** referenced by LHA via a DOI, repository accession, or external URL (e.g., LHA points out to a Zenodo DOI or a GenBank accession).
2. **LHA-internal datasets** physically hosted by LHA itself, identified by `health-atlas.de/lha/...` permalinks. LHA provides and associates unique permanent identifiers for each dataset and model, and many datasets exist only inside LHA.
3. **Publication-anchored discovery** — if LHA's metadata for a record links to a PMID in our corpus, every data product of that publication counts as discoverable via LHA (since a researcher finding the LHA record can navigate to the publication and thence to its data).

**Do not collapse these into a single DOI-only check.** A DOI-only check will undercount LHA's actual discovery surface by a large factor.

**I contitionally names the module file names. If they cause conflicts with already present files, suggest alternative names.**

---

## Inputs

The Leipzig data already exists in outputs/leipzig_university folder.
Inform and confirm with me about files and columns you want to use for the analysis. 
---

## File layout
Instect folder and file structure, report and confirm what files you plan to use for the analysis.
Do not modify any unless confirmed with me.

---

## Configuration — `config/lha.yaml`
Inspect proposed configuration file contents and suggest revisions, if needed.

```yaml
lha:
  base_url: "https://www.health-atlas.de"
  harvest:
    # Prefer in this order. Implement all three; pick whichever returns data.
    methods:
      - dcat_endpoint     # check /dcat, /catalog.ttl, /api/catalog
      - rest_api          # check /api/v1/, /api/datasets
      - sitemap_scrape    # /sitemap.xml then fetch each /lha/<id> page
    rate_limit_rps: 1     # one request per second, hard cap
    user_agent: "ArmLifeBank-Research-Bot/1.0 (contact: <FILL IN>)"
    respect_robots_txt: true
  match:
    enable_publication_anchored: true   # tier 3 matching on/off for sensitivity analysis
    fuzzy_title_threshold: 0.92         # only used if all hard matches fail
comparators:
  - country: Armenia
    role: target
  - country: Leipzig
    role: lha_served
  # Optional control — uncomment to add a German city without an LHA equivalent
  # - country: Heidelberg
  #   role: german_control_no_hub
```

The country list drives everything. **Do not hardcode "Armenia" or "Leipzig" inside Python.**

---

## Module 1 — `harvest.py`

**Goal.** Build a local index of every LHA record with enough metadata to enable matching.

**Discovery order.** Before writing the harvester, probe LHA for the best access method:

1. Check for a DCAT or DCAT-AP endpoint (`/dcat`, `/catalog.ttl`, `/api/dcat`). LHA participates in NFDI4Health, which standardizes on HealthDCAT-AP, so a DCAT export may exist.
2. Check for a JSON REST API (`/api/v1/datasets`, `/api/catalog`).
3. Fall back to harvesting `/sitemap.xml` and parsing each `/lha/<id>` record page.

Log which method succeeded. Persist raw responses under `cache/lha/raw/<lha_id>.json` (or `.ttl` / `.html` depending on method). **Never re-fetch a cached record.**

**Per-record fields to extract into:**

- `lha_id` — the `lha/<id>` permalink fragment (canonical internal identifier)
- `lha_url` — full URL
- `title`
- `record_type` — `dataset` | `model` | `phenotype` | `tool` | `other`
- `is_lha_hosted` (bool) — true if the dataset itself sits inside LHA (no external repository link)
- `external_dois` (list[str]) — every DOI mentioned in the record
- `external_accessions` (list[{repository: str, accession: str}]) — every repository accession mentioned
- `external_urls` (list[str]) — every other outbound URL
- `linked_pmids` (list[str]) — every PMID mentioned
- `authors` (list[str])
- `created_date`, `modified_date`
- `raw_path` — pointer to the cached raw response

**Constraints.**

- Hard rate limit: 1 request/sec. Respect `robots.txt`.
- Set the `User-Agent` from config; never use a generic one.
- On any HTTP error, log accession + status and continue. Do not crash the harvest on a single bad record.
- Re-runs must be idempotent: skip records already present in `cache/lha/raw/` unless `--refresh` is passed.

---

## Module 2 — `normalize.py`

**Goal.** Bring every identifier into a canonical form so matching is exact-string after normalization. No fuzzy matching here.

Implement these normalizers, each as a pure function with unit tests:

- `normalize_doi(s) -> str | None`. Strip `https://doi.org/`, `doi:`, `https://dx.doi.org/`, leading/trailing whitespace; lowercase. Return `None` if the result isn't a syntactically valid DOI (`10.\d+/...`).
- `normalize_url(s) -> str | None`. Lowercase host, strip `www.`, strip default ports, strip trailing `/`, drop `utm_*` query params, sort remaining query params, drop URL fragments. Keep path case as-is (paths can be case-sensitive).
- `normalize_accession(repository, s) -> str | None`. Per-repository rules: GenBank/RefSeq strip version suffix (`MK123456.1` → `MK123456`); GEO uppercase; PDB uppercase; ClinicalTrials.gov accept `NCT\d{8}`; etc. Document each rule in the function docstring.
- `extract_doi_from_url(url) -> str | None`. If a URL is a DOI redirector (zenodo.org/record, figshare.com/articles, osf.io), pull out the DOI when possible.

**Critical:** every accession must pass through these normalizers before any comparison. Mixing normalized and raw forms in the matcher is the most likely source of false negatives.

---

## Module 3 — `match.py`

**Goal.** For each `(pmid, accession), determine whether it is discoverable via LHA. Output one row per pair with the match tier and the matching LHA record.

**Three-tier matching, evaluated in order. Stop at the first hit per pair.**

### Tier 1 — Hard identifier match

A `(pmid, accession)` pair is **Tier-1 discoverable** if either:

- `normalize_doi(accession)` matches any entry in some LHA record's `external_dois`, OR
- `normalize_accession(repository, accession)` matches any entry in some LHA record's `external_accessions` (with same repository), OR
- `normalize_url(accession)` matches any entry in some LHA record's `external_urls`, OR
- The accession resolves to an LHA-internal permalink — i.e., `normalize_url(accession)` host is `health-atlas.de` and the path contains `/lha/<id>` matching a known `lha_id` in the index.

The last clause is the **"internally stored datasets"** case the user specifically asked to cover. A publication that says "data are available at https://www.health-atlas.de/lha/abc123" counts here, even though there is no DOI involved.

### Tier 2 — URL substring match (cautious)

If Tier 1 misses but the accession URL contains the LHA record's `lha_id` as a path component (e.g., shortened or paraphrased LHA links), record a Tier-2 match. Log these for manual review; do not silently treat them as confirmed.

### Tier 3 — Publication-anchored discovery

If Tier 1 and Tier 2 miss but **the article's PMID appears in some LHA record's `linked_pmids`**, mark the pair as Tier-3 discoverable. The reasoning: a researcher entering LHA can find that publication and from there reach all of its data products, including ones LHA doesn't directly index.

Tier 3 is generous. Report all metrics **twice**: once including Tier 3, once excluding it. Treat the Tier-1+2 number as the conservative headline.

### Output schema

One row per `(pmid, repository, accession)` pair from `repo_links.parquet`:

- `pmid`, `repository`, `accession_raw`, `accession_normalized`
- `match_tier` — `1` | `2` | `3` | `null` (no match)
- `match_method` — `doi` | `accession` | `external_url` | `lha_internal_url` | `url_substring` | `pmid_link`
- `matched_lha_id` — the LHA record that produced the match, or `null`
- `matched_lha_url`

**Reject and refuse to count** any pair where `accession_normalized` is `null` — log these for diagnosis. They are extraction-quality problems, not LHA coverage problems, and should not inflate or deflate the discoverability rate.

---

## Module 4 — `report.py`

**Goal.** Produce the headline table for the paper.

For each country in `config/lha.yaml`, compute:

- `n_articles_with_data` — articles with ≥1 valid (non-null normalized) repository link
- `n_links_total` — total valid links
- `n_articles_discoverable_via_lha_conservative` — articles with ≥1 Tier-1 or Tier-2 match
- `n_articles_discoverable_via_lha_inclusive` — articles with ≥1 match of any tier
- `n_links_discoverable_conservative` — links with Tier-1 or Tier-2 match
- `n_links_discoverable_inclusive` — links with any-tier match
- `pct_articles_conservative` = articles_discoverable_conservative / articles_with_data
- `pct_articles_inclusive` — same with inclusive numerator
- `pct_links_conservative`, `pct_links_inclusive`
- Per-tier breakdown: how many matches via DOI, accession, URL, lha_internal_url, pmid_link
- Per-repository-class breakdown (using the repo class mapping from the earlier v2 work, if available — otherwise skip)

Output `outputs/v2/lha_discoverability/<country>.json` per country and `outputs/v2/lha_discoverability/summary.md` with a Markdown table comparing all countries side-by-side.

The `summary.md` table should have rows: Armenia, Leipzig, (optional control), and columns: `% articles discoverable (conservative)`, `% articles discoverable (inclusive)`, `% links discoverable (conservative)`, `% links discoverable (inclusive)`. This is the table that will appear in the paper.

---

## Expected results — sanity checks

These are predictions, not requirements. If actual results diverge wildly, **stop and report — do not silently proceed.**
- Leipzig conservative discoverability: expected at least 5–20% based on LHA's published scope. Anything close to 0% suggests the LHA harvest is incomplete or the normalizers are misaligned.
- Tier-3 inclusive numbers should be noticeably higher than conservative for Leipzig but only marginally higher for Armenia (since few Armenian PMIDs are referenced in LHA).

If Leipzig comes back at exactly 0%, treat it as a debugging signal first and a finding second.

---

## Hard constraints

- Do **not** modify v1 pipeline code or rerun PubMed fetches except for Leipzig.
- Do **not** scrape LHA without rate limiting and a real `User-Agent`.
- Do **not** treat fuzzy title matches as confirmed discoverability — they are diagnostic only.
- Do **not** silently fail on harvest errors. Log every skipped record with its URL and HTTP status.
- Every external HTTP call must be cached on disk and never repeated for the same key.
- Random seeds (used in any sampling) must be recorded in output JSONs.
- All thresholds (rate limits, fuzzy cutoffs, tier toggles) must come from `config/lha.yaml`, not be hardcoded.

---

## Implementation order — implement and review one at a time

Stop after each step. Show file diffs, test results, and a one-paragraph summary before moving on.

1. `config/lha.yaml` + the empty module skeletons.
2. `normalize.py` + unit tests with handwritten expected values for: DOIs in 4 different prefix styles, URLs with `www`, trailing slashes, query params, fragments, and LHA permalinks; GenBank accessions with and without versions; GEO and PDB accessions.
3. `harvest.py` — first run with `--limit 50` and report which discovery method worked and what the parsed records look like. Do **not** harvest the full catalog until the parser is verified on 50 records.
4. Full LHA harvest. Report total records, breakdown by `record_type`, and counts of records with non-empty `external_dois`, `external_accessions`, `external_urls`, `linked_pmids`.
5. Leipzig v1 pipeline run. Verify per-year candidate counts are distinct from Armenia's. Report the counts in a table.
6. `match.py` + unit tests on a small synthetic dataset where every tier produces a hand-computed expected count.
7. Full matching run on Armenia and Leipzig. Report the sanity-check numbers above.
8. `report.py` and `summary.md`. Present the final table.

At step 7, if Armenia ≠ ~0% or Leipzig ≈ 0%, do not proceed to step 8 — investigate and report what you find first.
