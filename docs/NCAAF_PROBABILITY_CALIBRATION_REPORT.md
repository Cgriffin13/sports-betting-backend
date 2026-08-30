# NCAAF Probability Calibration Report

Status: **Phase 5B-4 completed offline on 2026-08-30.** This is development-period distribution evidence, not a sportsbook comparison, market edge, betting backtest, production model, or recommendation system. The 2025 holdout remained sealed and provider calls were zero.

## Frozen inputs and protocol

- Phase 5B-3 run: `036989b3c5b65226f93f72164e73ec4070b14ca7105d9b55c9e86af9c9778cfb`
- Dataset: `b2f7444e2a7451d90c9078fb3b694d1586b1d30dd7f9c3a60b869381532b8bfe`
- Feature set: `0d4d5b3e9996c5682bc6e5366f70c4a82fd80fce8a3ebaa8db7a6ee22bc446ad`
- Probability run: `4813f18a64fa5ae0d53038d07947ff47b135107fbf97f03825f25212332ff51b`
- Probability content: `efc02720a6c9eb569805afa224ef2ce8394cd096a235e8db0bd499bbbcf5d915`
- Calibration evaluation: 2020–2024, with 2019 OOF residuals seeding the first expanding pool.
- Horizons remain separate: game-day morning, 24 hours, and 60 minutes before kickoff.
- Candidate families were frozen in [`NCAAF_DISTRIBUTION_EXPERIMENT_PLAN.md`](NCAAF_DISTRIBUTION_EXPERIMENT_PLAN.md) before results were calculated.

Every distribution fit uses only OOF residuals from seasons strictly earlier than its evaluation season. No post-hoc binary calibrator was selected in v1: primary evidence evaluates the distribution itself, avoiding a thin additional nested calibration layer. Platt, beta, and isotonic calibration remain future predeclared challengers if the available nested sample supports them.

## Candidates evaluated

Margin paired the chronological power rating and Ridge full-v1 point models with homoskedastic Normal, bounded Student-t, chronological kernel-smoothed empirical residual, and quality-grouped Normal scale distributions. Total paired Ridge without opponent adjustment and Ridge full-v1 with those four candidates plus a bounded skew-normal challenger.

The quality-aware model uses four transparent groups: Weeks 0–3 versus later, crossed with both-team PBP coverage at least 0.8 versus lower coverage. Group variance is shrunk toward the global variance with 200 pseudo-observations. It changes uncertainty only, never the point prediction.

## Primary 24-hour results

| Target / point model | Distribution | NLL | CRPS | 90% coverage | Mean 90% width | ML Brier | ML log loss |
|---|---:|---:|---:|---:|---:|---:|---:|
| Margin power rating | Normal | 4.24531 | 9.46787 | 90.11% | 56.12 | 0.19450 | 0.57100 |
| Margin power rating | Student-t | 4.24550 | 9.46680 | 90.00% | 55.95 | 0.19424 | 0.57025 |
| Margin power rating | Empirical | 4.24738 | 9.46942 | 91.23% | 57.79 | 0.19449 | 0.57119 |
| Margin power rating | Quality-aware Normal | **4.24187** | **9.45926** | 90.11% | 55.87 | **0.19444** | **0.57078** |
| Total Ridge, no opponent adjustment | Normal | 4.23038 | 9.32681 | 90.63% | 55.48 | — | — |
| Total Ridge, no opponent adjustment | Student-t | 4.23017 | 9.32655 | 90.41% | 55.31 | — | — |
| Total Ridge, no opponent adjustment | Skew-normal | 4.22649 | 9.31237 | 90.30% | 55.36 | — | — |
| Total Ridge, no opponent adjustment | Empirical | **4.22481** | **9.30423** | 91.17% | 56.78 | — | — |
| Total Ridge, no opponent adjustment | Quality-aware Normal | 4.23078 | 9.32768 | 90.49% | 55.38 | — | — |

The Ridge full-v1 comparison remained slightly worse for both margin and total, consistent with Phase 5B-3. Current evidence advances:

- **Margin:** power rating + `quality-grouped-scale-v1`, retaining homoskedastic Normal as the required benchmark.
- **Total:** Ridge without opponent adjustment + `empirical-kernel-v1`, retaining Normal and skew-normal as diagnostics.

Advancement means eligible for later offline market comparison only. It does not alter `/opportunities` or create a production proprietary probability.

## Paired uncertainty

At 24 hours, quality-aware margin minus Normal produced NLL difference `-0.00344` (season-block 95% interval `[-0.00449, -0.00192]`) and CRPS difference `-0.00861` (`[-0.01161, -0.00459]`). The improvement is small but consistent and the complexity is limited to a transparent scale rule.

