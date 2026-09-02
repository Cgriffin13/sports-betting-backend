# NCAAF Portfolio Risk and Recommendations

Status: **Phase 6 implemented for paper trading.** The engine creates approval-ready recommendations; it does not place real-money wagers or bypass human approval. All v1 fair values come from the Phase 5B-10 retained market-consensus registry entries. This is a policy baseline for paper validation, not evidence that the default thresholds are optimal or profitable.

## Decision flow

```text
stored fresh observations
  -> Phase 4 exact-market pairing and best executable price
  -> Phase 5B-10 retained fair-value registry
  -> Phase 6 qualification and deterministic ranking
  -> fractional-Kelly/risk-budget allocation
  -> immutable proposed recommendation or PASS
  -> explicit human approval
  -> official paper bet and ledger reservation
  -> settlement and segmented attribution
```

Fair value and executable price are separate inputs. `ncaaf-fair-value-v1` supplies the registered probability/line, model status, uncertainty, source books, dispersion, as-of time, and provenance. Phase 4 supplies a specific sportsbook, exact point, American odds, observation ID, and all compared alternatives. A spread at `-3` is never substituted for `-3.5`; a total at `52.5` is never pooled with `53.5`.

## Qualification

`ncaaf-qualification-v3` requires a retained benchmark, exact event/market/side/point identity, at least two books, age no greater than the configured freshness window, acceptable dispersion, no hard provider/pricing quality warning, EV of at least `0.015`, and edge of at least `0.0075`. These defaults are environment-configurable. `material_book_outlier` and `best_executable_book_outlier` are audit labels, not blanket rejection reasons; malformed, unsupported, inactive, ambiguous, stale, incomplete, or otherwise unknown warnings remain fail-closed.

POLARIS has no separately validated or budgeted longshot sleeve. The actionable main board therefore has one narrow safety guardrail: a best executable price above `+500` remains fully calculable and visible in decision diagnostics, including fair probability, edge, EV, books, dispersion, and provenance, but receives `outside_main_board_odds_profile` and cannot become a recommendation, stake, approval, ledger entry, or parlay leg. This does not change fair value or EV. It is not a general `-300/+300` band and does not reject heavy favorites; prices through `+500` continue through the ordinary mathematical qualification and risk ranking. A future longshot sleeve requires its own evidence, exposure budget, policy version, and approval.

For decimal odds `d`, fair win probability `p_win`, explicit push probability `p_push`, and `p_loss = 1 - p_win - p_push`:

```text
implied_probability = 1 / d
probability_edge = p_win - implied_probability
EV_per_unit = p_win * (d - 1) - p_loss
```

Negative-EV positions never qualify. A position is `CORE` when EV is at least `0.03`, edge is at least `0.015`, and uncertainty is not high. Other qualified positive-EV positions are `OPPORTUNISTIC` and receive a smaller risk multiplier. Top N is a ceiling of ten; the system does not loosen rules to fill it. No accepted straight after risk controls produces an explicit PASS.

The runtime route begins from Phase 4's untruncated structurally calculable candidates, then applies the production qualification policy. Phase 4's conservative baseline excludes integer spreads/totals because the live retained interface does not yet supply a decision-time push model for those observations. The Phase 6 domain math is push-aware and accepts integer-line fair values only when an explicit push probability exists. The underlying observations remain preserved.

## Risk-adjusted ranking

Qualification and ranking are separate. EV and edge remain unchanged hard qualification inputs. After qualification, `expected-log-growth-risk-budget-v2` computes the same push-aware full Kelly fraction used by sizing, applies the existing quarter-Kelly, uncertainty, CORE/OPPORTUNISTIC, and portfolio-state multipliers, and caps the projected standalone fraction by current cash and existing day/game/team/market/correlation limits. It does not bypass sequential sizing or approval-time risk revalidation.

For projected bankroll fraction `f`, net win odds `b = d - 1`, and `p_loss = 1 - p_win - p_push`:

```text
g(p, f) = p_win * ln(1 + f*b) + p_loss * ln(1 - f)
```

A push contributes `p_push * ln(1) = 0`. The primary ranking score is a robustness bound: calculate `g` at the same executable price and projected fraction for every contributing book's paired no-vig probability, then use the minimum. This makes a candidate with fragile cross-book probability support rank below one with comparable consensus economics and stronger agreement without introducing subjective “sharp book” weights.

