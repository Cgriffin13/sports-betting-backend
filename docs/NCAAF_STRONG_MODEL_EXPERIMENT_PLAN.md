# NCAAF Phase 5B-5 Strong-Model Experiment Plan

Status: **Predeclared before Phase 5B-5 model fitting.** This plan governs offline development evidence only. It does not authorize provider access, the 2025 holdout, market comparison, production inference, recommendations, EV, or staking.

## Frozen inputs and folds

- Dataset: `b2f7444e2a7451d90c9078fb3b694d1586b1d30dd7f9c3a60b869381532b8bfe`
- Feature set: `0d4d5b3e9996c5682bc6e5366f70c4a82fd80fce8a3ebaa8db7a6ee22bc446ad`
- Baseline run: `036989b3c5b65226f93f72164e73ec4070b14ca7105d9b55c9e86af9c9778cfb`
- Probability run: `4813f18a64fa5ae0d53038d07947ff47b135107fbf97f03825f25212332ff51b`
- Development evaluations are 2019–2023 from expanding prior-season history. The 2024 season is validation/model selection. Ordinary commands reject 2025 and later.
- Morning, 24-hour, and 60-minute horizons remain distinct. Hyperparameters are selected on the 24-hour development folds once per target and reused unchanged across horizons to avoid redundant tuning of nearly identical football inputs.

## Equal-budget nonlinear screen

XGBoost, LightGBM, and CatBoost each receive exactly three predeclared configurations per target. Every configuration is evaluated on the five 2019–2023 development folds using `full_v1`; the development MAE selects one configuration per family and target. No 2024 outcome participates in hyperparameter selection.

| Configuration | Depth/leaves | Learning rate | Estimators | Row/feature sampling | Regularization/minimum leaf |
|---|---:|---:|---:|---:|---:|
| conservative | depth 3 / 15 leaves | 0.03 | 500 | 0.85 / 0.85 | strong / 20 |
| balanced | depth 5 / 31 leaves | 0.05 | 300 | 0.85 / 0.85 | medium / 20 |
| flexible | depth 7 / 63 leaves | 0.07 | 200 | 0.80 / 0.80 | strong / 30 |

Library-specific equivalents are frozen in code. Seeds are fixed; CPU execution uses one model thread, bounded fold/candidate concurrency, deterministic/histogram modes where supported, and no early stopping against the evaluation fold. Native deterministic missing-value handling is used; no full-dataset imputation or scaling is performed.

Primary tuning budget is `3 families × 3 configurations × 2 targets × 5 development folds = 90 fits`. Selected configurations then produce six-fold OOF predictions for three horizons: `3 × 2 × 6 × 3 = 108 fits`. Only the strongest family per target receives the three additional 24-hour ablations (`full_without_opponent_adjustment`, `raw_efficiency`, and `context_prior`) alongside its already-run `full_v1`, for at most 36 additional fits. The primary maximum is therefore 234 fits. A 2021–2022-excluded training sensitivity adds at most 12 diagnostic fits and is not eligible to select hyperparameters.

Implementation accounting clarification: the completed design uses only one 2024 validation refit per target for the 2021–2022 exclusion (2 fits, not the 12-fit ceiling) and one permutation-importance refit per target (2 fits). The exact executed budget is therefore 238 fits. This clarification changes no candidate, configuration, fold, metric, or advancement gate.

## Point-model evidence and advancement

Margin compares every challenger on identical games with the chronological power rating and Ridge `full_v1`. Total compares with Ridge `full_without_opponent_adjustment` and Ridge `full_v1`. Primary metrics are MAE and RMSE; bias and median absolute error are required diagnostics. Reports include season, 2024, Weeks 0–3/later, 2020, 2021–2022/outside, and high/low-quality segments.

Paired absolute- and squared-error differences use 2,000 deterministic season-block bootstrap samples. At most one nonlinear family may advance per target. Advancement requires all of:

1. at least 0.10 point aggregate 2019–2024 MAE improvement over the simple benchmark;
2. the paired MAE 95% interval has an upper bound below zero;
3. 2024 MAE is no more than 0.15 worse than the benchmark;
4. Weeks 0–3 and low-quality MAE are each no more than 0.25 worse;
5. RMSE is not materially worse and the advantage is not concentrated in 2020 alone;
6. deterministic reproduction and acceptable resource use.

If these gates disagree or improvements are operationally indistinguishable, the simpler baseline remains preferred. Feature importance uses bounded 2024 permutation importance for only the strongest family per target. Importance is diagnostic, not causal. Ablations are hypothesis tests, not a feature-subset search.

## Empirical-discrete margin challenger

The challenger starts from the existing chronological power-rating plus quality-aware Normal lattice. For each evaluation season and horizon, it uses only prior-season OOF rows. On a fixed integer support `[-80, 80]`, it accumulates:

- observed exact final-margin counts; and
- the sum of the benchmark's predicted integer mass.

The empirical calibration ratio is the observed count divided by expected benchmark mass, shrunk toward one with 200 pseudo-observations allocated by expected mass and bounded to `[0.25, 4.0]`. A new game's benchmark lattice is multiplied by these ratios and renormalized. Mass outside the fixed support retains the benchmark ratio of one. Pools require at least 400 rows. This deterministic correction can learn football clustering organically but never adds hand-authored mass to 3, 7, 10, or 14.

Primary comparison uses discrete NLL, lattice CRPS, interval coverage, and synthetic spread multiclass Brier/log loss. Key-number diagnostics predeclare exact margins `3, 7, 10, 14` plus the ten most frequent development margins. Settlement grids are `-2.5/-3/-3.5`, `-6.5/-7/-7.5`, `-9.5/-10/-10.5`, and `-13.5/-14/-14.5`. Half-points must have zero push mass. Season-block paired intervals must show that any key-number improvement does not materially degrade overall proper scores before advancement.

Only a nonlinear point model passing the point gates may receive the limited Phase 5B-4 benchmark distribution pairing. Post-hoc calibration is excluded from the primary 5B-5 design.

For a surviving margin model, the limited pairing is quality-aware Normal versus the existing power-rating plus quality-aware Normal benchmark. For a surviving total model, it is homoskedastic Normal and chronological empirical residual versus the existing Ridge-without-opponent-adjustment plus empirical benchmark. A challenger pairing may displace the simple pairing only when both paired NLL and CRPS season-block 95% intervals end below zero, 90% coverage error is not more than one percentage point worse, and point-model advancement gates already passed. Otherwise the simple probability pairing remains preferred.

## Reproducibility and resource policy

All predictions, configurations, folds, package versions, hashes, decisions, runtime, peak working set, and local artifact paths enter the run manifest. Large artifacts remain under ignored `.ncaaf-data/`. Column projection, one-horizon-at-a-time matrices, single-threaded fits, explicit object release, and sequential artifact writing bound memory. Provider/network access is prohibited; provider calls must remain zero.
