# Refugee Counsel Profiles

A legal engineering class project. It builds profiles of counsel who appear before the Refugee Protection Division (RPD) of the Immigration and Refugee Board, using published RPD decisions. The goal is to help refugee claimants, who often can't reach top lawyers, judge a potential representative by their track record.

## Data source

- The **A2AJ** Canadian case law connector, dataset `RPD`: 6,729 decisions dated 2002 to 2020. A2AJ got them directly from the IRB with no licensing restrictions.
- The related dataset `RLLR` (Refugee Law Lab Reporter, RPD decisions 2019 to 2024, about 1,000 documents) could extend coverage later.
- Decisions are identified by RPD file number (e.g. `TB8-03055`). The letter prefix gives the region: T = Toronto, M = Montréal, V = Vancouver/Calgary.
- Claimants' names are already anonymized as `XXXX`.

## Header fields (every decision has the same header block)

| Field | Example |
|---|---|
| RPD file number(s) | `TB8-03055` (joined claims list several) |
| Date(s) of hearing | September 14, 2020 |
| Place of hearing | Toronto, Ontario |
| Date of decision | November 18, 2020 |
| Panel (board member) | Daniel McKeown |
| Counsel for the claimant(s) | Raphael Vagliano (sometimes followed by "Barrister and Solicitor") |
| Designated representative | N/A or anonymized |
| Counsel for the Minister | N/A or a name (shows the Minister intervened) |

## Fields from the reasons

- **Outcome:** accepted, rejected, or split (joined claims can go both ways, e.g. TB8-03055 accepted 6 and rejected 4)
- **Special findings:** "no credible basis" (s. 107(2)) or "manifestly unfounded" (s. 107.1). These block an appeal to the RAD.
- Country of reference, number of claimants
- Legal basis: s. 96 (Convention ground) and/or s. 97 (person in need of protection), exclusion (Art. 1E/1F)
- Main issues decided: credibility, internal flight alternative, state protection, nexus
- Guidelines applied (e.g. the gender guideline)

## Profile metrics (draft)

1. **Experience:** number of decisions, years active, regions
2. **Acceptance rate,** shown with sample size and confidence range
3. **Acceptance rate adjusted for the expected rate:** compare against what's expected given the country of reference, the board member and the year. Those factors drive outcomes heavily.
4. **"No credible basis" / "manifestly unfounded" rate.** A strong negative signal.
5. **Opposing the Minister:** results when the Minister intervened
6. **Specialization:** countries, claim types and issues handled
7. **Joined and family claims handled**

## Running the extractor

```bash
python3 -m venv .venv && .venv/bin/pip install pandas pyarrow
curl -L -o data/raw/rpd.parquet https://huggingface.co/datasets/a2aj/canadian-case-law/resolve/main/RPD/train.parquet
.venv/bin/python src/extract.py --sample 50   # stratified sample -> data/processed/sample_50.csv
.venv/bin/python src/extract.py               # all decisions   -> data/processed/decisions.csv (~8 s)
```

The bulk Parquet file is A2AJ's approved bulk-access route. Their API terms prohibit systematic scraping.

## Extractor results (all 6,729 decisions)

| Field | Found |
|---|---|
| Panel member | 98% (header, with the signature as fallback) |
| Claimant's counsel named | 95% (3% none or self-represented, 2% not found) |
| Country of reference | 90% |
| Outcome | 98% |

- **Decision types:** 6,478 claims, 87 cessation, 78 vacation, 56 reopening, 17 abandonment, 13 reinstatement. Only *claims* should count toward acceptance rates.
- **Outcome accuracy:** where the IRB keyword line exists, the outcome comes from it. Otherwise the last decisive sentence of the conclusion is used. On 579 decisions that have keywords, the text-only method agreed with the IRB keywords 99.5% of the time.
- **Claim outcomes:** 6,040 rejected, 306 accepted, 41 split, 91 unknown.
- **Counsel:** 1,333 distinct names; 175 appear in 10 or more decisions.

**Important:** about 5% of published claims are accepted, while the RPD's real acceptance rate is far higher. The IRB mostly publishes negative decisions, so raw acceptance rates here are **not** a lawyer's real success rate. Profiles should present comparisons between counsel (same country, member and period), not absolute rates.

## Known limits

- The dataset holds only *published* decisions, a small and non-random share of all RPD decisions.
- Grant rates vary widely by board member and country. Raw acceptance rates mislead without adjustment.
- People change roles. Craig Costantino appears as counsel in 2010 and as a board member in 2019.
- The same counsel can appear under different spellings, or as a firm, consultant or clinic. Matching names needs care, and counsel may be lawyers or licensed immigration consultants.
- Present facts with context, not star ratings. Never try to re-identify claimants.
