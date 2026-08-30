# NCAAF Strong Model Challenger Report

Status: **Phase 5B-5 completed offline on 2026-08-30.** This report is development evidence from 2014–2024 only. It does not use 2025, sportsbook prices, EV, staking, or production recommendations.

## Frozen inputs and experiment

- Dataset hash: `b2f7444e2a7451d90c9078fb3b694d1586b1d30dd7f9c3a60b869381532b8bfe`
- Feature-set hash: `0d4d5b3e9996c5682bc6e5366f70c4a82fd80fce8a3ebaa8db7a6ee22bc446ad`
- Phase 5B-3 baseline run: `036989b3c5b65226f93f72164e73ec4070b14ca7105d9b55c9e86af9c9778cfb`
- Phase 5B-4 probability run: `4813f18a64fa5ae0d53038d07947ff47b135107fbf97f03825f25212332ff51b`
- Strong-model run: `8d168885a452466d92b8a97d650ce672710703e91e0af329632b111496a1cbfb`
- Key-number run: `38d21e9743db9e65b3f0f20f6118db9b18e00c7d778a7f1dbdde461d42b508e6`
- Challenger-distribution run: `f3d566354c8bd7854a7cb32d30238fb14a2495557289be18ec9c07e0ac1afc37`

The predeclared tournament gave XGBoost, LightGBM, and CatBoost the same three configurations and chronological folds. Configuration selection used 2019–2023 development evidence at 24 hours; 2024 remained validation. The selected conservative configuration used depth 3, 500 estimators, learning rate 0.03, 0.85 row/feature subsampling, minimum child size 20, and L2 15. The exact executed budget was 238 fits: 90 tuning, 108 primary OOF, 36 ablation, 2 sensitivity, and 2 permutation-importance refits. Provider calls were zero.

## Point-prediction results

The primary comparison horizon is 24 hours before kickoff. Values below are chronological OOF development metrics.

| Target | Candidate | MAE | RMSE | 2024 MAE | Weeks 0–3 MAE | Decision |
|---|---:|---:|---:|---:|---:|---|
| Margin | Power rating baseline | 13.418 | 16.941 | 13.364 | 14.861 | Retain |
| Margin | XGBoost | 13.521 | 17.029 | 13.319 | 14.603 | Reject |
| Margin | LightGBM | 13.563 | 17.059 | 13.308 | 14.662 | Reject |
| Margin | CatBoost | 13.522 | 16.997 | 13.388 | 14.688 | Reject |
| Total | Ridge without opponent adjustment | 13.202 | 16.618 | 12.964 | 13.126 | Benchmark |
| Total | XGBoost | 13.111 | 16.511 | 12.684 | 12.935 | Does not clear all gates |
| Total | LightGBM | 13.109 | 16.518 | 12.806 | 12.945 | Does not clear all gates |
| Total | CatBoost | 13.094 | 16.481 | 12.878 | 12.900 | Advances as offline point challenger |

No margin tree earned advancement. CatBoost total improved MAE by 0.108 points over Ridge; its season-block paired MAE interval was `[-0.184, -0.030]`, and all frozen point gates passed. This is a modest model-quality result, not evidence of betting edge.

CatBoost total residuals had mean `-0.035` in actual-minus-prediction convention, standard deviation `16.481`, skewness `0.317`, excess kurtosis `0.217`, and 5th/50th/95th percentiles `-25.782`, `-0.750`, and `28.616`. Low-quality MAE was `13.457`; 2020 MAE was `13.754`; the 2021–2022 tagged segment was `12.910`. Excluding 2021–2022 from training for the 2024 sensitivity refit did not reveal a blocking instability.

## Ablations and interpretation

Context/prior-only inputs were materially weaker. Raw efficiency, full-v1, and full-without-opponent-adjustment remained close enough that individual feature-family claims should stay conservative. Permutation importance is diagnostic, not causal. The strongest measured margin signals were defensive PPA differential, success-rate differential, points-per-drive differential, and away opponent-adjusted offensive PPA. The strongest total signals were away blended defensive PPA allowed, home blended plays per game, home blended defensive PPA allowed, and prior drives/defensive PPA.

| CatBoost 24h ablation | Margin MAE | Total MAE |
|---|---:|---:|
| Context/prior only | 14.844 | 13.532 |
| Raw efficiency | 13.631 | 13.084 |
| Without opponent adjustment | 13.553 | 13.090 |
| Full v1 | 13.522 | 13.094 |

