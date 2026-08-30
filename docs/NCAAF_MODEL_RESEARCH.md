# NCAAF Model Research and Architecture

Status: **Phase 5A research specification; no proprietary production model is implemented.**

This document defines the recommended NCAAF modeling architecture and the questions Phase 5B must answer empirically. Phase 5B-3 produced offline point-model evidence, and Phase 5B-4 now adds chronological distributions, push-aware probabilities, and calibration diagnostics; [`NCAAF_BASELINE_MODEL_REPORT.md`](NCAAF_BASELINE_MODEL_REPORT.md) and [`NCAAF_PROBABILITY_CALIBRATION_REPORT.md`](NCAAF_PROBABILITY_CALIBRATION_REPORT.md) record the measured results. Market consensus remains the implemented benchmark. None of these candidates affects `/opportunities`, official bets, or staking until it passes the promotion process in this document and `NCAAF_BACKTEST_DESIGN.md`.

## Executive recommendation

Build a chronological tournament around two primary continuous targets:

```text
margin = home_points - away_points
total  = home_points + away_points
```

Each candidate must emit a predictive distribution, not just a point estimate. The distribution is discretized onto integer football scores so moneyline, spread, total, and push probabilities are coherent. Direct home/away score models and a direct moneyline classifier are challengers and diagnostic checks, not assumed winners.

Run three information architectures:

1. **Independent football model:** point-in-time football features only.
2. **Market-residual model:** predict the error in a fixed-horizon market expectation.
3. **Market-as-feature model:** use market state explicitly, after independent and residual benchmarks exist.

The initial algorithm tournament includes a naive opponent-adjusted baseline, Elo/power ratings, Ridge/Elastic Net, a controlled screen of XGBoost/LightGBM/CatBoost, and a deferred hierarchical Bayesian challenger. No family is “the model.” Learned blends are eligible only from out-of-fold predictions and must beat the Phase 4 market baseline on locked chronological data.

The approved first practical workflow is **one game-day-morning run before the first NCAAF kickoff of the day**. The exact fixed local time versus first-kickoff-relative rule remains deliberately unfrozen until the bounded historical-odds audit establishes which convention is consistently reconstructable. Continue evaluating 60 minutes and 24 hours before kickoff as separate research horizons; never combine their results or substitute one for missing morning data.

## 1. Modeling problem

### 1.1 Primary targets

The first tournament should fit margin and total separately because they map directly to the three initial markets and are easy to audit:

- Margin distribution gives `P(home win)`, `P(away win)`, and cover/push/loss probabilities at any spread.
- Total distribution gives over/push/under probabilities at any total.
- A shared feature pipeline can serve both while allowing target-specific regularization, nonlinearities, variance, and calibration.

Point estimates alone are insufficient. For predictive cumulative distribution `F_M` over integer margin `M` and home spread `s`:

```text
P(home covers) = P(M + s > 0)
P(push)        = P(M + s = 0)
P(home loses) = P(M + s < 0)
```

For integer total score `T` and posted total `l`:

```text
P(over)  = P(T > l)
P(push)  = P(T = l)
P(under) = P(T < l)
```

Moneyline probability follows `P(M > 0)` and `P(M < 0)`. NCAA overtime and sportsbook full-game settlement rules must be reflected in the target score; ties should be impossible for completed modern games but data anomalies must be rejected.

### 1.2 Component-score challenger

Modeling `home_points` and `away_points` can produce a coherent joint score simulation and naturally link margin, total, and future correlated markets. It also exposes offense-versus-defense decomposition. Its drawbacks are larger specification burden, a required score covariance model, and the risk of optimizing score accuracy without improving the market probabilities that matter.

Phase 5B should test component scores as a challenger using either:

- two regularized conditional-mean models plus a residual covariance model; or
- a joint probabilistic model when a library supports it without fragile deployment.

Consistency checks should compare:

```text
derived_margin = predicted_home_points - predicted_away_points
derived_total  = predicted_home_points + predicted_away_points
```

against the direct margin/total candidates. A component model is promoted only if probability and calibration metrics improve, not because its score decomposition is aesthetically attractive.

### 1.3 Direct win-probability challenger

A direct binary home-win model is useful as:

- a moneyline-specific challenger;
- a check on probabilities derived from the margin distribution; and
- a possible ensemble component.

It cannot price spreads or totals and discards margin magnitude. It should therefore not be the sole first production architecture. Direct probability calibration must use validation-period predictions only.

## 2. Candidate model families

