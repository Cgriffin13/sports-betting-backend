# NCAAF Finalist Freeze

Status: **Phase 5B-8 frozen on 2026-08-31 without accessing 2025.** This is a pre-holdout research contract, not model promotion, production pricing, or evidence of profitability. Machine contract: [`reports/NCAAF_FINALIST_FREEZE_V1.json`](reports/NCAAF_FINALIST_FREEZE_V1.json), freeze hash `5aff62fe0faf9a246c49f2e1ad732b4b6bbb412aa084f9ccd1f635aacb498420`.

## Frozen slate

| Output | Primary/benchmark | Challenger or diagnostic | Disposition |
| --- | --- | --- | --- |
| Margin / spread / moneyline | `unweighted-median-v1` market consensus | chronological football power, diagnostic only | no proprietary replacement advances |
| Total | market consensus | constrained market + Ridge-no-opponent-adjustment blend | one locked challenger |

Rejected candidates remain rejected: margin residual Ridge, margin market-as-feature Ridge, total residual Ridge/CatBoost, total market-as-feature Ridge/CatBoost, and the preseason CatBoost blend. They cannot enter Phase 5B-9.

The total formula is:

```text
prediction = market_total + 0.17854145992095644 * (football_ridge_total - market_total)
```

The market weight is `0.8214585400790435`. The football component is the existing `develop_through_2023_evaluate_2024` Ridge artifact, trained on 7,479 rows with alpha 100 and `median-indicator-variance-standardize-v1`. Phase 5B-9 must use this artifact and fixed weight without refitting.

## Frozen provenance

- Horizon: `morning_first_kickoff_minus_3h`.
- Market comparison dataset: `cf8669b7f4dd371d12ae03e6e0de180ffb63c196a848a6d7ac791bba8f023bcc`.
- Historical market dataset: `96c3236ea6770e669b351398900b92289a9263cbfe625f3cf986dad235c5274b`.
- Phase 5B-7 dataset: `6305a430fd43d74feaf2dad8d326c809d0c2758521db60e5aaa8cc5502e72fad`.
- Point/probability artifacts: `71c33513361d1065eb9e45fe62fd97759f4350ce0e0a630bf9d0c9b7e22aff03` / `707d836dffd7c689a341efc4720268a4ddcc202f8daccabfa704d76160e9d9f9`.
- Feature dataset/set: `b2f7444e2a7451d90c9078fb3b694d1586b1d30dd7f9c3a60b869381532b8bfe` / `0d4d5b3e9996c5682bc6e5366f70c4a82fd80fce8a3ebaa8db7a6ee22bc446ad`.
- Baseline run and power predictions: `036989b3c5b65226f93f72164e73ec4070b14ca7105d9b55c9e86af9c9778cfb` / `acf300df3e7578039ef26a3da3e9939257095f8100e38cff3776c5a8a10e7e55`.
- Frozen total Ridge artifact: `d41797ed69ea699038f4ba530962611c24799db9ba930daf22c95decff32c167`.
- Vig and consensus: `proportional-v1` and `unweighted-median-v1`, at least two complete supported books and one exact coherent line.
- Probability/push handling: `chronological-empirical-market-aware-v1` plus `integer-lattice-settlement-v1`. Push mass remains separate.

## Total-blend promotion gate

Every condition is required on the identical 2025 common cohort:

1. All hashes and point-in-time checks pass, no later horizon enters, and at least 500 games are evaluable.
2. The blend improves MAE by at least **0.10 points**; RMSE may not degrade by more than **0.10 points**.
3. It improves both multiclass Brier and log loss by at least **0.001**.
4. The paired week-block 90% interval's upper bound for blend-minus-market MAE is at most **+0.05 points**.
5. Weighted calibration error is at most **0.05**, push probabilities remain explicit, and neither proper score is worse than market.
6. Computation remains the single fixed linear blend; no new fit, calibration, dependency, or service is allowed.
7. Predeclared broad-segment degradation stays within the limits below.

The 0.10-point threshold deliberately exceeds Phase 5B-7's 0.026-point gain: statistical detectability alone is insufficient to justify complexity. Failure of any condition retains market consensus.

## Calibration and segment gates

Relative to frozen 2024 references, the market benchmark may degrade by at most 0.02 Brier and 0.04 log loss for moneyline, spread, and total. This is a monitoring/integrity gate, not permission to substitute a rejected model. The total blend additionally may not degrade either proper score relative to market.

Only segments with at least 75 rows are evaluated:

- Weeks 0–3 versus Week 4+;
- dispersion below versus at/above 0.02;
- model/market disagreement 0–3, 3–7, and 7+ points;
- totals below 45, 45–60, and above 60;
- high versus low feature quality.

At most one eligible segment may degrade MAE by more than 0.25 points; no segment may degrade MAE by more than 0.50 points or multiclass Brier by more than 0.01. Sparse segments are reported as unevaluable, not mined for alternatives.

## Phase 5B-9 decision table

| Condition | Decision |
| --- | --- |
| Any artifact, identity, cutoff, cohort, or code-integrity failure | Stop; remediate before interpreting performance. |
| Margin/ML/spread market benchmark passes integrity/calibration gates | Retain market consensus. |
| Football power is stable and correctly labeled | Retain as diagnostic only, regardless of whether it beats market. |
| Total blend passes every practical, proper-score, calibration, interval, and segment gate | Advance to prospective shadow candidate only. |
| Total blend fails or is unevaluable on any required gate | Fall back to total market consensus. |

Market consensus remaining primary does not prohibit future moneyline or spread bets. Phase 6 may compare frozen fair probability with an executable price and require edge, EV, uncertainty, and portfolio-risk qualification. The football diagnostic cannot arbitrarily override the benchmark.

## One-time 2025 protocol

1. Verify this freeze hash and every available source/artifact hash.
2. Require an explicit one-time holdout unlock and immutable access record.
3. Build 2025 football and market inputs under existing point-in-time and identity rules.
4. Reject refitting, recalibration, retuning, candidate additions, and later-horizon substitution.
5. Generate predictions from the exact frozen specifications and artifacts.
6. Evaluate only the predeclared aggregate, proper-score, calibration, uncertainty, and segment gates.
7. Record pass, fail, unevaluable, and fallback decisions before interpretation.
8. Treat a genuine data/code integrity defect as a stop-and-remediate event. Poor performance is not a defect and cannot authorize tuning.

After Phase 5B-9, disappointing results remain immutable evidence. The next evidence stage is prospective 2026 shadow operation. No Phase 5B-8 decision changes Phase 4 APIs, pricing, recommendations, EV, or staking.

## Offline validation

```powershell
python -m app.cli.freeze_ncaaf_finalists build
python -m app.cli.freeze_ncaaf_finalists validate --require-local-artifacts
```

The build and validator do not load `.env`, contact providers, or read 2025 outcomes.