Empirical total minus Normal produced NLL difference `-0.00558` (`[-0.00894, -0.00203]`) and CRPS difference `-0.02259` (`[-0.05391, -0.00200]`). Student-t was operationally indistinguishable from Normal. Skew-normal improved CRPS, but its NLL interval crossed zero; it was not advanced over the empirical candidate.

## Interval, PIT, and segment diagnostics

The selected 24-hour margin distribution achieved 50/80/90/95% coverage of 51.09/80.35/90.11/95.15%. Its ten PIT counts were `372, 341, 388, 368, 375, 398, 355, 371, 353, 349`, which is acceptably flat for development evidence but not proof of locked-period calibration.

The selected total distribution achieved 51.50/81.96/91.17/95.80% coverage. Its PIT counts were `364, 393, 385, 391, 394, 388, 370, 345, 342, 298`, showing some upper-tail asymmetry remains despite improved proper scores.

- Weeks 0–3 margin remained harder: CRPS 10.588 versus 9.135 later; 90% coverage was 88.26% versus 90.64%. The quality-aware model widens early intervals from evidence rather than an arbitrary multiplier.
- Low-quality margin rows were sparse (197 of 3,670 at 24h) and had ML Brier 0.2003 versus 0.1941 for high-quality rows. The fitted group scale remains auditable and shrunk.
- Total low-quality CRPS was 9.395 versus 9.299 for high-quality rows; 90% coverage was 89.85% versus 91.25%.
- 2020 was retained and tagged. Selected margin 90% coverage was 88.95%; selected total was 88.95%. This warrants continued regime reporting, not silent exclusion.
- 2021–2022 remained non-blocking: selected margin CRPS 9.426 and 90% coverage 90.49%; selected total CRPS 9.269 and coverage 91.59%.

The three horizons produced the same margin metrics and only tiny legitimate total differences. They remain separate IDs; pooling was not required or promoted.

## Discrete settlement and key numbers

Continuous CDF mass is assigned to integer result `k` using `F(k + 0.5) - F(k - 0.5)`. Integer spread and total lines therefore receive explicit nonzero push mass; half-points receive exactly zero. For modern completed NCAA moneylines, integer margin zero is treated as impossible settlement mass: it is preserved for audit and home/away probabilities are conditioned on a non-tie result.

Synthetic line tests use the predeclared grids and are calibration diagnostics, not historical sportsbook tests. Under the Normal benchmark across horizons, a home `-7` spread assigned mean push probability 2.05% while 4.66% of outcomes landed exactly seven; `-3` assigned about 1.95% while 4.90% landed three. Margin key-number mass is understated materially at 3, 7, 10, and 14. This supports retaining empirical discrete/key-number challengers for 5B-5 rather than manually moving mass.

For totals, modeled versus observed exact mass was close at 49 and 52, but understated at 41 and 45. The selected empirical total distribution improves aggregate NLL/CRPS, but historical sportsbook lines are still needed to judge line-specific usefulness.

All settlement triples are numerically normalized and tested to satisfy finite probabilities in `[0,1]` summing to one. Phase 4's integer-line EV exclusion remains unchanged: this offline engine is not wired into production pricing.

## Joint consistency

Matched margin/total residual correlation was only 0.0413–0.0415 by horizon, below the predeclared 0.10 materiality threshold. No joint simulator was advanced. Expected component scores `(total ± margin)/2` produced no negative expectations across 3,670 games per horizon; minima were 6.74–6.77 home and 7.70–7.72 away. Future score simulation should be reconsidered if richer features or market-conditioned residuals produce material dependence. Separate marginal draws must not be advertised as a coherent joint score generator.

## Artifacts and performance

The ignored local run contains 198,180 probability rows, 270 fit manifests, and 60 empirical pools. Sizes were 10.22 MB Parquet, 2.68 MB pool JSON, 0.18 MB fit JSON, and 1.69 MB run manifest. Runtime was 168.793 seconds. Observed Windows peak working set was 1,604,968,448 bytes; this is feasible offline but is a clear optimization target before broader candidate expansion. No modeling dependency or artifact enters Render's production runtime.

## Limitations and next gate

- No 2025 result was accessed; 2026 remains prospective shadow evidence.
- No historical sportsbook price, ROI, EV, CLV, or profitability claim exists.
- Synthetic line grids do not substitute for historical executable market lines.
- Margin key-number mass needs a predeclared empirical-discrete challenger.
- Total PIT asymmetry and 2020 undercoverage remain diagnostics.
- Calibration-slope/intercept and post-hoc binary transforms were not promoted in v1; any future transform requires nested chronological fitting.
- The next market-aware phase requires the already specified bounded historical-odds coverage audit before acquisition or comparison.

Machine-readable aggregate evidence is in [`reports/NCAAF_PROBABILITY_CALIBRATION_2020_2024.json`](reports/NCAAF_PROBABILITY_CALIBRATION_2020_2024.json). Large OOF artifacts remain ignored under `.ncaaf-data/models/probability-v1/`.
