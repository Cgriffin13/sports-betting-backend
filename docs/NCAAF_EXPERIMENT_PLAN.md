# NCAAF Experiment Plan

Status: **Phase 5A plan; no experiment below has been run.** IDs and hypotheses are durable. Exact hyperparameter grids and promotion tolerances are frozen in a preregistered run manifest after the data audit and before the locked test is opened.

## Decision sequence

The tournament is deliberately staged. A model family earns additional complexity only after its data and simpler comparator work.

1. Prove event, target and point-in-time feature correctness.
2. Establish naive and sequential rating floors.
3. Establish interpretable margin/total distributions with Ridge.
4. Screen tree libraries under one bounded budget.
5. Compare distribution and calibration choices.
6. Acquire/audit fixed-horizon odds, then test market residual and market-as-feature candidates.
7. Test learned blends only from chronological out-of-fold predictions.
8. Run locked test once, then shadow prospectively.

## Initial experiment matrix

| ID | Target | Feature set | Candidate | Market input? | Distribution / calibration | Primary comparison |
| --- | --- | --- | --- | --- | --- | --- |
| D001 | Margin/total | targets only | Historical unconditional mean/variance by season regime | No | Empirical prior | Pipeline sanity floor |
| D002 | Margin/total | `ncaaf_basic_v1` | Exponentially weighted team differential + learned HFA | No | OOF empirical residual | Naive baseline |
| E001 | Home win / margin | prior results, venue | Standard Elo | No | Logistic Elo + calibration audit | D002 and market ML |
| E002 | Margin | results/MOV, venue | MOV-adjusted Elo | No | OOF empirical margin residual | E001/D002 |
| R001 | Margin | `ncaaf_basic_v1` | Ridge | No | Normal then OOF empirical | D002/E002 |
| R002 | Total | `ncaaf_basic_v1` | Ridge | No | Normal then OOF empirical | D002 |
| R003 | Margin/total | `ncaaf-efficiency-point-in-time-v1` | Ridge | No | Best prior distribution, recalibrated | R001/R002 ablation |
| R004 | Margin/total | efficiency + compact matchup interactions | Elastic Net | No | Same as R003 | Ridge; coefficient stability |
| P001 | Home/away points jointly | `ncaaf-efficiency-point-in-time-v1` | Two Ridge component models | No | Correlated OOF score residual simulation | Direct margin/total models |
| T001 | Margin/total | `ncaaf-efficiency-point-in-time-v1` | XGBoost | No | OOF empirical / best common calibrator | R003 under equal budget |
| T002 | Margin/total | same | LightGBM | No | Same protocol | R003/T001 |
| T003 | Margin/total | same | CatBoost | No | Same protocol | R003/T001/T002 |
| U001 | Margin/total | winning linear/tree features | Best simple candidate | No | Normal vs Student-t vs empirical residual | NLL/CRPS/calibration |
| U002 | Margin/total | same | Heteroskedastic location-scale or NGBoost challenger | No | Conditional scale/distribution | U001; tail/coverage gain |
| S001 | Margin/total | `ncaaf_preseason_v1` | Ridge / winning tree | No | Winning distribution | Weeks 0–3 and prior-only ablation |
| M001 | Margin residual to fixed-horizon spread | efficiency + preseason + `ncaaf_market_v1` quality | Ridge | Yes, residual target | OOF residual distribution | Same-horizon consensus |
| M002 | Total residual to fixed-horizon total | same | Ridge | Yes, residual target | OOF residual distribution | Same-horizon consensus |
| M003 | Margin/total residual | same | Winning tree | Yes, residual target | Winning calibrator | M001/M002 and consensus |
| M004 | Margin/total | full + market state | Ridge / winning tree | Yes, direct feature | Winning calibrator | Residual architecture |
| W001 | Moneyline | football features | Logistic Ridge direct classifier | No | Platt vs beta | Margin-derived probability |
| B001 | Line probability | OOF market + independent model | Constrained logistic stack on log-odds | Yes, learned blend | Beta/distribution calibration | Best single component |
| B002 | Margin/total | market + residual candidate | Uncertainty-conditioned shrinkage, low degrees of freedom | Yes | Winning calibrator | B001; only if sample supports |
| H001 | Margin | compact features | Dynamic hierarchical team/conference model | No | Posterior predictive | Ridge/Elo, early-season uncertainty |

The first computational commitment ends at R003 and E002. Run T001–T003 as a small screen with identical folds, features, search trials, seeds and wall-time cap. Continue only the best operationally acceptable tree, unless differences are within uncertainty—in which case prefer the simpler artifact. H001 is deferred until baseline residuals demonstrate a pooling question worth its cost.

## Ablation matrix

For each winning model, remove exactly one predeclared family:

- opponent adjustments;
- EPA/success features;
- explosives/finishing drives;
- tempo;
- preseason/team-continuity features;
- coaching;
- matchup interactions;
- market state (market-aware candidates);
- weather; and
- availability/news.

Only run weather and availability ablations after coverage audits. Report common-row comparisons and changed coverage. A family with unstable or negligible forward value is dropped even if individual feature importance looks impressive.

