# NCAAF v1.1 Production Scoring Gate

Status: **BLOCKED — DO NOT MERGE FOR WEEKEND USE**

Machine-readable result: [`reports/NCAAF_V11_PRODUCTION_SCORING_GATE.json`](reports/NCAAF_V11_PRODUCTION_SCORING_GATE.json).

## Decision

The requested v1.1 proprietary-football promotion run cannot satisfy its own locked-holdout contract. The 2025 season was opened exactly once on August 31, 2026, after Phase 5B-8 froze the then-eligible candidates. That evaluation failed, retained market consensus, and explicitly prohibited replacement-candidate search or retuning based on the now-visible 2025 outcomes.

Designing Ridge, Elastic Net, boosting, feature, calibration, blend, or cohort choices after observing that result and then calling 2025 a locked holdout would be future-evidence reuse, not an out-of-sample promotion test. No untouched completed evaluation season remains: 2024 already served model-selection/validation, 2025 has been opened, and 2026 is prospective shadow evidence with incomplete outcomes.

The v1.1 specification also requires the run to fail clearly if the 2025 holdout fails. That condition is already met. The branch therefore makes no model, registry, fair-value, recommendation, risk, staking, parlay, API, schema, or frontend change.

## Evidence checked

The existing research inputs are substantial and leakage-aware, but they do not create a new holdout:

- Development corpus: 2014–2024, 8,277 eligible FBS-vs-FBS rows per horizon under `ncaaf-efficiency-point-in-time-v1`.
- Feature-set hash: `0d4d5b3e9996c5682bc6e5366f70c4a82fd80fce8a3ebaa8db7a6ee22bc446ad`.
- Development dataset hash: `b2f7444e2a7451d90c9078fb3b694d1586b1d30dd7f9c3a60b869381532b8bfe`.
- Existing football families already evaluated chronologically include naive means, power ratings, Ridge, Elastic Net, CatBoost challengers, preseason/personnel variants, residual models, market-as-feature models, and constrained blends.
- Implemented football inputs include lagged efficiency, PPA/EPA proxies, pass/rush efficiency, success/explosiveness, yards/play, yards/drive, points/drive, pace proxies, havoc, prior-only opponent adjustment, home/neutral context, rest, early-season priors, recruiting/talent, returning production, roster/QB continuity proxies, transfers, coach continuity, and explicit quality/missingness fields.
- Point-in-time weather, verified injury availability, and historically published rankings are not production-ready feature families. They remain missing rather than being invented or retrospectively backfilled.

## Locked 2025 result

The immutable Phase 5B-9 run hash is `e32e8102de3ac51d1a5690fd6cd3e680fa36d9424060784be645c80d8e526256`; its pre-access freeze hash is `5aff62fe0faf9a246c49f2e1ad732b4b6bbb412aa084f9ccd1f635aacb498420`.

| Evidence | Market benchmark | Frozen proprietary challenger | Result |
| --- | ---: | ---: | --- |
| Spread MAE, 719 identical games | 11.7914 | football power 13.0355 | diagnostic underperformed by 1.2441 points |
| Moneyline, 724 games | Brier 0.1791; log loss 0.5320 | no promoted proprietary probability | market retained |
| Total MAE, 758 identical games | 12.5251 | constrained blend 12.5306 | improvement -0.0056; failed |
| Total multiclass Brier | 0.5003295 | 0.5003266 | improvement 0.0000029; failed 0.001 gate |
| Total multiclass log loss | 0.6934767 | 0.6934782 | improvement -0.0000015; failed 0.001 gate |

The frozen total blend failed its MAE, Brier, and log-loss promotion gates. The margin power diagnostic also underperformed the spread market benchmark on the identical 2025 cohort. Those facts do not prove that no future football model can add value; they do prove that a new pre-weekend candidate cannot be independently promoted using the already-observed season.

## Registry and production behavior

Registry hash `42bba06ef7165127615ae3724db4c333655581f41c076b63ab2748b1cbc64418` remains unchanged:

- four `retained_benchmark` market-consensus entries for margin, moneyline, spread, and total;
- two `diagnostic` football entries;
- one `rejected` constrained market/Ridge total blend.

No proprietary model is relabeled or substituted into the fair-value interface. Market consensus remains the NCAAF v1 benchmark. Existing football artifacts may continue producing explicitly diagnostic shadow outputs, but they cannot drive production EV, qualification, Kelly sizing, ranking, approval, or parlays.

## Live board and provider budget

The requested live call was conditional on historical validation and model selection completing successfully. That precondition failed, so making a billable live request could not rescue the promotion decision and would provide current-slate data that the specification forbids using for tuning.

- Odds API calls: **0**
- Odds API credits: **0**
- CFBD calls: **0**
- Thursday board: **NOT RUN**
- Friday board: **NOT RUN**
- Saturday board: **NOT RUN**
- Top-ten opportunities, ranked/primetime analysis, and stakes: **NOT RUN**
- Bets, approvals, and ledger mutations: **0**

This is a research-governance failure, not a claim that the live ingestion/pricing path is unhealthy.

## Valid path forward

1. Keep market consensus as the production fair-value benchmark for the current weekend.
2. Freeze any new v1.1 football specification without consulting 2025 for feature, family, hyperparameter, calibration, blend, or threshold selection.
3. Treat 2025 only as already-observed descriptive evidence, never as a new locked holdout.
4. Generate immutable pregame 2026 shadow predictions prospectively with complete feature/provenance records.
5. Evaluate the frozen candidate after an adequate untouched prospective sample using predeclared practical-effect, calibration, stability, and segment gates.
6. Create a new registry version only if that independent evidence passes. Do not modify the existing v1 history.

No new provider call, schema migration, environment variable, dependency, or production deployment step is required by this gate report.
