# NCAAF Historical Odds Coverage Audit

Status: **CONDITIONAL GO** for Phase 5B-7 same-horizon market-aware evaluation under `ncaaf-historical-odds-coverage-audit-v1`. This is a coverage audit, not evidence of model edge or profitability.

## Execution and frozen policy

- Logical requests: `76`.
- Unique historical network requests: `67`.
- Credits consumed: `2010` (authorized ceiling: `2280`).
- Provider credits before/after: `20000` / `17990`.
- Seasons: `2020`, `2022`, and `2024`; 2025 was excluded.
- Availability policy: `the-odds-api-provider-archive-snapshot-v1`.
- Minimum supported complete books: `2`.
- Provider snapshots must be at or before the requested cutoff and within 10 minutes before 2022-09-18 or 5 minutes thereafter.

The Odds API credential was used only as a transport parameter. It was not printed, logged, persisted, hashed into a request identifier, included in a report, or committed.

## Primary FBS-vs-FBS horizon and market coverage

| Horizon | Market | Games | Usable | Coverage | Median / p90 timestamp distance | Timestamp fidelity | >=2 / >=3 supported books | Paired completeness | Mapping reliable / ambiguous / missing | Approved |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| 24_hours_before_kickoff | h2h | 15 | 13 | 86.67% | 262s / 300s | 93.33% | 93.33% / 60.00% | 100.00% | 14 / 0 / 1 | no |
| 24_hours_before_kickoff | spreads | 15 | 12 | 80.00% | 262s / 300s | 93.33% | 86.67% / 60.00% | 100.00% | 14 / 0 / 1 | no |
| 24_hours_before_kickoff | totals | 15 | 13 | 86.67% | 262s / 300s | 93.33% | 93.33% / 60.00% | 100.00% | 14 / 0 / 1 | no |
| 60_minutes_before_kickoff | h2h | 15 | 14 | 93.33% | 262s / 300s | 100.00% | 93.33% / 66.67% | 100.00% | 14 / 0 / 1 | yes |
| 60_minutes_before_kickoff | spreads | 15 | 14 | 93.33% | 262s / 300s | 100.00% | 93.33% / 60.00% | 100.00% | 14 / 0 / 1 | yes |
| 60_minutes_before_kickoff | totals | 15 | 14 | 93.33% | 262s / 300s | 100.00% | 93.33% / 66.67% | 100.00% | 14 / 0 / 1 | yes |
| morning_first_kickoff_minus_3h | h2h | 264 | 229 | 86.74% | 262s / 300s | 100.00% | 86.74% / 51.89% | 100.00% | 244 / 0 / 20 | yes |
| morning_first_kickoff_minus_3h | spreads | 264 | 235 | 89.02% | 262s / 300s | 100.00% | 89.02% / 54.92% | 100.00% | 244 / 0 / 20 | yes |
| morning_first_kickoff_minus_3h | totals | 264 | 237 | 89.77% | 262s / 300s | 100.00% | 89.77% / 56.06% | 100.00% | 244 / 0 / 20 | yes |
| morning_fixed_0900_et | h2h | 264 | 229 | 86.74% | 262s / 300s | 100.00% | 86.74% / 51.89% | 100.00% | 244 / 0 / 20 | yes |
| morning_fixed_0900_et | spreads | 264 | 235 | 89.02% | 262s / 300s | 100.00% | 89.02% / 54.92% | 100.00% | 244 / 0 / 20 | yes |
| morning_fixed_0900_et | totals | 264 | 237 | 89.77% | 262s / 300s | 100.00% | 89.77% / 56.06% | 100.00% | 244 / 0 / 20 | yes |
| near_close_5_minutes | h2h | 15 | 13 | 86.67% | 262s / 262s | 100.00% | 86.67% / 66.67% | 100.00% | 14 / 0 / 1 | no |
| near_close_5_minutes | spreads | 15 | 14 | 93.33% | 262s / 262s | 100.00% | 93.33% / 60.00% | 100.00% | 14 / 0 / 1 | yes |
| near_close_5_minutes | totals | 15 | 14 | 93.33% | 262s / 262s | 100.00% | 93.33% / 66.67% | 100.00% | 14 / 0 / 1 | yes |

