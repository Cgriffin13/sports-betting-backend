# NCAAF Market Comparison Dataset Report

Status: **Phase 5B-7C offline comparison plumbing.** These diagnostics do not establish market edge, profitability, or production readiness.

## Provenance

- Comparison dataset hash: `cf8669b7f4dd371d12ae03e6e0de180ffb63c196a848a6d7ac791bba8f023bcc`; manifest: `afd57f1eabda16a17f3e1cf75072acb931b0f5270fa0c67d3f5ee774bbbfe811`.
- Source market dataset: `96c3236ea6770e669b351398900b92289a9263cbfe625f3cf986dad235c5274b`.
- Football OOF run: `036989b3c5b65226f93f72164e73ec4070b14ca7105d9b55c9e86af9c9778cfb`; feature set: `0d4d5b3e9996c5682bc6e5366f70c4a82fd80fce8a3ebaa8db7a6ee22bc446ad`.
- Policies: `proportional-v1` and `unweighted-median-v1`.
- Provider calls: `0`; 2025 holdout accessed: `false`.

## Artifact rows

- market_consensus: `8231` rows.
- football_market_joined: `16336` rows.
- residual_targets: `9978` rows.
- market_features: `9846` rows.

## Primary common cohorts

| Target / horizon | Rows | Unique games |
| --- | ---: | ---: |
| margin|60_minutes_before_kickoff | 72 | 36 |
| margin|morning_first_kickoff_minus_3h | 4866 | 2433 |
| total|60_minutes_before_kickoff | 74 | 37 |
| total|morning_first_kickoff_minus_3h | 4834 | 2417 |

Each selected point-model candidate contributes a separate row. Morning rows are the primary 2020–2023 development / 2024 validation cohort. Sixty-minute rows are diagnostic only. Near-close is consensus-only because no same-horizon football OOF prediction exists.

## Coverage and integrity

- Exact-line consensus rows with >=2 / >=3 books: `100.00%` / `51.08%`.
- Probability dispersion median / p90: `0.008664009704` / `0.01891548584`.
- Snapshot-distance median / p90: `261.0` / `300.0` seconds.
- Diagnostic consensus / joined rows: `183` / `240`.
- Exclusions: `{"fewer_than_two_complete_books_at_exact_line": 2018, "market_state_unavailable": 27704}`.
- Spread/total pairs are coherent within book and only the deterministically selected exact point contributes to probability consensus. Different points are never averaged.
- Canonical identity, OOF training cutoff, horizon equivalence, requested cutoff, and closest-prior snapshot are validated. Push labels remain separate.

## Plumbing-only market diagnostic

- Moneyline games: `3179`; Brier `0.182131`; log loss `0.540322`.
- These scores verify calculation and label plumbing. They are not a final model-selection comparison and say nothing about betting returns.

## Full Phase 5B-7 readiness

**Unblocked for the predeclared morning market-aware tournament.** The next phase may fit football-only, residual, and market-as-feature candidates on the frozen common cohorts. It must keep later horizons diagnostic, preserve 2025, predeclare comparisons, and make no profitability claim from this dataset alone.

Machine-readable report: [`reports/NCAAF_MARKET_COMPARISON_DATASET_2020_2024.json`](reports/NCAAF_MARKET_COMPARISON_DATASET_2020_2024.json).
