# NCAAF Historical Market Dataset Report

Status: **Phase 5B-7B canonical data build.** This is acquisition and normalization evidence, not model edge or profitability.

## Acquisition and artifacts

- New historical credits consumed: `12190`.
- New provider calls: `419`; cache hits: `39`.
- Normalized observations: `276620` across `3670` canonical events.
- Dataset hash: `96c3236ea6770e669b351398900b92289a9263cbfe625f3cf986dad235c5274b`; manifest: `bd88f4c68efbbc7d55d4ced6aeabec6304bbbd4125a2dcb89cc176174c183d5b`.
- Raw / normalized storage: `8347309` / `1474389` bytes.

The complete morning cohort is primary evidence. The deterministic 60-minute/near-close cohort is secondary robustness evidence only.

## Aggregate cohort coverage

| Horizon | Market | Games | Usable | Coverage | >=2 books | >=3 books |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| 60_minutes_before_kickoff | h2h | 55 | 47 | 85.45% | 85.45% | 63.64% |
| 60_minutes_before_kickoff | spreads | 55 | 47 | 85.45% | 85.45% | 58.18% |
| 60_minutes_before_kickoff | totals | 55 | 47 | 85.45% | 85.45% | 63.64% |
| morning_first_kickoff_minus_3h | h2h | 3670 | 3132 | 85.34% | 85.34% | 65.42% |
| morning_first_kickoff_minus_3h | spreads | 3670 | 3199 | 87.17% | 87.17% | 66.24% |
| morning_first_kickoff_minus_3h | totals | 3670 | 3245 | 88.42% | 88.42% | 68.99% |
| near_close_5_minutes | spreads | 55 | 46 | 83.64% | 83.64% | 58.18% |
| near_close_5_minutes | totals | 55 | 46 | 83.64% | 83.64% | 63.64% |

## Coverage

