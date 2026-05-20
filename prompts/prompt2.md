Implement the Armenia-country affiliation validation layer.

Problem:
The current PubMed query likely uses Armenia[ad] or similar. This catches both the country Armenia and possible false positives such as “Armenia, Colombia” or affiliations located in the city Armenia in Colombia. We need high-precision classification.

Tasks:
1. Fetch PubMed XML for candidate PMIDs returned by a broad search such as Armenia[ad].
2. Parse all author affiliations from the XML, preserving PMID, author name/order if available, and raw affiliation string.
3. Implement classify_affiliation_country(raw_affiliation) returning:
   - "armenia_country"
   - "not_armenia_country"
   - "uncertain"
4. Use explicit negative rules for Colombia false positives:
   - "Armenia, Colombia"
   - "Armenia, Quindío"
   - "Quindio"
   - Colombian institutions, departments, postal/address patterns when associated with Armenia
   - country token "Colombia"
5. Use positive rules for Armenia country:
   - country token "Armenia" as final address component or country-level component
   - "Republic of Armenia"
   - Armenian cities/institutions plus Armenia, e.g. Yerevan, Gyumri, Vanadzor, Ashtarak, Institute of Molecular Biology NAS RA, Yerevan State University, Armenian institutions, .am email domains
6. Do not classify as Armenia-country merely because the word "Armenian" appears in institution names unless country evidence is present. Mark as uncertain unless strong evidence exists.
7. For each article, classify it as Armenia-country if at least one affiliation is "armenia_country".
8. Keep excluded and uncertain affiliations in separate output files:
   - affiliations_validated.csv
   - affiliations_uncertain.csv
   - affiliations_excluded_colombia.csv
9. Add unit tests covering:
   - Yerevan, Armenia
   - Republic of Armenia
   - Armenia, Colombia
   - Armenia, Quindío, Colombia
   - ambiguous “Armenian Medical Institute” without country
   - .am email domain plus Armenian institution
10. Add a command-line option for strict vs broad mode:
   - strict: only explicit country Armenia or very strong evidence
   - broad: allows Armenian city/institution + no conflicting Colombia signal

After implementation, run tests and show me the classification logic and examples.
