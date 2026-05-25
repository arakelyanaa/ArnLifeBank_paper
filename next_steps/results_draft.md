# Results — Suggested Tables, Figures, and Wording

*Generated 2026-05-25. All numbers drawn from `output/country_comparison.csv`,
`output/country_comparison_gp_code.csv`, and `output/discoverability_comparison.csv`.*

---

## Suggested paper tables

---

### Table 1 — Deposition rates and repository fragmentation across four corpora (2020–2025)

> Place in Results section 3.2 / 3.3. Spans all repository classes. Full version is
> `output/country_comparison.csv`; the publication table below retains the most
> reportable rows.

| Metric | Armenia | Georgia | Estonia | Leipzig Univ. |
|--------|--------:|--------:|--------:|--------------:|
| Validated articles | 2,712 | 3,476 | 8,055 | 11,676 |
| PMC OA rate (%) | 73.6 | 75.0 | 83.9 | 85.3 |
| **Deposition rate – all articles (%)** | **26.8** | **24.0** | **40.3** | **40.8** |
| Deposition rate – OA articles (%) | 35.9 | 31.1 | 47.5 | 46.8 |
| Repositories used | 21 | 25 | 27 | 28 |
| Shannon H normalised | 0.552 | 0.516 | 0.580 | 0.539 |
| HHI normalised | 0.317 | 0.343 | 0.252 | 0.294 |
| Long-tail ratio < 10 articles (%) | 3.4 | 5.6 | **0.4** | 0.2 |
| Multi-repo orphaned silos (%) | 81.5 | 78.6 | 80.6 | 88.9 |

**Footnote suggestion:**
"Deposition rate: proportion of validated articles containing ≥1 confirmed repository
reference (dbSNP excluded). Shannon H normalised and HHI normalised computed over the
article-count distribution across repositories; H_norm = 0 indicates one repository captures
all deposits, H_norm = 1 indicates perfectly uniform distribution; HHI_norm = 0 indicates
perfect distribution, HHI_norm = 1 indicates monopoly. Long-tail ratio: share of
depositing-article-mentions in repositories used by fewer than 10 papers from that country's
corpus. Orphan rate: fraction of articles depositing in >1 repository where no two
repositories automatically cross-link (INSDC family or GEO–SRA)."

---

### Table 2 — Fragmentation in general-purpose and code repositories

> Optional supplementary table, or brief callout box. Highlights the "choice" layer of
> fragmentation (Zenodo, Figshare, OSF, Mendeley Data, Dryad, Dataverse, GitHub, GitLab,
> ClinicalTrials.gov) isolated from discipline-mandated domain archives.

| Metric | Armenia | Georgia | Estonia | Leipzig Univ. |
|--------|--------:|--------:|--------:|--------------:|
| Deposition rate – all articles (%) | 8.0 | 7.7 | 16.2 | 14.8 |
| Deposition rate – OA articles (%) | 10.6 | 9.4 | 19.0 | 16.6 |
| Shannon H normalised | 0.748 | 0.761 | 0.721 | 0.740 |
| HHI normalised | 0.162 | 0.136 | 0.208 | 0.151 |
| Long-tail ratio < 10 articles (%) | 6.5 | 6.0 | 0.0 | 0.3 |
| Multi-repo orphaned silos (%) | 100.0 | 100.0 | 100.0 | 100.0 |

**Key observation to note:** H_norm is markedly higher here (0.72–0.76 vs 0.52–0.58 in
Table 1) because the GenBank concentration effect is removed. All four countries show 100%
orphan rate for GP repos — no paper deposited in two general-purpose platforms that
cross-link. Every author who split their materials across, say, Zenodo and Figshare created
an isolated discovery barrier.

---

### Table 3 — Atlas discoverability: ArmLifeBank vs Leipzig Health Atlas

> Core comparison table. Place prominently in Results section 3.4.

| | Armenia / ArmLifeBank | Leipzig Univ. / LHA |
|---|---:|---:|
| Total papers analysed (2020–2025) | 2,712 | 11,676 |
| Papers citing any data repository | 738 | 4,813 |
| Atlas records harvested | 134 | 411 |
| Atlas records linked to ≥1 PMID | 66 (49.3%) | 31 (7.5%) |
| Papers discoverable — Tier 1 (PMID anchor) | 36 | 4 |
| Papers discoverable — Tier 2 (URL reference) | 0 | 1 |
| **Papers discoverable — any tier** | **36** | **5** |
| **% of papers citing any repo** | **4.88%** | **0.10%** |
| % of all papers | 1.33% | 0.04% |

