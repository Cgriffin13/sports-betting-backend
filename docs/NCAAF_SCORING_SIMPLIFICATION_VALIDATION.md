# NCAAF scoring simplification validation

Status: **failed validation; not integrated**

Evaluation date: 2026-09-02

Provider calls: **0**

## Decision

The proposed football-backed scoring change must not replace the registered NCAAF v1 market-consensus benchmark. The enhanced football models improved on the prior football-only diagnostics, but did not demonstrate stable incremental information beyond the same-horizon market:

- Margin development selected a **0.0 football weight**. Market consensus beat the enhanced football model in every season from 2020 through 2024 and again in the 2025 diagnostic sample.
- Moneyline development selected a **0.0 football weight**. Market Brier score beat the Normal-converted football margin probability in every evaluated season.
- Total development selected a conservative **0.2 football weight**, improving 2020–2024 MAE by only 0.030 points. The gain reversed in the 2025 diagnostic sample, where the blend was 0.019 points worse than market, and model-versus-market edge buckets were not stable or monotonic.

Because the offline gate failed, no production scoring code, registry status, recommendation behavior, UI, schema, migration, threshold, risk rule, or staking rule changed. The conditional one-call live sanity check was not performed, and no merge or deployment is authorized by this work.

## Inputs and controls

- Point-in-time development corpus: 8,277 game-day-morning rows, seasons 2014–2024.
- 2025 diagnostic corpus: 808 game-day-morning rows, filtered explicitly to season 2025 before concatenation.
- Development dataset hash: `b2f7444e2a7451d90c9078fb3b694d1586b1d30dd7f9c3a60b869381532b8bfe`.
- Diagnostic dataset hash: `ce04f50bea76923ece336e18d384e5f0a8a607bc91c827ebc8501a5956bde4bb`.
- Feature-set version/hash: `ncaaf-efficiency-point-in-time-v1` / `0d4d5b3e9996c5682bc6e5366f70c4a82fd80fce8a3ebaa8db7a6ee22bc446ad`.
- Market-comparison dataset hash: `cf8669b7f4dd371d12ae03e6e0de180ffb63c196a848a6d7ac791bba8f023bcc`.
- Model selection: expanding chronological folds; 2019–2023 development selection, 2024 validation, and 2025 diagnostic evidence only.
- No 2025 row was used for feature selection, preprocessing, model fitting, regularization choice, residual-scale fitting, or blend-weight selection. No 2026 outcome or live slate was inspected.

An initial scratch evaluation accidentally loaded the cumulative 2014–2025 artifact as if every row were a holdout row. That duplicated historical game IDs and allowed later duplicate mappings to corrupt the sequential power feature. The result was rejected immediately. The final run explicitly filtered `season == 2025` before combination and all results below come from that corrected run. This was an evaluation-harness defect caught before any production change, not a production-model result.

## Candidate design

The bounded experiment reused existing point-in-time facts and dependencies:

- prior-only chronological power margin;
- opponent-adjusted offensive and defensive PPA/EPA proxies;
- passing and rushing PPA;
- success and explosive-play rates;
- yards per play, yards per drive, and points per drive;
- plays and drives per game;
- havoc proxy;
- last-3, last-5, season-to-date, prior-season, blended-prior, and prior-only opponent-adjusted windows;
- rest difference, neutral site, conference game, postseason, week, current-season sample depth, and PBP/drive coverage.

Margin used 79 engineered features; total used 148, adding matchup sums appropriate to scoring volume. Fold-local median imputation, missing indicators, standardization, and Ridge were applied. The intentionally small grid was `alpha in {100, 1000}`. Elastic Net was not repeated because the completed baseline tournament already documented bounded convergence failures; existing tree/CatBoost challengers were not reopened because Phase 5 found no stable margin advancement and only a modest offline total challenger that did not earn production status. No injury, ranking, red-zone, reliable turnover, or current-QB feature was fabricated where the frozen corpus did not support it.

## Point-prediction results

| Target | Selected candidate | 2019–2023 MAE / RMSE / bias | 2024 MAE / RMSE / bias | 2025 diagnostic MAE / RMSE / bias |
| --- | --- | --- | --- | --- |
| Margin | Ridge, alpha 100 | 13.116 / 16.513 / +0.628 | 13.006 / 16.316 / -0.503 | 12.570 / 15.910 / -1.197 |
| Total | Ridge, alpha 1000 | 13.218 / 16.568 / +1.292 | 12.899 / 16.301 / +0.139 | 12.848 / 16.007 / +0.211 |

