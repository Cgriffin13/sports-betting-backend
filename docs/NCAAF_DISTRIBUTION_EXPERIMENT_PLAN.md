# NCAAF Phase 5B-4 Distribution Experiment Plan

Status: **Predeclared before Phase 5B-4 evaluation.** This plan governs offline distribution/calibration experiments only. It does not authorize sportsbook comparison, production inference, recommendations, EV, staking, or access to the sealed 2025 season.

## Frozen inputs and chronology

Phase 5B-4 consumes the deterministic Phase 5B-3 OOF artifact for 2019–2024. For an evaluation season `S`, distribution parameters and any calibration transform may use residuals only from OOF seasons `< S` in the same horizon, target, point-model family, and variant. The 2019 OOF season initializes the first pool; scored calibrated evaluation therefore begins in 2020. Horizons remain separate. Residual pools require at least 400 games. Provider/network access is prohibited.

Point-model pairings are frozen as:

- margin: `elo/ncaaf-margin-power-v1` and `ridge/full_v1`;
- total: `ridge/full_without_opponent_adjustment` and `ridge/full_v1`.

## Primary distribution candidates

Each candidate models `actual = point_prediction + residual`.

1. `normal-homoskedastic-v1`: training-pool residual mean and population standard deviation.
2. `student-t-bounded-grid-v1`: degrees of freedom in `{3, 5, 8, 15, 30}`; location and scale are fitted on the historical pool and selected by historical negative log likelihood. A 30-df result is treated as effectively Normal rather than novel heavy-tail evidence.
3. `empirical-kernel-v1`: chronological empirical residuals smoothed by a deterministic Gaussian kernel using bounded Silverman bandwidth. This supplies stable interpolation and nonzero tails while retaining empirical key-number mass.
4. `quality-grouped-scale-v1`: Normal location with scale estimated for the predeclared `(weeks 0–3 versus later) × (high versus low PBP quality)` group. Group variance is shrunk toward global variance with 200 pseudo-observations; no group is discarded.
5. `skew-normal-total-v1`: total-only challenger justified before testing by Phase 5B-3 positive residual skew. Shape, location, and scale are bounded/stably fitted on prior residuals.

No new primary family may be added after results are inspected. A later exploratory family requires a new version and is ineligible for primary selection in this phase.

## Discretization and market-neutral settlement tests

Integer mass uses half-unit bins: `P(Y=k)=F(k+0.5)-F(k-0.5)`. NCAA eligible completed games have no final ties; moneyline home/away probabilities condition the modeled integer margin on nonzero margins and expose the removed tie mass for audit. Integer spread/total lines receive explicit push mass. Half-point lines have zero push mass.

Synthetic spread grid: `-14, -10, -7.5, -7, -3.5, -3, 0, 3, 3.5, 7, 7.5, 10, 14` from the home-bet perspective.

Synthetic total grid: `35, 41, 41.5, 45, 45.5, 49, 49.5, 52, 52.5, 56, 56.5, 63`.

These grids evaluate probability mechanics and calibration only. They are not historical sportsbook lines and cannot establish edge or profitability.

## Metrics and diagnostics

Continuous scoring: NLL, deterministic quantile-integrated CRPS, PIT histograms with ten fixed bins, and central 50%, 80%, 90%, and 95% interval coverage/width. Binary scoring: Brier score and clipped log loss. Three-way settlement scoring: multiclass Brier and log loss plus push frequency/probability. Reliability uses fixed deciles; sparse bins remain visible with their counts.

Segments are predeclared as overall, season, weeks 0–3/later, high/low quality (both teams' PBP coverage at least `0.80` is high), 2020, and 2021–2022. Key-number diagnostics inspect integer margin mass at `3, 7, 10, 14` and the ten most common realized development margins without manually reallocating mass.

Paired comparisons resample whole seasons with 2,000 deterministic bootstrap iterations. Horizon-specific models are primary; a shared-pool diagnostic is permitted only as a simplicity comparison and cannot erase horizon identifiers.

## Advancement rule

Advancement considers development OOF NLL and CRPS jointly, interval coverage error and width, PIT shape, moneyline Brier/log loss, synthetic spread/total settlement scores, push calibration, season stability, early/quality segments, complexity, and paired uncertainty. A richer family advances only if improvements are practically meaningful, stable, and not explained by bootstrap uncertainty. Otherwise the homoskedastic Normal baseline advances. Advancement is only to later offline historical-market comparison; it is not production promotion.

No post-hoc probability transform is primary in v1. Distribution fitting and any future Platt/isotonic calibration remain separate. Isotonic is excluded because nested chronological samples are limited and uncontrolled flexibility could hide structural distribution errors.