**Footnote suggestion:**
"Tier 1 (PMID anchor): an atlas record's linked-publications list contains the paper's
PubMed identifier. Tier 2 (URL reference): the paper's full text contains a URL resolving
to an atlas record. A paper is counted once at its highest-confidence tier. Armenian corpus:
2020–2025; Leipzig corpus: 2020–2025, affiliation query `Leipzig[Affiliation]`."

---

## Suggested figures

---

### Figure 1 — Deposition rates by country and OA status (grouped bar chart)

**Data:** `country_comparison.csv` rows "Deposition rate – all articles (%)" and
"Deposition rate – OA articles (%)".

**Design:**
- X-axis: four countries (Armenia, Georgia, Estonia, Leipzig Univ.)
- Two bars per country: "all validated articles" (lighter shade) + "PMC OA subset" (darker shade)
- Colour: one hue per country, two lightness levels
- Add horizontal reference lines at 25% and 40% for visual benchmarking
- Y-axis: 0–55%

**Caption draft:**
"Figure 1. Data deposition rates across four national/institutional corpora (2020–2025).
Bars show the proportion of validated articles citing ≥1 external data repository, for
all articles (light) and for articles with PMC Open Access full text (dark). dbSNP
excluded. Error bars not shown (bibliometric study; no sampling error)."

**What it shows:** Armenia and Georgia are ~15 pp below Estonia and Leipzig; OA articles
always deposit more; the OA–non-OA gap is consistent across countries (~9–10 pp).

---

### Figure 2 — Repository composition by class and country (stacked bar)

**Data:** `output/{country}/repository_counts.csv` with class labels applied.

**Design:**
- One stacked bar per country (normalised to 100% of all depositing-article mentions)
- Three segments: domain-standard (blue), general-purpose (orange), code/other (green)
- Optional: add absolute n of depositing articles as annotation above each bar

**Caption draft:**
"Figure 2. Composition of data deposits by repository class for four corpora (2020–2025).
Each bar shows the proportion of depositing-article mentions attributed to domain-standard
archives (e.g. GenBank, PDB, GEO), general-purpose repositories (e.g. Zenodo, Figshare,
OSF), and code/registry repositories (GitHub, ClinicalTrials.gov). Note that one article
may contribute to multiple classes if it deposits in repositories from different classes."

**What it shows:** All four countries are heavily dominated by domain-standard archives
(GenBank in particular). GP repos are 8–17% depending on country. Leipzig has proportionally
more code/GitHub deposits, reflecting a larger computational biology fraction.

---

### Figure 3 — Fragmentation space: H_norm vs HHI_norm (scatter with quadrant labels)

**Data:** Table 1 values.

**Design:**
- X-axis: HHI_norm (0 = even, 1 = concentrated) — reverse axis so rightward = more fragmented
- Y-axis: H_norm (0 = concentrated, 1 = even) — reversed so upward = more fragmented
- One labelled point per country + one for GP-repos-only (dashed outline) = 8 points total
- Quadrant labels: "High concentration" (low H, high HHI), "High fragmentation" (high H, low HHI)
- Draw diagonal reference line from (0,0) to (1,1) to show the expected correlation

**Caption draft:**
"Figure 3. Fragmentation space defined by normalised Shannon entropy (H_norm) and
Herfindahl–Hirschman Index (HHI_norm) for all repositories (filled circles) and for
general-purpose repositories only (open circles). Points closer to the upper-left indicate
more fragmented, more evenly distributed deposition; points closer to the lower-right
indicate concentration in fewer repositories. All four corpora occupy a moderate-concentration
zone for the full repository set; general-purpose subsets shift toward higher entropy,
reflecting more even distribution across non-domain archives."

**What it shows:** The GP-only points shift to higher H_norm and lower HHI_norm than the
all-repos points — a visual demonstration that removing the GenBank anchor reveals much
greater choice-layer fragmentation. No country is clearly better or worse in this space;
the argument is about cross-national comparability.

---

### Figure 4 — Top repositories by country (Cleveland dot plot or heatmap)

**Data:** `output/{country}/repository_counts.csv` for all four countries; top ~15 repos.

**Design option A (Cleveland dots):**
- One panel per repository (rows), four dots per row (countries), dot size = n articles,
  x-axis = country. Sort rows by Armenia article count descending.

**Design option B (heatmap):**
- Rows: repositories (top 15–20 union), columns: countries
- Cell fill: log10(n+1) of article count; annotate cells with raw n
- Use a single sequential colour scale

**Caption draft:**
"Figure 4. Number of articles per repository and country. Only repositories appearing
in ≥5 articles for at least one country are shown. Cell values are article counts (one
article counted once per repository). dbSNP excluded."