Qualified candidates sort by robust expected log growth, consensus expected log growth, projected adjusted Kelly fraction, quote-integrity class, book depth, lower dispersion, and then closeness of the executable break-even probability to 50%. Raw EV, edge, kickoff, and stable candidate ID are deterministic later tie-breakers. The moderate-odds tie-break applies only after the bankroll-growth and quality terms; there is no market-type quota or primary hard odds-band ranking. A well-supported price at `+500` or shorter may still qualify and rank first when its prudent expected growth is genuinely superior. Prices above `+500` are separately excluded by the no-longshot-sleeve safety guardrail, not by changing their calculated economics. Top N is applied only after this ranking, and candidates rejected by a stake/exposure control do not consume a Top-N slot.

Phase 4's public pricing projection remains an EV-oriented market-analysis endpoint with no bankroll context. POLARIS Today uses the Phase 6 portfolio order. Watchlist remains ordered by gate distance because it answers a different research question.

### Executable outlier semantics

`unweighted-median-v1` continues to build fair value from every complete supported-book pair at the exact market identity. A book more than 3 probability points from the median is labeled; it is not silently removed or allowed to replace the median. Median consensus is already robust to one extreme contributor. Removing or weighting books would change the frozen fair-value method and requires separate evidence.

The best executable price remains separate from fair value. If its book is a consensus-probability outlier, the candidate receives the explicit `verified_best_price_consensus_outlier` integrity label but is not rejected merely because the quote is better. It must still be a current, active, supported-book quote with a valid opposing pair and valid odds, and both Phase 4's 8-point and Phase 6's stricter 6-point total-dispersion gates remain hard. Unknown integrity warnings remain hard failures. Ranking uses the worst contributing no-vig probability and the integrity label, so weakly corroborated prices face an economic ranking penalty rather than an automatic false equivalence between “different” and “bad.”

## Fractional Kelly and units

For net odds `b = d - 1`, the push-aware full-Kelly candidate is:

```text
f* = max(0, (b*p_win - p_loss) / (b*(p_win+p_loss)))
```

`expected-log-growth-risk-budget-v2` preserves the v1 sizing rules: it multiplies the full-Kelly candidate by `0.25`, then by uncertainty, classification, and portfolio-state factors. It adds the interpretable ranking calculation above; it does not increase risk. Full Kelly remains prohibited, and a subminimum calculated stake is never increased merely to place a bet. Stake is rounded down to cents after all caps.

Initial paper defaults:

| Control | Default |
| --- | ---: |
| CORE position | 2% equity maximum |
| OPPORTUNISTIC position | 1% equity maximum |
| Slate/day | 8% equity maximum |
| Per game | 4% equity maximum |
| Per team | 5% equity maximum |
| Per market type | 5% equity maximum |
| Correlated exposure | 4% equity maximum |
| Minimum / fixed maximum stake | $1 / $50 |
| Unit display | 4% of decision-time equity |
| Reduced-risk drawdown | 10% from peak equity |
| Paused drawdown | 20% from peak equity |
| Bankroll floor | 50% of starting capital |

At the historical `$200` starting bankroll, one displayed unit is `$8`; the default CORE cap is `$4` (0.5 units), and the OPPORTUNISTIC cap is `$2` (0.25 units). Units are presentation only. Kelly and risk budgets determine the dollar stake.

`NORMAL` uses the calculated allocation, `REDUCED_RISK` halves it, and `PAUSED` forces PASS. Approval rechecks current cash, drawdown state, per-position, daily, game, team, market, correlated, and parlay-sleeve caps plus opposing positions inside the same database transaction, preventing a stale recommendation from bypassing newly consumed risk.

Qualification and actionability are distinct. A candidate is **qualified** after it passes the pricing, quality, and model-status gates. It is **actionable** only after the sequential portfolio allocation also produces at least the configured minimum stake and passes exposure controls. A qualified candidate whose calculated stake is below `$1.00` is preserved in the immutable decision-run analysis as a non-actionable qualified opportunity with its exact pre-rejection stake and `below_minimum_stake` blocker. It is never rounded up, does not create a `recommendations` row, cannot be approved, and cannot enter a parlay. Watchlist remains reserved for positive-EV near misses that did not qualify.

## Parlay of the Day

`cross-event-parlay-v2` searches only verified executable combined quotes over two or three already-qualified straight candidates. It never derives the sportsbook payout by multiplying leg prices. Each quote must link every leg to an exact stored source observation.