## Supported sportsbook continuity

| Horizon | Market | DraftKings | FanDuel | BetMGM |
| --- | --- | ---: | ---: | ---: |
| 24_hours_before_kickoff | h2h | 93.33% | 73.33% | 80.00% |
| 24_hours_before_kickoff | spreads | 93.33% | 73.33% | 73.33% |
| 24_hours_before_kickoff | totals | 93.33% | 73.33% | 80.00% |
| 60_minutes_before_kickoff | h2h | 93.33% | 80.00% | 80.00% |
| 60_minutes_before_kickoff | spreads | 93.33% | 80.00% | 73.33% |
| 60_minutes_before_kickoff | totals | 93.33% | 80.00% | 80.00% |
| morning_first_kickoff_minus_3h | h2h | 84.47% | 76.52% | 66.67% |
| morning_first_kickoff_minus_3h | spreads | 88.64% | 79.17% | 67.42% |
| morning_first_kickoff_minus_3h | totals | 88.64% | 79.17% | 69.32% |
| morning_fixed_0900_et | h2h | 84.47% | 76.52% | 66.67% |
| morning_fixed_0900_et | spreads | 88.64% | 79.17% | 67.42% |
| morning_fixed_0900_et | totals | 88.64% | 79.17% | 69.32% |
| near_close_5_minutes | h2h | 93.33% | 80.00% | 73.33% |
| near_close_5_minutes | spreads | 93.33% | 80.00% | 73.33% |
| near_close_5_minutes | totals | 93.33% | 80.00% | 80.00% |

## Primary FBS-vs-FBS season breakdown