## Early-season experiments

S001 expands into four frozen variants:

1. fully regressed prior-season rating only;
2. prior plus recruiting/talent and returning production;
3. prior plus QB/coach/transfer continuity;
4. best prior with current-season evidence weighted by effective plays/games.

Evaluate preseason (before Week 0), after one, two and three games, and Weeks 4+. Compare mean errors, proper scores, calibration and predictive interval coverage. Estimate uncertainty from posterior/bootstrap/fold dispersion and residual scale; do not assign subjective confidence labels.

## Distribution and push experiments

U001 compares normal, Student-t and out-of-fold empirical residuals for each target/horizon. It must report:

- NLL and CRPS;
- PIT/reliability and 50/80/90/95% coverage;
- tail errors and key-number probability mass;
- line Brier/log loss; and
- integer-line win/push/loss calibration.

U002 proceeds only if residual scale visibly changes with week, feature completeness, favorite magnitude, tempo, roster continuity or market dispersion. Quantile/distributional models must preserve a coherent monotone CDF. Component-score simulation must model covariance; independent home/away score draws are not accepted without evidence.

## Market architecture experiments

M001–M004 require audited exact historical market state at the same cutoff as the football features. Run separate game-day-morning, 24-hour, and 60-minute experiments; opening remains exploratory until consistently defined. Morning, 24-hour, and 60-minute results may not be combined or substituted. For every row retain market policy version, book count/dispersion, observation IDs and snapshot IDs.

M001/M002 test the most interpretable incremental hypothesis. M003 tests nonlinear residual interactions. M004 tests whether direct inclusion is more accurate but must expose reliance on the market. Compare all on the identical eligible intersection and separately report coverage.

The independent model remains in the report even if worse. Its error diversity is necessary to evaluate complementarity. A closing line is evaluation-only for earlier horizons.

## Ensemble experiments

B001 receives only chronological out-of-fold component predictions. Candidate inputs are market log-odds, model log-odds, and at most a small set of predeclared quality/uncertainty interactions. Apply constrained/regularized stacking and calibrate in a later fold.

B002 may condition shrinkage on early season, effective team history, QB/roster uncertainty, market book count/dispersion and model predictive scale. It is allowed only if B001 has stable gain and each regime retains sufficient OOS support. There is no fixed 50/50 blend and no forced blend.

## Tuning budget and selection

- Naive/Elo/Ridge: small explicit grids selected on inner forward folds.
- Elastic Net: bounded alpha/l1-ratio grid.
- Each tree library: same number of trials, seeds, maximum depth/leaves, early-stopping protocol and CPU/wall-time budget.
- Bayesian/distributional: preregistered compact specifications, not open-ended posterior shopping.
- Transformations, feature selection and calibration are fitted in-fold.
- Primary selection uses proper probabilistic score plus calibration and operational constraints; point metrics are supporting evidence.

Preserve all trials, including failures. The 2025 holdout is opened once after the candidate and practical-effect rule are frozen.

## Required reports per experiment

Each report contains:

- hypothesis and falsification condition;
- dataset/feature/model/calibration manifests and hashes;
- exact folds, horizons, exclusions, coverage and missing reasons;
- point, distribution, line-probability and calibration metrics;
- same-horizon market comparison where available;
- predeclared segment metrics with counts/intervals;
- runtime, peak memory, artifact size and inference latency;
- explanation examples generated from actual features;
- leakage/time-travel test results;
- whether the result advances, repeats or rejects the hypothesis; and
- next action without consulting the locked test.

## Phase 5B implementation sequence

### 5B-0 — source and identity audit

**Completed as a conditional-go research audit on 2026-08-29.** `NCAAF_SOURCE_AUDIT.md` records public coverage, identities, targets, timing classifications, costs, and frozen provider-audit designs. The CFBD credentialed gate was subsequently completed in 5B-1. Phase 5B-7A then executed the historical-odds gate for 2,010 credits under its 2,280-credit ceiling.

### 5B-1 — historical facts ingestion

**Completed on 2026-08-29.** Versioned, idempotent ingestion covers calendars, schedules/results, teams/conferences, venues, plays/drives, game team stats, manifests, identities, targets, exclusions, reports, safe resume, and the 2025 holdout gate. PostgreSQL stores canonical/time-sensitive indexes; lossless partitioned canonical-JSON gzip stores raw bulky PBP. Rosters/coaches/personnel and all model code remain deferred.

### 5B-2 — as-of features and dataset builder

**Completed on 2026-08-29.** The offline builder emits normalized Parquet facts, three distinct horizon matrices, explicit missingness/quality, prior-only rolling/opponent adjustment, early-season shrinkage, chronological fold metadata, immutable manifests, and leakage/time-travel tests. The feature set is `ncaaf-efficiency-point-in-time-v1`. It does not fit imputation, select columns, train a model, or claim predictive performance.

### 5B-3 — falsification baselines