V2 retains the v1 cross-event/disjoint-team independence restriction. Same-game, shared-team, unknown-correlation, missing-provenance, malformed, nonpositive-EV, unquoted, or main-board-ineligible combinations are rejected. There is no production-quality same-game correlation model. Eligible offers rank by expected log growth at the actual capped parlay stake after a deterministic duplicate-exposure penalty, then by joint, minimum-leg, and aggregate leg probability before raw joint EV. This naturally prefers robust higher-probability legs when their verified combined quote is attractive, without manufacturing an even-money payout. Because every leg must first be an actionable straight, a diagnostic `>+500` price cannot enter the parlay sleeve.

The parlay Kelly multiplier is `0.10`, the default single-parlay cap is `0.5%` of equity (configurable only up to `0.75%`), and the daily parlay sleeve is capped at `1%`. The stake also consumes the straight portfolio's day, game, and team budgets. A duplicate single/parlay event is counted in both economic exposures.

The current The Odds API adapter does not provide executable parlay quotes. The public recommendation endpoint therefore cannot accept caller-invented parlay payouts and normally returns `PARLAY OF THE DAY: PASS`. The optimizer is complete behind a provider-neutral service contract and deterministic tests; a future trusted parlay-price adapter may supply verified quotes without changing portfolio math. This limitation is preferable to fabricating payout or independence.

## Persistence, approval, and accounting

`recommendation_decision_runs` freezes portfolio equity, state, policy versions, PASS reasons, input/output hashes, and rejection counts. Expanded `recommendations` rows preserve fair value, exact executable price, alternatives, full/adjusted Kelly values, projected expected/robust log growth, quote integrity, portfolio rank, stake, units, classification, risk adjustments, and provenance. Ranked order is persisted explicitly and restored by recommendation reads rather than being replaced by hash order. `recommendation_legs` preserves parlay component economics and registry versions.

Recommendations are proposed strategy-book records. `POST /recommendations/{id}/approve` is the explicit human boundary. Approval atomically marks the recommendation approved, creates one official `bets` row, attaches `bet_approvals`, records the state transition, and appends the negative stake ledger entry. Repeating approval returns the same bet. Rejection never creates a bet. Parlay paper bets use the same bet/ledger/settlement system and retain their legs through the linked recommendation; there is no second bankroll.

Cash is the ledger sum. Reserved exposure is open stake. Equity is cash plus reserved exposure at stake value. Settlement returns stake plus net P&L to cash. Performance reports add peak equity, maximum drawdown, turnover, available closing-price CLV observations, and attribution by sport, market, sportsbook, CORE/OPPORTUNISTIC, straight/parlay, edge bucket, odds bucket, confidence, and model version.

## Phase 6.5 backend contract

Authenticated routes added for a presentation layer:

| Route | Purpose |
| --- | --- |
| `POST /portfolio/{id}/recommendations/analyze` | Build and persist today's NCAAF decision run; returns straights, parlay/PASS, state, stake, policies, and hashes. |
| `GET /portfolio/{id}/recommendations` | List actionable strategy-book recommendation history and the latest decision analysis, including non-actionable qualified opportunities. |
| `POST /recommendations/{id}/approve` | Explicitly approve and reserve one paper position. |
| `POST /recommendations/{id}/reject` | Record a human rejection without placing a bet. |
| `GET /portfolio/{id}/risk?slate_date=...` | Current cash/equity/drawdown and exposure by game, team, market, and kind. |

Existing portfolio, history, stats, settlement, pricing, authentication, and `uvicorn main:app` contracts remain available. The dashboard must display fair value separately from executable price and must not label a proposal as an official bet before approval.

## Offline simulator and limitations

`app.domain.portfolio_simulator.simulate_portfolio` replays chronological decision slates through the exact qualification, sizing, risk, PASS, and parlay logic. Outcomes must have timestamps after their decision cutoff; future leakage raises an error. It reports ending bankroll, P&L, turnover, maximum drawdown, straight/parlay counts, PASS slates, and decision hashes. It is for risk-policy validation, not post-2025 predictive-model tuning.

The v1 defaults remain empirical paper policies. Same-game correlation, trusted executable parlay acquisition, partial-cashout/voided-leg repricing, mature CLV conventions, PostgreSQL concurrency load testing, and sufficiently powered sleeve-disable rules remain future work. No part of Phase 6 authorizes autonomous sportsbook execution.