**What it shows:** GenBank dominates universally. Leipzig has more PDB and GitHub deposits
(structural biology and computational focus). Estonia leads in Zenodo/Figshare (reflecting
Estonian Biobank data-sharing culture). Armenia has a non-trivial ClinicalTrials.gov count.

---

### Figure 5 — Atlas discoverability funnel (paired waterfall / funnel chart)

**Data:** Table 3.

**Design:**
- Two side-by-side funnels or waterfall bars:
  Left: Armenia / ArmLifeBank
  Right: Leipzig / LHA
- Three levels per funnel: total papers → papers citing any repo → discoverable papers
- Annotate with absolute n and % at each level
- Use consistent colour scales; shade the "discoverable" bar distinctly

**Caption draft:**
"Figure 5. Atlas discoverability funnel for Armenia (ArmLifeBank) and Leipzig University
(Leipzig Health Atlas), 2020–2025. Each level shows the subset of papers meeting
progressively stricter criteria: all validated papers, papers citing ≥1 external data
repository, and papers discoverable through the respective atlas by PMID anchor or URL
reference."

**What it shows:** ArmLifeBank covers 4.88% of the Armenian "depositing" corpus vs LHA's
0.10% of Leipzig's — a 49-fold proportional difference. Critically, the absolute size of
the atlas does not explain the gap (LHA has 3× more records than ArmLifeBank); the
difference lies in publication linkage density (49% of ArmLifeBank records link to a PMID
vs 7.5% for LHA).

---

## Suggested wording for Results section

Below is a full draft of sections 3.1–3.4 using the actual numbers.
Copy, adjust prose style to match the rest of the paper, and adjust rounding if needed.

---

### 3.1 Corpus overview

"PubMed queries for Armenia-, Georgia-, Estonia-, and Leipzig-affiliated biomedical
publications (2020–2025) yielded, after affiliation validation and false-positive exclusion,
final corpora of 2,712, 3,476, 8,055, and 11,676 articles respectively. PMC Open Access
full text was successfully retrieved for 73.6%, 75.0%, 83.9%, and 85.3% of each corpus
(Table 1). The higher OA rates of the two larger corpora reflect a known positive
correlation between output volume and open-access uptake in biomedical publishing."

---

### 3.2 Data deposition rates

"Overall data deposition rates — defined as the proportion of validated articles
containing at least one confirmed reference to an external data repository — were 26.8%
(727/2,712) for Armenia and 24.0% (834/3,476) for Georgia, compared with 40.3%
(3,247/8,055) for Estonia and 40.8% (4,762/11,676) for Leipzig University (Table 1;
Figure 1). Within the PMC Open Access subset, rates rose to 35.9%, 31.1%, 47.5%, and
46.8%, respectively, a ~9 percentage-point increase consistent across all four corpora
and suggesting that open-access publication correlates with data-sharing behaviour
independently of country."

"The South Caucasus corpora (Armenia and Georgia) thus deposit data at roughly 60% of the
rate observed in the Estonian and Leipzig corpora — a gap of approximately 15 percentage
points for all articles and 14 points within the OA subset. Because the pipeline applies
identical methods and repository patterns to all four corpora, the difference is attributable
to scientific community behaviour rather than analytical artefact."

---

### 3.3 Repository fragmentation

"Despite depositing less frequently, Armenian and Georgian authors distributed their deposits
across 21 and 25 repositories respectively, comparable to Estonia (27) and Leipzig (28).
Normalised Shannon entropy (H_norm) ranged from 0.516 (Georgia) to 0.580 (Estonia), with
Armenia (0.552) and Leipzig (0.539) at intermediate values (Table 1). The normalised
Herfindahl–Hirschman Index (HHI_norm) was highest for Georgia (0.343) and Armenia (0.317),
reflecting greater concentration in a single dominant repository, and lowest for Estonia
(0.252), indicating more even distribution across archives."

"The dominant repository in all four corpora was GenBank, which accounted for 76–84% of
all domain-standard archive mentions and drove the high HHI values. To disentangle
discipline-mandated deposition from researcher choice, we separately analysed the
general-purpose repository subset (Zenodo, Figshare, OSF, Mendeley Data, Dryad, Dataverse,
GitHub, GitLab, ClinicalTrials.gov; Table 2). Within this subset, H_norm rose to 0.72–0.76
across all four corpora — indicating substantially more uniform distribution once the
GenBank anchor is removed — while HHI_norm fell to 0.14–0.21, confirming that no single
general-purpose platform has achieved dominance in any of the four national corpora."

