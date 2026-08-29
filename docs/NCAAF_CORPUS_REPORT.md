# NCAAF 2014–2024 development corpus report

Status: **Phase 5B-1 complete on 2026-08-29.** This is a source/identity/target report, not a model result or backtest. The machine-readable companion is [`reports/NCAAF_CORPUS_2014_2024.json`](reports/NCAAF_CORPUS_2014_2024.json).

## Corpus

- 24,222 year-wide games retained for context.
- 9,440 games have at least one FBS participant.
- 8,277 valid final FBS-vs-FBS games have `margin = home points - away points` and `total = home points + away points` labels.
- 15,944 games are excluded as not FBS-vs-FBS, including 1,162 FBS-vs-FCS games; one additional game is excluded as not final.
- No 2025 endpoint or score magnitude was accessed.

## Coverage

| Product | Rows | FBS-participant games | Coverage |
| --- | ---: | ---: | ---: |
| Plays | 1,695,709 | 9,367 / 9,440 | 99.23% |
| Drives | 238,898 | 9,389 / 9,440 | 99.46% |
| Team game statistics | 9,414 | 9,414 / 9,440 | 99.72% |

All FBS-participant team identities resolve through exact CFBD IDs. The 289 missing team identities are retained lower-division context, not the primary model cohort. No ambiguous exact-provider mapping remains in the model cohort.

## Provenance, cache, and storage

- 415 immutable source manifests cover 414 canonical requests and one correction/supersession.
- 1,222,673,736 response bytes occupy 92,579,833 bytes in lossless content-addressed gzip artifacts.
- A complete 397-product replay produced 397 cache hits, zero provider calls, and no duplicate facts.
- The run made 421 credentialed HTTP requests. CFBD counted 416 against the shared free-tier quota, leaving 584/1,000 calls. Four `/info` requests and one rejected contract probe were not billed.
- Credential-bearing headers are absent from request hashes, manifests, filenames, reports, and logs.

## Reconciliation

The CFBD corpus contains 123,444 fewer play rows than the Phase 5B-0 cfbfastR QA scan. The sources and filters are not definition-identical: bulky CFBD products are FBS-classification bounded, while the public QA files use their own published universe and processing. Because FBS-participant game coverage is 99.23%, this is not automatically a blocking gap, but Phase 5B-2 must segment the difference by season and game before freezing the feature dataset.
