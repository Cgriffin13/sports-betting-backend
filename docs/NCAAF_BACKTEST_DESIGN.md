# NCAAF Backtest Design

Status: **Phase 5A experimental protocol.** This document governs model research; it does not describe an implemented outcome backtest. Phase 4 implements deterministic pricing replay only.

## Objective and estimands

The primary question is not “did a betting simulation make money?” It is whether a candidate produces calibrated, reproducible incremental information at a specified decision horizon.

Predeclare separate estimands:

1. point accuracy for final margin and total;
2. distribution quality for margin and total;
3. line-level win/push/loss probability quality;
4. incremental probability quality versus same-horizon market consensus;
5. closing-line relationship when a valid later close exists; and
6. eventual risk-adjusted portfolio performance under a separate frozen staking policy.

Only 1–5 belong in the Phase 5 model tournament. Portfolio simulation belongs to Phase 6.

## Point-in-time row contract

One evaluation row represents one canonical game and one declared prediction horizon. Its cutoff is:

```text
as_of = scheduled_start_at - horizon
```

For every source record used:

```text
effective_at <= as_of
observed_at  <= as_of
ingested_at  <= as_of
```

Where a reconstructed historical dataset lacks a genuine historical ingestion timestamp, mark `availability_mode = reconstructed` and apply a source-specific conservative publication rule. Such a row may support exploratory football-model research but cannot claim strict live replay equivalence. The report must separate contemporaneously captured and reconstructed evidence.

Phase 3 market replay retains both observation-time and ingestion-time boundaries. A provider update observed before cutoff but ingested afterward is unavailable. Final scores, corrections, closing lines, realized weather and later roster/injury states are labels or evaluation data only.

## Prediction horizons

Evaluate these distinct snapshots where data permits:

- opening proxy, with an explicit source-specific definition;
- 24 hours before kickoff;
- game-day morning at a declared UTC/local convention;
- 60 minutes before kickoff; and
- last eligible pre-start snapshot (“close”), for evaluation only.

Recommend **60 minutes pre-kickoff** as the first operational paper-recommendation horizon: it captures much current information while leaving a plausible execution window. It is a hypothesis. The 24-hour horizon tests whether the system has earlier actionable signal. Do not mix horizons in one metric or fill a missing 60-minute observation with a closing price.

## Dataset and season plan

Detailed PBP is practically strongest from 2014 onward, while exact The Odds API history begins in 2020. Use two linked tracks:

### Independent-football track

- 2014–2018: feature warm-up and earliest expanding-window training where coverage passes audit;
- 2019–2023: walk-forward development folds;
- 2024: validation/model-selection season;
- 2025: locked final test season;
- 2026: prospective shadow season.

### Market-aware/residual track

- 2020–2023: expanding-window development, constrained by purchased market coverage;
- 2024: validation/model-selection season;
- 2025: locked final test;
- 2026: prospective shadow.

The exact first year can move after the coverage audit. The logical roles cannot. If only one credible untouched season remains, do not use it repeatedly; keep it locked and require a later shadow season before recommendation influence.

## Walk-forward protocol

For evaluation season `S`:

1. Train transformations and model only on seasons/games strictly before the row cutoff, normally through `S-1` plus earlier completed games in `S` only when the deployment design supports in-season refits.
2. Fit imputation, scaling, encoding, opponent adjustment and feature selection inside the training fold.
3. Tune hyperparameters with inner chronological folds, not random cross-validation.
4. Generate untouched predictions for `S` in chronological order.
5. Fit calibrators on prior out-of-fold predictions only.
6. Freeze prediction, explanation, source manifest and artifact hashes before attaching outcomes.

Compare expanding windows with a bounded rolling window as a predeclared experiment. Expanding is the default because NCAAF has a modest sample; recency decay and offseason state may handle nonstationarity without discarding history.

Random train/test splits are prohibited as primary evidence. Team-aware random grouping still leaks season/regime information and is not a substitute for time.

## Leakage controls

Automated tests and dataset audits must reject:

- season averages or ratings that include the target game;
- end-of-season summaries used for earlier games;
- opponent strength using the opponent's future results;
- a closing or later line in an earlier-horizon input;
- final injury/roster/depth-chart state before its report time;
- weather observations/reanalysis used instead of the forecast run available at cutoff;
- retrospective team/player identity or transfer corrections silently backfilled;
- postgame statistical corrections ingested after cutoff;
- target-derived encoders or imputation fitted across the validation/test period;
- calibration on the same outcomes being scored;
- selection of features/hyperparameters after viewing the locked test; and
- duplicate games or provider-event aliases crossing folds.

Required boundary fixtures include records exactly at, one microsecond before and one microsecond after `as_of`, plus late ingestion. A “time travel” test must recompute an old row after new data arrives and obtain the same features and prediction.

## Targets and probability scoring

```text
margin = home_points - away_points
total  = home_points + away_points
```

Score margin and total point estimates with MAE, RMSE, median error, residual standard deviation and predefined tail quantiles. Report by season and Weeks 0–3 versus later weeks.

Score predictive distributions with negative log likelihood, CRPS, probability integral transform diagnostics, central interval coverage/width and tail calibration. After discretizing onto integer scores, derive for every tested line:

```text
P(win), P(push), P(loss)
```