| Family | Role in tournament | Strengths | Principal risks | Phase 5B disposition |
| --- | --- | --- | --- | --- |
| Naive opponent-adjusted baseline | Falsification floor | Transparent, cheap, catches pipeline errors | Underfits nonlinear/context effects | Required |
| Elo / dynamic power rating | Sequential team-strength baseline | Naturally time-aware, handles unequal schedules, deploys trivially | One-dimensional strength; MOV, carryover, and HFA choices can overfit | Required |
| Ridge regression | Primary interpretable benchmark | Stable under correlated efficiency features; fast; auditable coefficients | Linear/additive unless interactions are explicit | Required |
| Elastic Net | Sparse challenger | Can suppress redundant features | Instability under strongly correlated groups; sparsity is not truth | Small controlled comparison |
| XGBoost | Boosted-tree challenger | Mature ecosystem, missing-value handling, constraints, CPU package option | Hyperparameter search and overfit risk; categorical preparation | Screen under fixed budget |
| LightGBM | Boosted-tree challenger | Fast histogram training, native missing/categorical support | Leaf-wise growth can overfit small seasonal data; binary dependency | Screen under same budget |
| CatBoost | Boosted-tree challenger | Strong categorical handling, ordered target statistics, missing-value support | Larger dependency/artifacts; categorical transforms require temporal care | Screen under same budget |
| Hierarchical Bayesian | Partial-pooling challenger | Principled early-season/team/conference uncertainty and shrinkage | Modeling and inference complexity; slower iteration/deployment | Research after deterministic baselines |
| Ensemble / stacking | Potential final combination | Can exploit genuinely different errors | Leakage and arbitrary-weight risk | Only from chronological OOF predictions |

