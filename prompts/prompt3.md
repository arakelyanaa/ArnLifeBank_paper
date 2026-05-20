Add a module for identifying and retrieving machine-readable Open Access full text.

Tasks:
1. For each validated Armenia-country PubMed article, determine whether it has:
   - PMID
   - DOI
   - PMCID
   - PMC live/full-text availability
   - OA availability
2. Extract PMCID from PubMed XML when present.
3. If PMCID is missing, try PMC ID Converter API or ELink PubMed→PMC.
4. For PMCID articles, use PMC OA service to check whether the article is in the PMC Open Access subset and whether downloadable resources exist.
5. Retrieve machine-readable full text preferentially as:
   - JATS XML from OA package when available
   - BioC XML/JSON if easier and available
   - Europe PMC full text XML as fallback if accessible
6. Respect licenses and automated-retrieval rules. Do not scrape arbitrary publisher HTML/PDF pages.
7. Cache all retrieved metadata and full text by PMCID/PMID.
8. Record failures and reasons:
   - no PMCID
   - PMCID not live
   - not in OA subset
   - OA metadata found but XML unavailable
   - network/API error
9. Extend articles.csv with:
   - pmcid
   - doi
   - has_pmcid
   - is_pmc_live
   - is_pmc_oa
   - oa_license
   - full_text_source
   - full_text_cached_path
   - full_text_retrieval_status
10. Add a small test mode that processes only the first N validated articles.

Run the pipeline on a small sample, e.g. 20 articles, and report how many have PMCID and how many have OA full text.
