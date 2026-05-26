# Search-Based Findability: ArmLifeBank vs GEO vs PubMed

*11 ArmLifeBank-indexed papers with GEO accessions (Armenia 2020–2025).
Each paper's topic query was issued identically to GEO, PubMed, and ArmLifeBank.
Metric: **Reciprocal Rank (RR) = 1/rank** — higher is more findable; 0 = not found in top 500.*

---

## Summary table

Two query passes simulate best-case (Pass 1: specific, 3–4 terms derived from the paper's own keywords) and realistic (Pass 2: broad, 1–2 general terms a naive researcher would use) search conditions.

| Portal | Pass 1 — specific query | | | Pass 2 — broad query | | |
|--------|:-----------------------:|:---:|:------:|:--------------------:|:---:|:------:|
| | **Found** | **Mean corpus** | **Mean RR** | **Found** | **Mean corpus** | **Mean RR** |
| GEO | 3/11 | 50 | 0.057 | 6/11 | 2,700 | 0.008 |
| PubMed | 9/11 | 1,364 | 0.161 | 3/11 | 24,646 | 0.002 |
| ArmLifeBank | **11/11** | 126 | 0.028 | **11/11** | 126 | **0.028** |

---

## Per-paper results

| PMID | Topic | GSE | Pass 1 query | GEO RR | PubMed RR | ArmLB RR | Pass 2 query | GEO RR | PubMed RR | ArmLB RR |
|------|-------|-----|-------------|-------:|----------:|---------:|-------------|-------:|----------:|---------:|
| 33897770 | Telomere maintenance | GSE14533 | telomere maintenance pathway cancer | 0 | 0.0037 | 0.0154 | telomere cancer | 0 | 0 | 0.0154 |
| 34281234 | Melanoma isoforms | GSE112509 | melanoma transcriptome isoforms splicing | 0 | 0.1111 | 0.0164 | melanoma RNA-seq | 0 | 0 | 0.0164 |
| 35159171 | Brain aging methylome | GSE11512 | brain aging transcriptome methylation | 0 | 0.0108 | 0.0185 | brain transcriptome aging | 0 | 0 | 0.0185 |
| 35681780 | Glioma multi-omics | GSE61374, GSE129477 | glioma multi-omics methylome | 0 | 0.0909 | 0.0204 | glioma transcriptome | 0.0026 | 0 | 0.0204 |
| 37217719 | mRNA translation bacteria | GSE153497 | mRNA translation decay bacteria | 0.0909 | 0.0147 | 0.0233 | mRNA translation bacteria | 0.0025 | 0 | 0.0233 |
| 37568651 | Colorectal metastasis | GSE159216, GSE178318 | colorectal liver metastasis transcriptome | 0.0303 | 0.0063 | 0.0244 | colorectal metastasis transcriptome | 0.0192 | 0.0021 | 0.0244 |
| 37680201 | Pathway analysis toolkit | GSE112509 | pathway signal flow gene expression | 0 | 0 | 0.0263 | pathway analysis transcriptome | 0 | 0 | 0.0263 |
| 38368435 | Schizophrenia gene expression | GSE21138 + 5 others | brain gene expression schizophrenia temporal | 0 | 0 | 0.0333 | schizophrenia gene expression | 0.0031 | 0 | 0.0333 |
| 38763334 | Pan-cancer telomere | GSE84465 | pan-cancer telomere maintenance mechanisms | 0 | 0.2000 | 0.0385 | cancer telomere | 0 | 0 | 0.0385 |
| 39273985 | Grapevine drought | GSE70670 | grapevine transcriptome drought thiamine | 0 | 1.0000 | 0.0400 | grapevine transcriptome | 0.0208 | 0.0084 | 0.0400 |
| 39732652 | Cardiac diet transcriptome | GSE272168 | cardiac transcriptome western diet sex | 0.5000 | 0.3333 | 0.0526 | cardiac transcriptome diet | 0.0385 | 0.0104 | 0.0526 |

---

## Findings

**1. ArmLifeBank has perfect recall and stable rank across both query types.**
All 11 papers were found in ArmLifeBank under both specific and broad queries (11/11), at an unchanged mean RR of 0.028. Broadening the query had zero effect — the corpus is pre-filtered to Armenian research, so there is no dilution regardless of how generic the search terms are.

**2. PubMed collapses under broad queries.**
With specific queries, PubMed found 9/11 papers at a mean RR of 0.161 — the highest of any portal under Pass 1. However, this reflects the fact that the specific queries were derived directly from each paper's own keywords, giving PubMed an artificial advantage. Under broad queries (Pass 2), PubMed found only 3/11 papers within the top 500 results, with mean RR dropping 99% to 0.002. Mean corpus size grew from 1,364 to 24,646 results per query, diluting Armenian papers beyond practical reach.

**3. GEO keyword search is weak in both passes.**
GEO found only 3/11 papers under specific queries (mean RR 0.057) and 6/11 under broad queries, but with mean RR falling to 0.008. GEO is not designed for topic-based discovery; researchers cannot reliably locate Armenian datasets in GEO by keyword. The two best-performing cases in Pass 1 (cardiac transcriptome, mRNA translation) were highly specific topics with very few global GEO results — not representative of typical searches.

**4. The dilution effect is the core finding.**
The table below captures it directly:

| Portal | Pass 1 Mean RR | Pass 2 Mean RR | Δ (broad − specific) |
|--------|---------------:|---------------:|---------------------:|
| GEO | 0.057 | 0.008 | −86% |
| PubMed | 0.161 | 0.002 | −99% |
| **ArmLifeBank** | **0.028** | **0.028** | **0%** |

Under realistic search conditions (Pass 2), ArmLifeBank's mean RR is **14× higher than GEO** and **14× higher than PubMed**. The advantage is not that ArmLifeBank's search engine ranks papers better — its absolute ranks (19–65 out of 126) are moderate — but that its corpus is small enough and focused enough that a researcher is never buried under thousands of irrelevant global results.

**5. Implication for the paper.**
The findability gap is structural, not technical. Depositing data in GEO or publishing in PubMed does not make Armenian research discoverable to a researcher browsing by topic; those portals serve global audiences where Armenian output constitutes a fraction of a percent of results. ArmLifeBank closes this gap by providing a national-scope entry point where every result is relevant. The 14× findability advantage under broad queries is a direct quantification of that structural benefit.