| Season | Horizon | Market | Games | Usable | Coverage | >=2 books | >=3 books | Reliable / ambiguous / missing |
| ---: | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 2020 | 60_minutes_before_kickoff | h2h | 13 | 9 | 69.23% | 69.23% | 30.77% | 10 / 0 / 3 |
| 2020 | 60_minutes_before_kickoff | spreads | 13 | 9 | 69.23% | 69.23% | 23.08% | 10 / 0 / 3 |
| 2020 | 60_minutes_before_kickoff | totals | 13 | 9 | 69.23% | 69.23% | 30.77% | 10 / 0 / 3 |
| 2020 | morning_first_kickoff_minus_3h | h2h | 534 | 431 | 80.71% | 80.71% | 57.30% | 487 / 0 / 47 |
| 2020 | morning_first_kickoff_minus_3h | spreads | 534 | 436 | 81.65% | 81.65% | 59.36% | 487 / 0 / 47 |
| 2020 | morning_first_kickoff_minus_3h | totals | 534 | 442 | 82.77% | 82.77% | 60.67% | 487 / 0 / 47 |
| 2020 | near_close_5_minutes | spreads | 13 | 9 | 69.23% | 69.23% | 23.08% | 10 / 0 / 3 |
| 2020 | near_close_5_minutes | totals | 13 | 9 | 69.23% | 69.23% | 30.77% | 10 / 0 / 3 |
| 2021 | 60_minutes_before_kickoff | h2h | 8 | 6 | 75.00% | 75.00% | 37.50% | 7 / 0 / 1 |
| 2021 | 60_minutes_before_kickoff | spreads | 8 | 6 | 75.00% | 75.00% | 37.50% | 7 / 0 / 1 |
| 2021 | 60_minutes_before_kickoff | totals | 8 | 6 | 75.00% | 75.00% | 37.50% | 7 / 0 / 1 |
| 2021 | morning_first_kickoff_minus_3h | h2h | 770 | 581 | 75.45% | 75.45% | 32.60% | 704 / 0 / 66 |
| 2021 | morning_first_kickoff_minus_3h | spreads | 770 | 603 | 78.31% | 78.31% | 32.60% | 704 / 0 / 66 |
| 2021 | morning_first_kickoff_minus_3h | totals | 770 | 616 | 80.00% | 80.00% | 33.90% | 704 / 0 / 66 |
| 2021 | near_close_5_minutes | spreads | 8 | 5 | 62.50% | 62.50% | 37.50% | 7 / 0 / 1 |
| 2021 | near_close_5_minutes | totals | 8 | 5 | 62.50% | 62.50% | 37.50% | 7 / 0 / 1 |
| 2022 | 60_minutes_before_kickoff | h2h | 13 | 13 | 100.00% | 100.00% | 76.92% | 13 / 0 / 0 |
| 2022 | 60_minutes_before_kickoff | spreads | 13 | 13 | 100.00% | 100.00% | 69.23% | 13 / 0 / 0 |
| 2022 | 60_minutes_before_kickoff | totals | 13 | 13 | 100.00% | 100.00% | 76.92% | 13 / 0 / 0 |
| 2022 | morning_first_kickoff_minus_3h | h2h | 776 | 697 | 89.82% | 89.82% | 64.95% | 730 / 0 / 46 |
| 2022 | morning_first_kickoff_minus_3h | spreads | 776 | 698 | 89.95% | 89.95% | 66.11% | 730 / 0 / 46 |
| 2022 | morning_first_kickoff_minus_3h | totals | 776 | 709 | 91.37% | 91.37% | 69.33% | 730 / 0 / 46 |
| 2022 | near_close_5_minutes | spreads | 13 | 13 | 100.00% | 100.00% | 69.23% | 13 / 0 / 0 |
| 2022 | near_close_5_minutes | totals | 13 | 13 | 100.00% | 100.00% | 76.92% | 13 / 0 / 0 |
| 2023 | 60_minutes_before_kickoff | h2h | 8 | 7 | 87.50% | 87.50% | 75.00% | 7 / 0 / 1 |
| 2023 | 60_minutes_before_kickoff | spreads | 8 | 7 | 87.50% | 87.50% | 62.50% | 7 / 0 / 1 |
| 2023 | 60_minutes_before_kickoff | totals | 8 | 7 | 87.50% | 87.50% | 75.00% | 7 / 0 / 1 |
| 2023 | morning_first_kickoff_minus_3h | h2h | 792 | 703 | 88.76% | 88.76% | 82.32% | 738 / 2 / 52 |
| 2023 | morning_first_kickoff_minus_3h | spreads | 792 | 721 | 91.04% | 91.04% | 82.95% | 738 / 2 / 52 |
| 2023 | morning_first_kickoff_minus_3h | totals | 792 | 732 | 92.42% | 92.42% | 87.63% | 738 / 2 / 52 |
| 2023 | near_close_5_minutes | spreads | 8 | 7 | 87.50% | 87.50% | 62.50% | 7 / 0 / 1 |
| 2023 | near_close_5_minutes | totals | 8 | 7 | 87.50% | 87.50% | 75.00% | 7 / 0 / 1 |
| 2024 | 60_minutes_before_kickoff | h2h | 13 | 12 | 92.31% | 92.31% | 92.31% | 12 / 0 / 1 |
| 2024 | 60_minutes_before_kickoff | spreads | 13 | 12 | 92.31% | 92.31% | 92.31% | 12 / 0 / 1 |
| 2024 | 60_minutes_before_kickoff | totals | 13 | 12 | 92.31% | 92.31% | 92.31% | 12 / 0 / 1 |
| 2024 | morning_first_kickoff_minus_3h | h2h | 798 | 720 | 90.23% | 90.23% | 86.22% | 748 / 0 / 50 |
| 2024 | morning_first_kickoff_minus_3h | spreads | 798 | 741 | 92.86% | 92.86% | 86.84% | 748 / 0 / 50 |
| 2024 | morning_first_kickoff_minus_3h | totals | 798 | 746 | 93.48% | 93.48% | 89.60% | 748 / 0 / 50 |
| 2024 | near_close_5_minutes | spreads | 13 | 12 | 92.31% | 92.31% | 92.31% | 12 / 0 / 1 |
| 2024 | near_close_5_minutes | totals | 13 | 12 | 92.31% | 92.31% | 92.31% | 12 / 0 / 1 |

## Integrity and limitations

- Snapshot distance median/p90: `262` / `300` seconds.
- Unusable reasons: event_mapping_ambiguous=6, event_mapping_missing=813, insufficient_supported_complete_books=1476.
- Every stored snapshot is at or before its cutoff; missing prices are never interpolated.
- Individual book observations are retained. Consensus, vig removal, edge, EV, CLV, and model comparison remain Phase 5B-7C or later work.
- The secondary later-horizon cohort is not full-cohort evidence and cannot be represented as such.

## Phase 5B-7C readiness

**GO for primary morning same-horizon model-versus-market work.** All three morning markets exceed 85% aggregate usable/two-book coverage and every season remains above the frozen 70% floor. The later cohorts remain diagnostic only; their small per-season cells, especially 2020–2021, cannot support full-cohort claims.

Machine-readable report: [`reports/NCAAF_HISTORICAL_MARKET_DATASET_2020_2024.json`](reports/NCAAF_HISTORICAL_MARKET_DATASET_2020_2024.json).