These improve on the documented old margin power MAE of about 13.418 and old total Ridge MAE of about 13.202 only selectively; they do not establish a usable market-relative signal.

## Same-horizon market comparison

### Margin / spread

The development blend selected 0% football and 100% market.

| Cohort | Rows | Market MAE / RMSE | Football MAE / RMSE | Selected blend MAE / RMSE |
| --- | ---: | --- | --- | --- |
| 2020–2024 | 2,499 | 12.105 / 15.197 | 12.928 / 16.187 | 12.105 / 15.197 |
| 2024 validation | 660 | 12.114 / 15.359 | 13.040 / 16.384 | 12.114 / 15.359 |
| 2025 diagnostic | 719 | 11.791 / 14.935 | 12.488 / 15.789 | 11.791 / 14.935 |

Season-by-season market MAE versus football MAE was 12.767 vs 13.302 (2020), 12.274 vs 13.031 (2021), 11.751 vs 12.647 (2022), 12.064 vs 12.861 (2023), and 12.114 vs 13.040 (2024). The football model lost every season.

Historical 2020–2024 ATS direction based on football-minus-market disagreement was not profitable or monotonic:

| Absolute disagreement | Bets | Hit rate | Flat-stake ROI |
| --- | ---: | ---: | ---: |
| 0–1 | 425 | 44.29% | -14.60% |
| 1–2 | 399 | 48.60% | -6.52% |
| 2–3 | 359 | 44.94% | -13.56% |
| 3–5 | 545 | 50.09% | -3.66% |
| 5+ | 771 | 49.02% | -5.76% |

### Total

The development blend selected 20% football and 80% market.

| Cohort | Rows | Market MAE / RMSE | Football MAE / RMSE | 20% blend MAE / RMSE |
| --- | ---: | --- | --- | --- |
| 2020–2024 | 2,417 | 12.592 / 15.924 | 12.949 / 16.313 | 12.562 / 15.885 |
| 2024 validation | 674 | 12.674 / 16.020 | 12.794 / 16.109 | 12.611 / 15.949 |
| 2025 diagnostic | 758 | 12.525 / 15.579 | 12.929 / 16.147 | 12.544 / 15.620 |

The 0.030-point aggregate development gain and 0.063-point 2024 gain were too small to survive the diagnostic season. Season-level blend versus market MAE was 13.496 vs 13.450 (2020), 12.542 vs 12.584 (2021), 12.158 vs 12.159 (2022), 12.552 vs 12.592 (2023), and 12.611 vs 12.674 (2024): the direction and magnitude varied.

Historical 2020–2024 O/U direction showed some high-disagreement strength, but it failed to replicate in 2025:

| Absolute disagreement | 2020–2024 bets / ROI | 2025 diagnostic bets / ROI |
| --- | --- | --- |
| 0–1 | 412 / -2.29% | 183 / +4.30% |
| 1–2 | 364 / -3.69% | 161 / -3.06% |
| 2–3 | 345 / -9.48% | 121 / +1.40% |
| 3–5 | 579 / +3.85% | 156 / -10.21% |
| 5+ | 717 / +5.08% | 137 / -7.48% |

### Moneyline probability

Football home-win probability was derived from enhanced margin and a chronological Normal residual scale of 16.502 points. Development again selected 0% football.

| Cohort | Rows | Market Brier | Football Brier | Selected blend Brier |
| --- | ---: | ---: | ---: | ---: |
| 2020–2024 | 3,132 | 0.18170 | 0.19262 | 0.18170 |
| 2024 validation | 720 | 0.18840 | 0.19930 | 0.18840 |
| 2025 diagnostic | 724 | 0.17905 | 0.18449 | 0.17905 |

Market Brier was better in every season: 0.17379 vs 0.18332 (2020), 0.17627 vs 0.18592 (2021), 0.18940 vs 0.19981 (2022), 0.17655 vs 0.18991 (2023), and 0.18840 vs 0.19930 (2024).

## Production impact

- Registered fair value remains `market consensus` for margin, moneyline, spread, and total.
- No football model or blend is promoted.
- No live provider request or credit was consumed because the offline validation prerequisite failed.
- No Thursday/Friday/Saturday board, Watchlist, major-game analysis, odds mix, recommendation mix, or production Top 10 was generated under an unvalidated model.
- No recommendation, approval, bet, bankroll, ledger, deployment, environment, frontend, or database state changed.

The model family remains a useful research diagnostic, but it is not suitable to drive weekend paper recommendations. A future attempt needs genuinely new, point-in-time football information or a better-validated target formulation—not looser qualification thresholds or post-hoc live-slate tuning.