| Season | Horizon | Market | Games | Coverage | >=2 books | Paired completeness | Unusable reasons |
| ---: | --- | --- | ---: | ---: | ---: | ---: | --- |
| 2020 | 24_hours_before_kickoff | h2h | 5 | 60.00% | 80.00% | 100.00% | event_mapping_missing=1, insufficient_supported_complete_books=1, snapshot_timestamp_outside_tolerance=1 |
| 2020 | 24_hours_before_kickoff | spreads | 5 | 40.00% | 60.00% | 100.00% | event_mapping_missing=1, insufficient_supported_complete_books=2, snapshot_timestamp_outside_tolerance=1 |
| 2020 | 24_hours_before_kickoff | totals | 5 | 60.00% | 80.00% | 100.00% | event_mapping_missing=1, insufficient_supported_complete_books=1, snapshot_timestamp_outside_tolerance=1 |
| 2020 | 60_minutes_before_kickoff | h2h | 5 | 80.00% | 80.00% | 100.00% | event_mapping_missing=1, insufficient_supported_complete_books=1 |
| 2020 | 60_minutes_before_kickoff | spreads | 5 | 80.00% | 80.00% | 100.00% | event_mapping_missing=1, insufficient_supported_complete_books=1 |
| 2020 | 60_minutes_before_kickoff | totals | 5 | 80.00% | 80.00% | 100.00% | event_mapping_missing=1, insufficient_supported_complete_books=1 |
| 2020 | morning_first_kickoff_minus_3h | h2h | 63 | 82.54% | 82.54% | 100.00% | event_mapping_missing=5, insufficient_supported_complete_books=11 |
| 2020 | morning_first_kickoff_minus_3h | spreads | 63 | 80.95% | 80.95% | 100.00% | event_mapping_missing=5, insufficient_supported_complete_books=12 |
| 2020 | morning_first_kickoff_minus_3h | totals | 63 | 84.13% | 84.13% | 100.00% | event_mapping_missing=5, insufficient_supported_complete_books=10 |
| 2020 | morning_fixed_0900_et | h2h | 63 | 82.54% | 82.54% | 100.00% | event_mapping_missing=5, insufficient_supported_complete_books=11 |
| 2020 | morning_fixed_0900_et | spreads | 63 | 80.95% | 80.95% | 100.00% | event_mapping_missing=5, insufficient_supported_complete_books=12 |
| 2020 | morning_fixed_0900_et | totals | 63 | 84.13% | 84.13% | 100.00% | event_mapping_missing=5, insufficient_supported_complete_books=10 |
| 2020 | near_close_5_minutes | h2h | 5 | 60.00% | 60.00% | 100.00% | event_mapping_missing=1, insufficient_supported_complete_books=2 |
| 2020 | near_close_5_minutes | spreads | 5 | 80.00% | 80.00% | 100.00% | event_mapping_missing=1, insufficient_supported_complete_books=1 |
| 2020 | near_close_5_minutes | totals | 5 | 80.00% | 80.00% | 100.00% | event_mapping_missing=1, insufficient_supported_complete_books=1 |
| 2022 | 24_hours_before_kickoff | h2h | 5 | 100.00% | 100.00% | 100.00% | none |
| 2022 | 24_hours_before_kickoff | spreads | 5 | 100.00% | 100.00% | 100.00% | none |
| 2022 | 24_hours_before_kickoff | totals | 5 | 100.00% | 100.00% | 100.00% | none |
| 2022 | 60_minutes_before_kickoff | h2h | 5 | 100.00% | 100.00% | 100.00% | none |
| 2022 | 60_minutes_before_kickoff | spreads | 5 | 100.00% | 100.00% | 100.00% | none |
| 2022 | 60_minutes_before_kickoff | totals | 5 | 100.00% | 100.00% | 100.00% | none |
| 2022 | morning_first_kickoff_minus_3h | h2h | 96 | 88.54% | 88.54% | 100.00% | event_mapping_missing=7, insufficient_supported_complete_books=11 |
| 2022 | morning_first_kickoff_minus_3h | spreads | 96 | 91.67% | 91.67% | 100.00% | event_mapping_missing=7, insufficient_supported_complete_books=8 |
| 2022 | morning_first_kickoff_minus_3h | totals | 96 | 91.67% | 91.67% | 100.00% | event_mapping_missing=7, insufficient_supported_complete_books=8 |
| 2022 | morning_fixed_0900_et | h2h | 96 | 88.54% | 88.54% | 100.00% | event_mapping_missing=7, insufficient_supported_complete_books=11 |
| 2022 | morning_fixed_0900_et | spreads | 96 | 91.67% | 91.67% | 100.00% | event_mapping_missing=7, insufficient_supported_complete_books=8 |
| 2022 | morning_fixed_0900_et | totals | 96 | 91.67% | 91.67% | 100.00% | event_mapping_missing=7, insufficient_supported_complete_books=8 |
| 2022 | near_close_5_minutes | h2h | 5 | 100.00% | 100.00% | 100.00% | none |
| 2022 | near_close_5_minutes | spreads | 5 | 100.00% | 100.00% | 100.00% | none |
| 2022 | near_close_5_minutes | totals | 5 | 100.00% | 100.00% | 100.00% | none |
| 2024 | 24_hours_before_kickoff | h2h | 5 | 100.00% | 100.00% | 100.00% | none |
| 2024 | 24_hours_before_kickoff | spreads | 5 | 100.00% | 100.00% | 100.00% | none |
| 2024 | 24_hours_before_kickoff | totals | 5 | 100.00% | 100.00% | 100.00% | none |
| 2024 | 60_minutes_before_kickoff | h2h | 5 | 100.00% | 100.00% | 100.00% | none |
| 2024 | 60_minutes_before_kickoff | spreads | 5 | 100.00% | 100.00% | 100.00% | none |
| 2024 | 60_minutes_before_kickoff | totals | 5 | 100.00% | 100.00% | 100.00% | none |
| 2024 | morning_first_kickoff_minus_3h | h2h | 105 | 87.62% | 87.62% | 100.00% | event_mapping_missing=8, insufficient_supported_complete_books=13 |
| 2024 | morning_first_kickoff_minus_3h | spreads | 105 | 91.43% | 91.43% | 100.00% | event_mapping_missing=8, insufficient_supported_complete_books=9 |
| 2024 | morning_first_kickoff_minus_3h | totals | 105 | 91.43% | 91.43% | 100.00% | event_mapping_missing=8, insufficient_supported_complete_books=9 |
| 2024 | morning_fixed_0900_et | h2h | 105 | 87.62% | 87.62% | 100.00% | event_mapping_missing=8, insufficient_supported_complete_books=13 |
| 2024 | morning_fixed_0900_et | spreads | 105 | 91.43% | 91.43% | 100.00% | event_mapping_missing=8, insufficient_supported_complete_books=9 |
| 2024 | morning_fixed_0900_et | totals | 105 | 91.43% | 91.43% | 100.00% | event_mapping_missing=8, insufficient_supported_complete_books=9 |
| 2024 | near_close_5_minutes | h2h | 5 | 100.00% | 100.00% | 100.00% | none |
| 2024 | near_close_5_minutes | spreads | 5 | 100.00% | 100.00% | 100.00% | none |
| 2024 | near_close_5_minutes | totals | 5 | 100.00% | 100.00% | 100.00% | none |

