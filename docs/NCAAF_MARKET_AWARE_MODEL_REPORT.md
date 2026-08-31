# NCAAF Market-Aware Model Report

Status: **Phase 5B-7 completed offline on 2026-08-31.** This is model-selection research, not evidence of profitability, market edge at executable prices, or production readiness. The live API still uses market consensus; no recommendation, EV, stake, or portfolio behavior changed.

## Frozen experiment

- Horizon: first scheduled kickoff minus three hours (`morning_first_kickoff_minus_3h`).
- Development: 2020–2023; validation: 2024; 2025 was not accessed.
- Market source: Phase 5B-7C dataset `cf8669b7f4dd371d12ae03e6e0de180ffb63c196a848a6d7ac791bba8f023bcc`.
- Market policies: `proportional-v1`, `unweighted-median-v1`, two complete supported books minimum, one exact coherent line.
- Football source: chronological OOF predictions only. No provider calls occurred.
- Primary full common cohorts: 2,433 margin games and 2,417 total games. Newly fitted market-aware candidates and OOF blends begin in 2021 because 2020 is their first market-training season, leaving 2,199 margin and 2,198 total point-comparison games.
- Run dataset/hash: `6305a430fd43d74feaf2dad8d326c809d0c2758521db60e5aaa8cc5502e72fad`; primary artifacts contain 41,384 point rows and 36,006 probability rows.

The slate was frozen before execution. It included the prior power/Ridge/CatBoost/preseason finalists, Ridge residual/direct models for both targets, CatBoost residual/direct total challengers, and bounded constrained OOF blends. It did not reopen algorithm, feature, vig, consensus, horizon, or acquisition searches.

## Point-prediction tournament

Lower MAE/RMSE is better. Full-cohort football-only rows cover 2020–2024. Market-aware/blend rows cover 2021–2024 and are compared with the market on those same games.

### Margin

| Candidate | Architecture | Games | MAE | RMSE | Bias | 2024 MAE | Paired MAE minus market (95% season-block interval) | Decision |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| Market consensus spread | market-only | 2,433 | 12.099 | 15.198 | -0.061 | 12.135 | reference | advance benchmark |
| Market + power OOF blend | OOF blend | 2,199 | 12.046 | 15.121 | -0.058 | 12.135 | +0.009 [0.000, +0.032] | reject as replacement; converged to 100% market by 2022 |
| Market + preseason power blend | OOF blend | 2,199 | 12.065 | 15.130 | -0.083 | 12.153 | +0.028 [+0.009, +0.052] | reject |
| Market-residual Ridge | residual | 2,199 | 12.640 | 15.932 | +1.930 | 12.720 | +0.602 [+0.349, +0.872] | reject |
| Market-as-feature Ridge | direct | 2,199 | 12.750 | 16.096 | +2.086 | 12.748 | +0.713 [+0.450, +1.043] | reject |
| Football power | football-only | 2,433 | 13.112 | 16.448 | -0.612 | 13.220 | +1.013 [+0.770, +1.236] | retain independent research benchmark only |
| Preseason power | football-only | 2,433 | 13.135 | 16.398 | -0.275 | 13.312 | +1.036 [+0.756, +1.294] | reject as market challenger |
| Football Ridge full v1 | football-only | 2,433 | 13.323 | 16.719 | +0.702 | 13.523 | +1.224 [+1.003, +1.369] | reject as market challenger |

The independent margin models contain football signal, but they do not improve the morning spread expectation. Larger model-market disagreement primarily identifies larger model error, not a reliable correction signal. The simple blend learns a football weight of 8.4% in 2021 and exactly 0% in 2022–2024; it is therefore not a distinct advancing architecture.

### Total

| Candidate | Architecture | Games | MAE | RMSE | Bias | 2024 MAE | Paired MAE minus market (95% season-block interval) | Decision |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| Market consensus total | market-only | 2,417 | 12.592 | 15.924 | -0.821 | 12.674 | reference | advance benchmark |
| Market + football Ridge OOF blend | OOF blend | 2,198 | 12.481 | 15.780 | -0.567 | 12.633 | -0.026 [-0.038, -0.008] | advance as narrow Phase 5B-8 challenger |
| Market + preseason CatBoost blend | OOF blend | 2,198 | 12.485 | 15.781 | -0.469 | 12.605 | -0.022 [-0.058, +0.019] | retain sensitivity comparator, not a separate finalist |
| Market-residual CatBoost | residual | 2,198 | 12.731 | 15.987 | +0.086 | 12.805 | +0.225 [+0.053, +0.491] | reject |
| Market-as-feature CatBoost | direct | 2,198 | 12.851 | 16.111 | +0.093 | 12.699 | +0.344 [+0.073, +0.732] | reject |
| Market-residual Ridge | residual | 2,198 | 12.976 | 16.301 | -0.058 | 12.889 | +0.470 [+0.208, +0.844] | reject |
| Market-as-feature Ridge | direct | 2,198 | 12.996 | 16.344 | -0.169 | 12.849 | +0.489 [+0.215, +0.880] | reject |
| Football CatBoost full v1 | football-only | 2,417 | 12.875 | 16.273 | +0.024 | 12.747 | +0.283 [+0.114, +0.521] | retain independent point benchmark only |
| Preseason CatBoost | football-only | 2,417 | 12.918 | 16.306 | +0.291 | 12.783 | +0.326 [+0.137, +0.617] | reject as market challenger |
| Football Ridge no-opponent-adjustment | football-only | 2,417 | 12.979 | 16.368 | -0.314 | 12.883 | +0.387 [+0.247, +0.636] | retain blend component only |