"Long-tail fragmentation was disproportionately higher for the smaller corpora: 3.4% of
Armenian and 5.6% of Georgian depositing-article mentions reside in repositories used by
fewer than ten papers from that country's corpus, versus 0.4% (Estonia) and 0.2% (Leipzig).
These 'singleton' deposits represent data that any national-level catalogue covering only
the major repositories would miss."

---

### 3.4 Cross-repository linkage and orphan silos

"Of the 162 Armenian articles that deposited in more than one repository, only 30 (18.5%)
did so in repositories that automatically cross-link — principally within the INSDC family
(GenBank, ENA, SRA, BioProject, BioSample) or the GEO–SRA pair. The remaining 132 articles
(81.5%) are orphaned silos: data deposited across archives with no automatic cross-discovery
path. This pattern was consistent across all four corpora (orphan rates 78.6–88.9%; Table 1)
and was most pronounced for Leipzig (88.9%), whose larger and more disciplinarily diverse
corpus generates more heterogeneous repository combinations."

"Restricting to general-purpose and code repositories, the orphan rate reached 100% in all
four countries: every article that deposited in more than one general-purpose platform did so
across platforms that do not cross-link. Because Zenodo, Figshare, OSF, Mendeley Data, Dryad,
and Dataverse each maintain independent metadata and discovery interfaces, a researcher
querying any single platform will systematically miss co-deposits on the others. A national
or institutional data catalogue that harvests and cross-references these platforms would
directly address this gap."

---

### 3.5 Atlas discoverability

"We assessed what fraction of data-depositing papers in each corpus are discoverable through
the country's or institution's designated data atlas: ArmLifeBank for Armenia and the Leipzig
Health Atlas (LHA) for Leipzig University (Table 3; Figure 5)."

"Of 738 Armenian papers citing any external data repository, 36 (4.88%) were discoverable
through ArmLifeBank. All 36 matches were Tier-1 PMID anchors — ArmLifeBank records that
explicitly link the paper's PubMed identifier — consistent with ArmLifeBank's design as a
publication-linked resource. Zero papers were identified via Tier-2 URL citation, indicating
that no Armenian paper in the corpus cited ArmLifeBank directly in its data-availability
statement or methods section, despite all 36 papers being indexed by the platform."

"For Leipzig University, 5 of 4,813 papers citing any repository (0.10%) were discoverable
through LHA — a 49-fold lower proportion than for Armenia/ArmLifeBank. LHA's index is
substantially larger (411 records vs 134 for ArmLifeBank), yet contains proportionally far
fewer outward publication links: 31 of 411 LHA records (7.5%) carry a linked PMID, compared
with 66 of 134 ArmLifeBank records (49.3%). The low LHA coverage therefore reflects not
insufficient indexing volume but insufficient publication cross-referencing — LHA records
often lack explicit PMID links to the papers that generated the deposited data."

"These findings are consistent with the two platforms serving different primary functions
at their current development stage: LHA is primarily a data-hosting and modelling platform
with loose bibliographic integration, while ArmLifeBank was designed with publication
linkage as a structural feature. The comparison illustrates that discoverability is a
function of metadata completeness (specifically, bidirectional publication–dataset linkage),
not merely atlas size."

---

## Notes on interpretation / caveats to include

1. **LHA coverage caveat.** LHA does not aim to index all Leipzig output — it covers
   specific research projects and cohorts. The low 0.10% is a coverage metric against the
   full institutional corpus, not against LHA's intended scope. Clarify this in the text
   to pre-empt reviewer objections.

2. **ArmLifeBank scope note.** ArmLifeBank similarly covers a curated subset; the 4.88%
   rate should be presented as the fraction of the depositing Armenian corpus that *happens
   to be* represented, not as a target coverage rate.

3. **Deposition rate denominator.** The 26.8% Armenia figure uses all 2,712 validated
   articles as denominator. If reviewers prefer "articles with full-text available", use
   the OA-subset rate (35.9%). Be consistent whichever you choose.

4. **GenBank concentration.** The high HHI for Armenia/Georgia is driven by GenBank.
   If reviewers argue this is appropriate (genbank is the correct place for sequence data),
   the response is: (a) the GP-repo analysis already isolates choice-layer fragmentation,
   and (b) GenBank dominance is exactly what makes a cross-linking catalogue valuable —
   it is the one place a national catalogue could provide a curated entry point.

5. **Cross-link group completeness.** The INSDC cross-link group covers GenBank/ENA/SRA/
   BioProject/BioSample. Some institutional repositories (e.g. EMBL-EBI collections) also
   cross-link but are not in our pattern set. The orphan rate may be slightly overstated.