## Timestamp and identity findings

The four boundary probes returned closest-prior snapshots as recorded in the machine report. Provider event IDs were stable for `284/284` matched audited games across horizons.

| Probe | Requested | Returned | Absolute distance | At/before cutoff |
| --- | --- | --- | ---: | --- |
| 2024-boundary-before_grid | 2024-09-07T12:59:59Z | 2024-09-07T12:55:38Z | 261s | yes |
| 2024-boundary-at_grid | 2024-09-07T13:00:00Z | 2024-09-07T12:55:38Z | 262s | yes |
| 2024-boundary-after_grid | 2024-09-07T13:00:01Z | 2024-09-07T12:55:38Z | 263s | yes |
| 2024-boundary-next_grid | 2024-09-07T13:05:00Z | 2024-09-07T13:00:38Z | 262s | yes |

Historical archive rows use provider snapshot time for research availability and retain real local retrieval time. They are not mislabeled as contemporaneous Phase 3 ingestions.

The approval gates use only the frozen FBS-vs-FBS model cohort. FBS/FCS and other context rows are retained in the machine-readable cohort/slate summaries and were not silently discarded.

## Decision

**CONDITIONAL GO**. Approved horizon/market combinations: `60_minutes_before_kickoff|h2h, 60_minutes_before_kickoff|spreads, 60_minutes_before_kickoff|totals, morning_first_kickoff_minus_3h|h2h, morning_first_kickoff_minus_3h|spreads, morning_first_kickoff_minus_3h|totals, morning_fixed_0900_et|h2h, morning_fixed_0900_et|spreads, morning_fixed_0900_et|totals, near_close_5_minutes|spreads, near_close_5_minutes|totals`.

Recommended game-day-morning convention: `morning_first_kickoff_minus_3h`.
The candidates used the same timestamp on `8/9` slates and tied on aggregate coverage. Coverage tied; the relative convention guarantees a run before the first kickoff and remains well-defined when a slate starts earlier or later than noon Eastern.

A larger bounded historical acquisition is justified only for the approved combinations.
Do not substitute a missing horizon, loosen the two-book gate, or infer edge from this audit.

## Limitations

- This bounded sample covers nine representative slates, not every game or bookmaker vintage.
- Historical snapshots can contain provider corrections and only include books/markets available at that time.
- Display-name reconciliation is deterministic and orientation-aware; missing matches remain missing rather than fuzzy-merged.
- Near-close is a five-minute proxy, not a universal sportsbook-specific closing definition.
- The audit evaluates acquisition feasibility only. It does not compare models, calculate EV, or claim profitability.

Machine-readable aggregate: [`reports/NCAAF_HISTORICAL_ODDS_AUDIT_2020_2024.json`](reports/NCAAF_HISTORICAL_ODDS_AUDIT_2020_2024.json).