The Ridge total blend is the only candidate with a consistently negative paired point-error interval. Its practical improvement is only 0.026 points of MAE, and its 2024 football weight is 17.85%. It advances only as a narrow challenger to a market-only benchmark, not as a clear winner or production model. The CatBoost blend is statistically indistinguishable from market-only and adds more complexity.

## Probability and push-aware diagnostics

Each point candidate was paired with a chronological empirical residual distribution fitted only from earlier candidate OOF seasons. Integer score-lattice settlement preserves nonzero push mass. Market moneyline uses the actual no-vig median consensus rather than a football-derived mapping. Market spread/total side probabilities remain conditional on non-push because sportsbook pairs do not themselves identify push mass; the chronological market-residual distribution supplies the separate research push estimate.

| Target / candidate | Games | ML Brier | ML log loss | Line multiclass Brier | Line multiclass log loss | Mean modeled push |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Margin market consensus | 2,199 | 0.182325 | 0.540039 | 0.512084 | 0.736267 | 0.005192 |
| Margin market + power blend | 1,834 | 0.184641 | 0.544884 | 0.512894 | 0.739227 | 0.005519 |
| Margin football power | 2,199 | 0.198733 | 0.581969 | 0.557081 | 0.790502 | 0.004540 |
| Total market consensus | 2,198 | — | — | 0.504235 | 0.704288 | 0.002295 |
| Total market + Ridge blend | 1,847 | — | — | 0.501253 | 0.701070 | 0.002404 |
| Total market + preseason CatBoost blend | 1,847 | — | — | 0.501218 | 0.701040 | 0.002395 |

On identical probability rows, the margin power blend's ML Brier difference versus market is -0.000127 with an interval spanning zero; its line-score changes are numerically tiny and largely reflect a market-identical location. The total Ridge blend improves multiclass Brier by 0.000997 and log loss by 0.001018 on 1,847 paired games, with season-block intervals excluding zero. The gain is small enough that Phase 5B-8 must freeze a practical-effect rule before accessing 2025.

Reliability tables are preserved in the machine report. Moneyline consensus remains the clear ML benchmark. No proprietary margin probability beat it convincingly. Push probabilities are finite, nonnegative, and included in the three-way score; pushes were never recoded as wins or losses.

## Stability and diagnostics

- The market point baseline led all standalone architectures in every aggregate comparison. Residual and market-as-feature models did not reveal stable systematic market errors.
- The total Ridge blend improved point MAE by a very small amount and did not suffer a 2024 reversal, but the effect is too small to call a clear win before the locked season.
- Preseason/personnel inputs did not create incremental market-relative margin value. The preseason total blend was indistinguishable from the simpler Ridge blend/market baseline.
- Predeclared season, early/late, favorite/underdog, disagreement, book-depth, dispersion, and feature-quality slices are stored in the machine report. No subgroup is used to invent a qualification threshold.
- The bounded 60-minute diagnostic contained 36 margin and 37 total games. Results were noisy: market MAE was 13.306 for margin and 15.324 for total; the corresponding football power and Ridge-no-opponent-adjustment MAEs were 13.055 and 16.313. These small samples did not affect selection.
- Near-close retained 32 spread and 31 total consensus rows but no same-horizon football OOF prediction; it remains consensus-only diagnostic evidence.

## Reproducibility and integrity

- Primary and repeat runs produced the identical dataset hash `6305a430fd43d74feaf2dad8d326c809d0c2758521db60e5aaa8cc5502e72fad`.
- Point artifact hash: `71c33513361d1065eb9e45fe62fd97759f4350ce0e0a630bf9d0c9b7e22aff03`.
- Probability artifact hash: `707d836dffd7c689a341efc4720268a4ddcc202f8daccabfa704d76160e9d9f9`.
- Summary hash: recorded in the final run manifest and machine report.
- Every fitted row has `training_cutoff < season`; 2025 and non-morning rows are rejected; later diagnostic horizons cannot enter selection.
- Runtime was approximately 128 seconds for the final full run on the development machine. Artifacts remain ignored under `.ncaaf-data/`; research dependencies remain outside Render production requirements.

## Phase 5B-8 handoff

Advance a deliberately narrow slate:

1. **Margin and moneyline:** market consensus is the clear benchmark. No proprietary replacement or blend advances. Retain football power only as an independent diagnostic to measure future incremental features.
2. **Total point/probability:** retain market-only and advance the constrained market + Ridge-no-opponent-adjustment blend as a single narrow challenger. Treat the preseason CatBoost blend as a sensitivity comparator, not a second promoted architecture.
3. **Spread probability:** retain the market-centered chronological push-aware distribution benchmark. No residual/direct proprietary architecture advances.
4. Freeze practical-effect, calibration, segment-degradation, artifact, and one-time-access rules before opening 2025. If the tiny total-blend gain fails those rules, retain market consensus rather than force a proprietary model.

Phase 5B-8 may perform the one-time locked evaluation only after this slate and its promotion thresholds are frozen. Nothing in this report authorizes production prediction deployment, EV qualification, staking, recommendations, or a claim of profitability.

Machine-readable report: [`reports/NCAAF_MARKET_AWARE_MODEL_2020_2024.json`](reports/NCAAF_MARKET_AWARE_MODEL_2020_2024.json).