Official documentation confirms that CatBoost handles numerical/categorical inputs and explicit missing-value modes, LightGBM handles missing values and integer-coded categoricals, and XGBoost offers a CPU-only distribution. Those capabilities are reasons to test—not evidence of NCAAF superiority: [CatBoost categorical features](https://catboost.ai/docs/en/features/categorical-features), [CatBoost missing values](https://catboost.ai/docs/en/concepts/algorithm-missing-values-processing), [LightGBM advanced topics](https://lightgbm.readthedocs.io/en/latest/Advanced-Topics.html), [XGBoost installation](https://xgboost.readthedocs.io/en/stable/install.html).

### 2.1 Naive baseline

Use only information available before the game:

- exponentially weighted scoring margin and total;
- home-field/neutral-site indicator;
- simple schedule-strength adjustment estimated only from prior games; and
- offseason regression toward the FBS mean.

This is intentionally hard to fool and should be reproducible in a few pure functions. If a complex model cannot beat it chronologically, the complex model is rejected.

### 2.2 Elo / power ratings

Test standard result-only Elo and a margin-of-victory variant. Learn, rather than assume:

- home-field points/rating adjustment;
- update factor;
- MOV transform and cap;
- offseason carryover and regression;
- promoted/reclassified team prior; and
- optional conference-level preseason shrinkage.

QB, roster, recruiting, or conference-strength adjustments should enter only as separately versioned prior experiments. They must not be hand-tuned point bonuses. Dynamic paired-comparison models support time-varying latent strength, but their utility here remains empirical: [dynamic Bradley–Terry research](https://rss.onlinelibrary.wiley.com/doi/full/10.1111/j.1467-9876.2012.01046.x).

### 2.3 Regularized regression

Ridge is the default interpretable benchmark for margin and total. Encode games symmetrically where possible:

- margin predictors primarily use home-minus-away features;
- total predictors primarily use home-plus-away and matchup interactions;
- venue, neutral site, rest, travel, season week, and data-quality flags remain explicit.

Standardization, imputation, and categorical encoding must be fitted inside each chronological training fold. Report standardized coefficients and coefficient stability across folds.

### 2.4 Boosted trees

Run XGBoost, LightGBM, and CatBoost against the identical versioned feature matrix, folds, targets, tuning budget, seeds, and stopping rules. Compare:

- walk-forward MAE/RMSE and probabilistic score;
- calibration before and after the same calibration protocol;
- early-season and missing-data robustness;
- wall time, peak memory, artifact size, deterministic inference, and Render compatibility;
- SHAP stability and ease of auditing.

The initial data volume is modest by ML standards, so training speed is not the selection criterion. If the three are statistically indistinguishable, prefer the smaller operational burden. Deep neural networks are excluded from the initial tournament because the tabular sample is small and no incremental hypothesis currently justifies them.

### 2.5 Hierarchical Bayesian model

NCAAF has many teams, unequal schedules, conference structure, short seasons, and severe offseason turnover. Partial pooling is therefore scientifically attractive for:

- team offense/defense latent effects;
- conference-level priors;
- season-to-season state evolution;
- explicit early-season posterior uncertainty; and
- missing or sparse team histories.

It is not required for 5B-1. First determine whether Ridge/Elo residuals show stable conference/team pooling structure. A Bayesian candidate should start with a modest dynamic margin model, use prior predictive checks, and be judged by the same held-out log score—not by posterior sophistication. Bradley–Terry extensions demonstrate the value and computational cost of hierarchical paired comparisons: [Bayesian paired comparison overview](https://pmc.ncbi.nlm.nih.gov/articles/PMC9374650/).

## 3. Market-aware versus market-independent architecture

### Architecture A — independent football model

```text
point-in-time football features -> margin/total distribution -> probabilities
                                                          |
market consensus -----------------------------------------+-> comparison only
```

This measures whether football data contains independent signal and makes model-market disagreement interpretable. It may be less accurate than the market, especially near kickoff. It is required even if never promoted.

### Architecture B — market as a feature

Include a fixed-horizon consensus spread/total/probability, dispersion, contributing-book count, and time-to-kickoff. This will often improve raw prediction because the market aggregates information unavailable in structured data.

Risks:

- using a closing line for an earlier simulated decision;
- training on a best price while evaluating against that same price;
- confusing a market-driven output with independent proprietary signal;
- learning book/provider availability artifacts;
- circular explanations such as “the model likes the team because the market does.”

This architecture is tested only with exact as-of joins to Phase 3 observations.

### Architecture C — market residual

For spread/margin:

```text
target_residual = actual_margin - market_expected_margin_at_horizon
```

For totals:

```text
target_residual = actual_total - market_total_at_horizon
```

The model predicts a correction to market expectation. This directly asks whether features add incremental information and tends to shrink naturally toward the market. For moneyline, use a log-odds correction or compare the corrected margin distribution with consensus; do not subtract probabilities on an unconstrained scale.

Recommendation: test A and C first. Test B concurrently as a challenger, but require it to expose the market feature and residual contribution separately. Architecture C is the leading practical hypothesis, not a predetermined winner.

## 4. Market/model blending

No fixed blend is accepted. Candidate mechanisms are:

1. residual correction to market margin/total;
2. logistic stacking on out-of-fold market and model log-odds;
3. constrained calibrated weight estimated on validation data;
4. Bayesian shrinkage toward market with learned uncertainty; and
5. regime-dependent weights only after simpler weights are stable.

Weights may be conditioned on week, returning production, QB continuity, market book count/dispersion, model predictive scale, and time to kickoff only if the interaction improves forward validation. The number of regimes must be small enough to retain useful sample size.

Every blend output must retain:

- market probability and policy version;
- independent/model probability and model version;
- blend mechanism and fitted parameters;
- training cutoff and calibration version;
- final probability; and
- component uncertainty.

If no blend improves market consensus on locked data, production fair probability remains market consensus.

## 5. Predictive distributions and pushes

### 5.1 Candidate distributions

Test these in increasing complexity:

1. homoskedastic normal residual;
2. Student-t residual with learned degrees of freedom;
3. empirical out-of-fold residual distribution;
4. heteroskedastic location-scale model;
5. quantile/distributional regression; and
6. joint score simulation if component models justify it.

Normality is a benchmark, not an assumption. Compare negative log likelihood, CRPS, PIT/reliability diagnostics, tail coverage, and line-level Brier/log loss. NGBoost is a possible distributional challenger because it predicts conditional distribution parameters under proper scoring rules, but its parametric family must fit the data: [NGBoost paper](https://proceedings.mlr.press/v119/duan20a.html).

### 5.2 Discretization

For a continuous latent margin CDF `F`, assign probability mass to integer score margin `k`:

```text
P(M = k) = F(k + 0.5) - F(k - 0.5)
```

Apply the same lattice conversion to total points and normalize any truncated numerical tail. This produces nonzero push probability at integer lines without inventing a manual push rate. Validate the mass around football key numbers and overtime separately.

Empirical residual candidates must use out-of-fold residuals from past games only. Never estimate residual shape from the locked test outcomes and then score those same outcomes.

## 6. Early-season and offseason architecture

Weeks 0–3 must carry quantitatively wider epistemic uncertainty. Candidate preseason state is built from separately testable priors:

- regressed prior-season team strength;
- multi-year program strength;
- returning production;
- prior QB attempts/efficiency and projected QB continuity;
- recruiting/talent composite;
- transfer gains/losses with explicit coverage flags;
- NFL departures;
- head coach/coordinator/system continuity; and
- promoted/reclassified team indicator.

Do not add these as hand-authored points. Fit their contribution to preseason latent strength using prior seasons. Blend prior and current-season evidence dynamically through sample size or a learned state-space/update rule. Week number alone is an imperfect proxy; number of qualifying plays, opponents faced, and schedule connectivity are better uncertainty inputs.

Required experiments:

- prior-only prediction before Week 0;
- prior plus one/two/three games;
- fixed versus learned decay of preseason prior;
- features with and without market state;
- performance for new QB, new head coach, high transfer turnover, and missing-roster cohorts.

## 7. Calibration

Calibration is fitted only on chronological out-of-fold predictions, never on the locked test season. Evaluate:

- Platt/logistic scaling as the low-variance binary baseline;
- beta calibration for asymmetric probability distortion;
- isotonic regression only with adequate calibration sample size;
- location/scale correction and PIT diagnostics for margin/total distributions;
- empirical residual calibration by season and horizon.

Beta calibration is a useful challenger because isotonic can overfit small calibration sets and ordinary logistic calibration cannot represent every common distortion: [Kull, Silva Filho, and Flach](https://proceedings.mlr.press/v54/kull17a.html).

Calibration across arbitrary lines must preserve monotonicity and home/away complementarity. Prefer distribution-level calibration or one symmetric selection transform rather than fitting unrelated calibrators at every spread value. Push-capable outputs require three mutually exclusive probabilities that sum exactly to one.

Version each calibrator with model version, target, horizon, training rows/seasons, fitted parameters, clipping used only for scoring, and artifact hash.

## 8. Uncertainty

Do not emit ungrounded HIGH/MEDIUM/LOW labels. Preserve numerical components:

- `predictive_mean_points`;
- `predictive_sd_points` or calibrated quantiles;
- `aleatoric_variance` from residual outcome variation;
- `epistemic_variance` from fold/model/bootstrap disagreement where estimable;
- `model_disagreement_sd`;
- `calibration_interval_width`;
- `data_completeness_fraction` and explicit missingness flags;
- `effective_team_sample` (games/plays and opponent connectivity);
- `market_dispersion` and contributing-book count; and
- flags for new QB/coach, roster turnover, uncertain availability, or forecast age.

Phase 6 may later use a conservative edge distribution, lower credible bound, or bounded confidence multiplier. Phase 5A does not choose the staking transformation.

## 9. Explainability

Explanations must be generated from the actual model input row and artifact:

- Ridge: standardized coefficient × feature-value contribution.
- Elo: pregame ratings, home adjustment, and update history.
- Trees: offline SHAP values plus permutation importance and fold stability.
- Bayesian: posterior contrasts and credible intervals.

Store structured explanation facts before rendering prose:

```text
feature_name, feature_version, value, reference_value,
signed_contribution, explanation_method, source_ids
```

Separate three sections in any future UI:

1. model contributors actually consumed;
2. market comparison; and
3. research context/warnings not consumed by the model.

An LLM may verbalize this structure but cannot invent a driver or adjust probability.

## 10. Training and inference architecture

Training should run offline on a developer machine or bounded batch job, not in the Render web request:

```text
versioned source manifests
  -> as-of feature builder
  -> chronological folds
  -> candidate training/calibration
  -> evaluation report
  -> immutable artifact + hashes
  -> registry status: experimental/candidate/shadow/production/retired
```

Future inference can run inside FastAPI because the initial Ridge/Elo/tree artifacts are small and CPU inference is cheap. The service should load one approved artifact at startup and fail closed if its schema/hash/version is incompatible. A separate worker becomes justified for scheduled feature refresh, bulk inference, or heavier Bayesian training—not for synchronous single-game inference.

Do not pickle arbitrary untrusted objects. Prefer transparent JSON for linear/Elo parameters and a library-native safe format or ONNX where faithfully supported for trees. Record library/runtime versions and verify a golden prediction fixture before promotion.

## 11. Model registry and lifecycle

Registry metadata belongs in PostgreSQL; large feature/model artifacts remain immutable files or object-store objects referenced by URI and SHA-256:

- model name/version and family;
- target and prediction horizon;
- feature-set/schema version;
- source dataset/manifests and hashes;
- training cutoff and seasons;
- code commit;
- hyperparameters and random seeds;
- distribution and calibration versions;
- metrics overall and by predefined segments;
- artifact URI/hash/format/runtime;
- creation time and creator/process;
- status and promotion/retirement reason.

Lifecycle:

```text
experimental -> candidate -> shadow -> production -> retired
```

Transitions are explicit records. No model silently replaces another, and historical predictions remain tied to their producing version.

## 12. Promotion gates

A model may produce shadow predictions before it may influence paper recommendations. Promotion requires all of the following:

1. Dataset, feature, code, model, distribution, and calibrator versions reproduce from immutable manifests.
2. Automated leakage and as-of boundary tests pass.
3. Hyperparameters and calibrators were selected without the locked test season.
4. At least two seasons of truly out-of-sample evidence are available before recommendation influence; until then the model remains shadow/experimental.
5. A market-aware candidate improves both mean log loss and Brier score versus the same-horizon Phase 4 consensus, with a predeclared practical threshold and a paired week/season block-bootstrap interval that excludes material degradation.
6. Margin/total point and distribution metrics beat the naive and Elo baselines; market residual must show incremental signal after market expectation.
7. Calibration intercept/slope, reliability, and interval coverage meet predeclared tolerances overall and do not collapse in Weeks 0–3.
8. Results are directionally stable across seasons, major conference groupings, favorite/underdog, home/away, and probability/line buckets; sparse segments are reported, not overinterpreted.
9. No severe failure exists under missing data, new QB/coach, large roster turnover, or high market-dispersion cases.
10. Shadow operations produce reproducible predictions and explanations without changing Phase 4 outputs.

Numeric practical-effect and calibration tolerances remain unresolved until Phase 5B measures baseline variability. They must be frozen before opening the final holdout. ROI, hit rate, or a recent winning streak cannot substitute for these gates.

## 13. Major risks and falsification questions

- **Historical odds gap:** without fixed-horizon market snapshots, residual/blend claims are not valid.
- **Backfilled sports data:** current endpoint values may contain corrections or retrospective metrics unavailable at prediction time.
- **NCAAF turnover:** player/team identities and roster state are discontinuous across seasons.
- **Injury coverage:** league-wide historical availability is incomplete and provider-dependent.
- **Weather leakage:** final observed weather is not the forecast known at decision time.
- **Provider licensing:** open-source code licenses do not automatically license upstream ESPN or recruiting data for production redistribution.
- **Small effective sample:** thousands of games become far fewer independent seasons/regimes; model searches can overfit.
- **Market strength:** a model can be useful for explanation or uncertainty while failing to beat consensus. That is a valid negative result.

Phase 5B should answer: Does an independent model add stable information? Does residual learning improve the market? Which distribution calibrates at key lines? Which early-season priors reduce error without hiding uncertainty? If the answers are negative, keep consensus as final fair probability.

## 14. Resolved constraints and remaining decisions

Approved for Phase 5B planning:

- one game-day-morning operational run, with exact convention selected after the coverage audit;
- separate 60-minute and 24-hour research horizons;
- 2025 as the untouched locked test and 2026 as prospective shadow evidence;
- only a bounded historical-odds audit before any full acquisition;
- CFBD as the primary MVP source, starting on its free tier with immutable caching;
- injuries/weather as later coverage and ablation tracks rather than baseline blockers; and
- offline training with lean PostgreSQL metadata plus immutable Parquet/model-native artifacts.

Still unresolved: the exact morning convention and audit tolerances; the SportsDataverse upstream-use determination; conservative availability rules for reconstructed fields; the operational 2025 access seal; numeric promotion tolerances; and whether evidence beyond one locked plus one shadow season is required. See `NCAAF_SOURCE_AUDIT.md`.

## Related specifications

- `NCAAF_DATA_SOURCES.md`: source coverage, access, licensing, cost tiers and minimum dataset.
- `NCAAF_SOURCE_AUDIT.md`: Phase 5B-0 measurements, identity/target contracts, bounded provider audits, costs and go/no-go gates.
- `NCAAF_FEATURE_CATALOG.md`: feature definitions, timestamps, provenance, missingness and model eligibility.
- `NCAAF_BACKTEST_DESIGN.md`: cutoff semantics, chronological folds, leakage controls, metrics and evidence rules.
- `NCAAF_EXPERIMENT_PLAN.md`: concrete experiment matrix and Phase 5B implementation order.
> Phase 5B-5 implementation note (2026-08-30): the controlled tree tournament and empirical-discrete key-number experiment are complete offline. No margin tree displaced the power rating; CatBoost total advanced only as a point challenger; Ridge empirical remains the total probability benchmark; empirical-discrete margin advances for offline evaluation. See [`NCAAF_STRONG_MODEL_REPORT.md`](NCAAF_STRONG_MODEL_REPORT.md).