In 2020, CatBoost margin MAE was `13.797` versus the power benchmark's `13.643`; CatBoost total was `13.754` versus Ridge's `13.976`. The total improvement was therefore not solely a 2020 artifact. CatBoost's 2021–2022 versus outside-segment MAEs were `13.490` versus `13.539` for margin and `12.910` versus `13.192` for total. A 2024 refit excluding 2021–2022 training rows produced MAE `13.366` margin and `12.814` total versus full-training `13.388` and `12.878`; the known PBP discrepancy is non-blocking for this tournament, without being declared irrelevant.

Opponent adjustment contributed modestly to margin but not total in this bounded comparison. Coverage/quality fields appeared in margin importance, while recent-form fields were not consistently dominant. Many lower-ranked permutation effects were near zero or variable across repeats; they are unstable diagnostics and were not used for post-result feature removal.

The three horizons remain separate. Their football-only results are close, as expected, but not copied or pooled because point-in-time inputs can differ.

## Key-number refinement

The empirical-discrete margin challenger learns an integer residual-ratio mass function only from strictly earlier OOF seasons and multiplies it by the existing quality-aware Normal lattice before normalization. It does not manually add probability to 3, 7, 10, or 14.

At 24 hours on 3,670 evaluated games:

| Distribution | NLL | Discrete CRPS | 90% coverage | 90% width |
|---|---:|---:|---:|---:|
| Quality-aware Normal lattice | 4.24188 | 9.49758 | 90.76% | 55.87 |
| Empirical discrete | 4.11085 | 9.42329 | 93.35% | 59.41 |

Paired empirical-minus-Normal differences were `-0.13103` NLL (95% season-block interval `[-0.14656, -0.11379]`) and `-0.07429` CRPS (`[-0.09176, -0.06052]`). Exact positive-margin mass improved substantially:

| Margin | Observed | Normal | Empirical discrete |
|---:|---:|---:|---:|
| 3 | 5.531% | 2.084% | 5.518% |
| 7 | 4.659% | 2.056% | 4.051% |
| 10 | 2.643% | 1.977% | 2.643% |
| 14 | 2.725% | 1.806% | 2.714% |

The empirical-discrete method advances for offline spread/push research. Its wider, overcovering 90% intervals remain a limitation to monitor. Phase 4's production integer-line exclusion is unchanged.

The next most common positive margins after the predeclared keys were 21 (90 games), 17 (86), 4 (78), 2 (71), and 28 (68). They were identified diagnostically rather than added to the primary selection rule. On integer spreads, empirical predicted push equals the corresponding exact-margin mass shown above; at half-points (`-2.5`, `-3.5`, `-6.5`, `-7.5`, `-9.5`, `-10.5`, `-13.5`, `-14.5`) push probability is exactly zero. Multiclass cover/push/loss scores were computed across the entire frozen grid.

## Limited distribution pairing

Only the surviving CatBoost total point challenger received the predeclared limited pairing. At 24 hours:

| Pairing | NLL | CRPS | 90% coverage | 90% width |
|---|---:|---:|---:|---:|
| CatBoost + Normal | 4.22008 | 9.22152 | 90.65% | 54.97 |
| CatBoost + empirical residual | 4.21492 | 9.21123 | 91.44% | 56.56 |
| Ridge + empirical residual benchmark | 4.22481 | 9.30423 | 91.17% | 56.78 |

CatBoost empirical minus Ridge empirical was `-0.00988` NLL with interval `[-0.02494, 0.00012]`, and `-0.09300` CRPS with interval `[-0.23744, 0.00718]`. Both intervals cross zero. CatBoost therefore remains an offline point-model challenger, while Ridge plus empirical residual remains the total probability benchmark.

## Operational evidence and limitations

- Strong tournament: 108,252 OOF rows, 2.27 MB Parquet and 2.77 MB total artifacts, 2,042.6 seconds, peak RSS 1.00 GiB.
- Key-number run: 22,020 rows, 10.61 MB total artifacts, 168.1 seconds, peak RSS 685.4 MiB.
- Challenger distribution: 22,020 rows, 2.08 MB total artifacts, 23.7 seconds, peak RSS 618.0 MiB.
- Artifacts are content-hashed, local, ignored by Git, and reproducible from frozen inputs.
- 2025 remained sealed; all standard commands reject it before artifact reads.
- No historical provider call, database migration, FastAPI import, endpoint, or Render dependency was added.

Phase 5B-6 readiness: retain the power rating for margin; retain Ridge plus empirical residual as the total probability benchmark; carry CatBoost total as a point challenger; carry empirical-discrete margin for offline push/key-number evaluation. Historical same-horizon sportsbook acquisition and market-relative evaluation remain blockers to any edge, EV, or production claim. Recruiting, transfers, returning production, quarterback continuity, coaching, weather, and injuries remain separate predeclared feature tracks—not post-result explanations for this tournament.
