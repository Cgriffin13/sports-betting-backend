# NCAAF cross-line market-value calibration

Status: **Implemented for the POLARIS paper recommendation path. Thresholds retained, not optimized.**

This audit evaluates the 2020–2024 immutable game-day-morning market corpus. It makes no provider calls, does not use 2025 or 2026 outcomes, and does not claim profitability. Its machine-readable companion is `reports/NCAAF_MARKET_VALUE_CALIBRATION_V1.json`.

## Implemented fair-value method

Moneyline keeps the existing `proportional-v1` no-vig probability for each complete book pair and `unweighted-median-v1` consensus. Spread and total use `ncaaf-empirical-cross-line-v1`:

1. Preserve exact, coherent opposing sides inside each sportsbook. Different books may quote different main lines.
2. Convert each book's no-vig first-side probability and point into an implied market center with the historical empirical NCAAF residual curve.
3. Combine book centers with bounded inverse-overround weights and Huber influence (`overround-weighted-huber-center-v1`). This uses price information but limits one distant book's influence.
4. Project the robust center to every executable line on the integer football-score lattice.
5. Select the best side-specific executable offer by push-aware EV, retaining every alternative and source observation.
6. Calculate `P(win)`, `P(push)`, and `P(loss)` explicitly. Half-points have zero push mass; integer lines may have nonzero push mass.

For home spread point `s`, line advantage is `expected_margin + s`; for away it is `-expected_margin + s`. For totals, Over advantage is `expected_total - line` and Under advantage is `line - expected_total`. A home `-3.5` is therefore correctly better than `-4.5` at the same price when the market center is unchanged. The stored artifact contains 3,199 spread residual games and 3,245 total residual games and is content-hashed as `199e8170c86acb497b864b20b60abf190ce5a8cae1d6b8352e3ef584183c76bb`.

## Chronological falsification

For spread and total season `S`, the audit estimated probabilities using residuals from seasons before `S`; 2020 initializes the pool and scored evaluation covers 2021–2024. The 2024 season remains the final validation segment. Production book depth and the six-percentage-point probability-dispersion ceiling were retained in pricing qualification. The `+500` positive-price guardrail is reported separately because it is a later portfolio/main-board rule, not pricing math.

| Market | Candidate sides | Mean modeled EV | Realized unit ROI | Existing-gate sides | 2024 gate sides |
|---|---:|---:|---:|---:|---:|
| Spread | 5,525 (5,526 calculable) | -3.441% | -3.740% | 13 | 6 |
| Total | 5,606 | -3.413% | -3.315% | 4 | 1 |
| Moneyline | 6,264 | -2.129% | -3.819% | 167 | 33 |

The broad spread and total distributions are directionally calibrated around the market hold. Total line-advantage buckets improved materially: realized unit return moved from -6.36% below zero advantage to +5.87% at 1–2 points and +17.99% above two points. The positive-EV tail is nevertheless only four bets under current gates, with one adverse 2024 observation.

Spread evidence is more cautious. The 0.5–1.0 point bucket improved relative to smaller nonnegative advantages, but the 1+ point tails contained only 55 sides and performed poorly. Inspection showed large cross-book line reversals/outliers in that tail. Those quotes remain auditable, but their evidence does not justify relaxing gates; probability dispersion, quote-integrity labels, least-favorable-book robust growth, Kelly sizing, and the minimum-stake rule remain necessary protections.

Moneyline evidence also rejects threshold expansion. The pricing gates identified 167 sides before the portfolio odds-profile rule; 77 remained after the existing `+500` main-board guardrail, with realized unit ROI of approximately +4.34%. The `-220` through `+220` diagnostic band produced 20 pricing-gate candidates over five seasons and only three in 2024. Results were positive but too sparse to establish a new odds-band rule. The `+221` through `+500` tail was unstable and adverse in 2024. Prices above `+500` remain diagnostic-only and are never counted as actionable main-board evidence.

## Qualification decision

No market-specific threshold change is supported. Phase 6 retains, for spread, total, and moneyline:

- minimum probability edge: **0.75 percentage points**;
- minimum EV per unit: **1.50%**;
- minimum complete supported books: **2**;
- maximum Phase 6 consensus dispersion: **6 percentage points**.

This is deliberately conservative. It does not imply that the thresholds are permanently optimal; it means this sample does not support replacing them. No threshold was selected to create activity on the current slate.

## Production implications

Cross-line spread and total offers now reach the same candidate, Watchlist, risk ranking, stake sizing, persistence, and Today API path as moneylines. Watchlist records the executable line, robust consensus fair line, line advantage, empirical probability version, edge, EV, and exact failed gates. Diagnostic summaries are segmented by market and by the fixed American-odds bands, including the practical `-220` to `+220` band. These diagnostics change visibility only; they do not alter fair probabilities or qualification.

The production artifact is deliberately small and standard-library-only. Offline generation/audit code may use the research dependency stack, but Render startup does not import PyArrow or other research modules.