They must be nonnegative and sum to one. Half-points have zero push mass; integer lines retain it. Score non-push binary outcomes with Brier/log loss and push-capable outcomes with a declared multiclass/proper score. Never drop pushes after seeing results.

## Calibration protocol

Candidate calibrators:

- distribution location/scale correction;
- empirical out-of-fold residual distribution;
- Platt/logistic scaling for binary checks;
- beta calibration for asymmetric distortion; and
- isotonic regression only when calibration sample size supports it.

Fit calibration artifacts only on prior out-of-fold predictions. Version target, horizon, source model, training cutoff/rows, algorithm, parameters and hash. For each candidate report calibration intercept/slope, reliability diagram, Brier decomposition when practical, expected calibration error with fixed bins, and uncertainty intervals. ECE is descriptive and bin-sensitive, not a sole selection metric.

## Market comparison

At the exact prediction horizon:

1. Build Phase 4 consensus from eligible fresh unambiguous exact-line observations.
2. Use the same game/selection outcome for market and candidate.
3. Compare paired Brier and log-loss differences on the intersection where both exist.
4. Report coverage separately; never improve a score by abstaining on hard rows without showing abstention.
5. Block-bootstrap differences by week and season to respect shared shocks and clustered games.
6. Compare model-minus-market margin/total residual, line probability and calibration.

A market-independent model can be valuable without beating consensus everywhere if its errors differ and a locked out-of-fold blend improves proper scores. That complementarity must be learned, not inferred from correlation alone.

## Closing-line evaluation

When an auditable close exists, record:

- prediction/entry cutoff and executable observation;
- closing consensus and best comparable line/price;
- exact market identity and any line movement;
- model probability/edge at entry; and
- whether predicted direction moved toward close.

CLV is a market-quality diagnostic, not ground truth and not yet implemented. A later close cannot enter the earlier prediction. Line changes require price-aware comparison rather than treating -3.5 and -4 as identical.

## Segments and multiplicity

Always report predeclared segments:

- season;
- Weeks 0–3 versus later;
- conference grouping and cross-conference games;
- favorite/underdog and home/away;
- market probability and line buckets;
- QB/coach continuity and roster-turnover cohorts;
- data completeness;
- market book count/dispersion; and
- prediction horizon.

These diagnose failure, not invite picking winners. Mark small samples with counts and intervals. Exploratory slices discovered after results are hypotheses for a future season, not evidence for the current promotion.

## Statistical comparison

- Compare every candidate to naive, Elo and same-horizon market baselines.
- Use paired game-level losses and week/season block bootstrap confidence intervals.
- Report mean, median, dispersion, sample size and coverage—not only a p-value.
- Define a smallest practical improvement after development variance is measured and freeze it before opening 2025.
- Correct or control the interpretation of many candidate/tuning comparisons; the locked test is evaluated once under the frozen selection rule.
- Preserve all failed experiments to reduce repeated researcher degrees of freedom.

No model is selected on betting ROI alone. ROI is high variance, sensitive to assumed fills and staking, and easily data-mined. It is reported later as secondary evidence with drawdown and uncertainty.

## Missing data and abstention

For each feature/source, distinguish structural absence, provider failure, not-yet-reported, not-applicable and stale. Imputation is learned only in-fold and paired with missing indicators. Models may abstain when a predeclared data-quality gate fails. Reports show:

- total eligible games;
- prediction coverage;
- reason counts for abstention;
- metrics on common intersection and full model coverage; and
- sensitivity to excluding reconstructed data.

Abstention thresholds are frozen before holdout and may not be loosened to manufacture recommendations.

## Reproducibility outputs

Every run writes an immutable manifest containing:

- run/experiment ID and code commit;
- source object/version/hash and extraction time;
- event universe and exclusions;
- feature-set/schema version;
- cutoff/horizon semantics;
- fold assignment;
- model/hyperparameters/seeds/runtime versions;
- distribution/calibrator versions;
- prediction and explanation artifact hashes;
- evaluation code/version and all metrics; and
- status (`research`, `candidate`, `shadow`, etc.).

PostgreSQL should store registry/run metadata and point-in-time source indexes. Partitioned Parquet is appropriate for immutable raw play data, feature matrices and out-of-fold predictions. Large artifacts are referenced by URI/hash, not stored as ORM blobs. This is a modest research lake, not a distributed platform.

## Promotion evidence

Before affecting paper recommendations, a candidate needs reproducible as-of data, leakage tests, frozen hyperparameters/calibration, stability across predefined segments, and at least two genuinely out-of-sample seasons (for example a locked 2025 test plus 2026 shadow). A market-aware candidate must improve mean Brier and log loss over same-horizon consensus under a predeclared practical threshold and paired interval, without material calibration or segment failures.

Exact numeric thresholds and minimum game counts remain unresolved until Phase 5B measures variance. Freeze them before evaluating the final holdout. A negative result—keeping market consensus—is valid.

## Pricing replay versus outcome backtest versus portfolio simulation

- **Pricing replay (implemented Phase 4):** reconstruct consensus and EV known at cutoff.
- **Outcome/model backtest (designed here):** join frozen predictions to later game outcomes and evaluate probability/model quality.
- **Portfolio simulation (Phase 6):** add executable entry assumptions, stake/risk policy, correlated exposure, bankroll path and settlements.

Do not call pricing replay a profitable backtest, and do not infer a staking policy from Phase 5 model metrics.