Implemented 2026-08-29 as `ncaaf-baseline-tournament-v1`: training-mean, home-field, prior-team-average, chronological margin power rating, and Ridge margin/total regressions. The Ridge alpha grid is `{0.1, 1, 10, 100}` and selection uses 2019–2023 development OOF only. Five predeclared feature views test context/priors, raw efficiency, opponent-adjusted, full v1, and full without opponent adjustment. Separate exclusion runs assess 2014 and 2021–2022 training sensitivity. The three horizons remain separate and were fitted independently after exact comparison showed small point-in-time input differences.

Elastic Net's bounded grid was attempted but did not converge reliably on the wide v1 matrix. It is deferred rather than promoted or reported with unstable metrics. Trees, probability distributions, calibration, historical markets, and blending remain later experiments.

Run D001/D002, E001/E002 and R001–R003 using chronological folds. Establish evaluation/reporting and OOF prediction artifacts before adding sophistication.

### 5B-4 — distribution/calibration foundation

**Completed offline on 2026-08-30.** U001 compared predeclared Normal, Student-t, empirical residual, quality-grouped scale, and total skew-normal candidates with strict prior-season residual pools. Integer-score discretization now produces moneyline and spread/total win/push/loss probabilities, and the run reports NLL, CRPS, intervals, PIT, buckets, key numbers, regimes, quality, and paired uncertainty. Quality-aware Normal margin and empirical-residual total advance only to later offline comparison; no production exposure or market claim exists.

The frozen design and measured evidence are in `NCAAF_DISTRIBUTION_EXPERIMENT_PLAN.md` and `NCAAF_PROBABILITY_CALIBRATION_REPORT.md`. A margin empirical-discrete key-number challenger and any post-hoc binary transform require a new predeclared experiment.

### 5B-5 — controlled challengers

Completed offline on 2026-08-30 under [`NCAAF_STRONG_MODEL_EXPERIMENT_PLAN.md`](NCAAF_STRONG_MODEL_EXPERIMENT_PLAN.md). The equal-budget tournament retained the margin power rating, advanced CatBoost total only as a point challenger, retained Ridge empirical as the total probability benchmark, and advanced chronological empirical-discrete margin mass for offline key-number/push research. See [`NCAAF_STRONG_MODEL_REPORT.md`](NCAAF_STRONG_MODEL_REPORT.md).

Run R004/P001 and bounded T001–T003. Advance at most one tree family unless evidence distinguishes more. Run U002 only if heteroskedasticity evidence justifies it.

### 5B-6 — preseason and personnel

**Implemented offline on 2026-08-30.** The source plan was frozen before 68 bounded CFBD calls. `ncaaf-preseason-personnel-v1` materializes reconstructed returning-production, roster/QB continuity, transfer, recruiting/talent, head-coach, and quality fields, then runs S001 through the existing expanding folds. Results and advancement decisions are recorded in `NCAAF_PRESEASON_MODEL_REPORT.md`; injury/weather remain separate future audits.

### 5B-7 — historical market comparison

Phase 5B-7A completed the predeclared sample with 76 logical/67 unique requests and 2,010 credits. Phase 5B-7B then built the complete 2020–2024 FBS-vs-FBS morning h2h/spread/total corpus and a separately predeclared, outcome-blind 60-minute/near-close robustness cohort. The morning cohort is the primary basis for M001–M004 and W001. Later-horizon rows are secondary diagnostics only and must not be pooled with morning or portrayed as full-cohort evidence. Do not include 24h or near-close h2h. Reuse `the-odds-api-provider-archive-snapshot-v1` and evaluate only events passing reliable identity, cutoff, paired-market, and two-supported-book gates.

### 5B-8 — blend and locked evaluation

Run B001 and only justified B002; freeze the complete selection/promotion rule; evaluate 2025 once. A candidate may advance to shadow but not production recommendation influence.

### 5B-9 — registry and prospective shadow

Implement model/run/calibrator registry, immutable artifact verification, offline batch inference and 2026 prospective shadow predictions. Compare operational coverage, calibration and market increment without changing `/opportunities` fair probability.

### 5B-10 — production-inference decision

Only after promotion gates pass, design a separately reviewed API integration that exposes market, proprietary and final probabilities distinctly. A negative decision retains Phase 4 market consensus.

## Approved constraints and remaining human decisions

Approved: CFBD primary MVP/free-tier-first; a small historical-odds audit before full acquisition; one game-day-morning operational run; separate 60-minute and 24-hour research horizons; locked 2025 and prospective 2026; offline training; PostgreSQL metadata plus immutable Parquet/artifacts; and injuries/weather as later ablation tracks.

Remaining decisions include the scope/cost ceiling of the next approved historical acquisition, upstream SportsDataverse-use determination, production-grade 2025 access-seal mechanism, numeric promotion rule, and whether longer shadow evidence is required. The morning convention and audit tolerances are now resolved. The reconstructed CFBD delay is fixed for v1 at kickoff plus 24 hours and may become stricter only through a new version.

## Explicit non-deliverables

This plan does not implement a production model, proprietary probability in `/opportunities`, staking, portfolio allocation, parlays, automated execution, a web UI or arbitrary LLM probability adjustments.
