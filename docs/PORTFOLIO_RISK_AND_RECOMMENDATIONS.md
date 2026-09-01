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

`ncaaf-qualification-v1` requires a retained benchmark, exact event/market/side/point identity, at least two books, age no greater than the configured freshness window, acceptable dispersion, no provider/pricing quality warning, EV of at least `0.015`, and edge of at least `0.0075`. These defaults are environment-configurable.

For decimal odds `d`, fair win probability `p_win`, explicit push probability `p_push`, and `p_loss = 1 - p_win - p_push`:

```text
implied_probability = 1 / d
probability_edge = p_win - implied_probability
EV_per_unit = p_win * (d - 1) - p_loss
```

Negative-EV positions never qualify. A position is `CORE` when EV is at least `0.03`, edge is at least `0.015`, and uncertainty is not high. Other qualified positive-EV positions are `OPPORTUNISTIC` and receive a smaller risk multiplier. Top N is a ceiling of ten; the system does not loosen rules to fill it. No accepted straight after risk controls produces an explicit PASS.

The runtime route currently begins from Phase 4 qualified opportunities, whose conservative baseline excludes integer spreads/totals because the live retained interface does not yet supply a decision-time push model for those observations. The Phase 6 domain math is push-aware and accepts integer-line fair values only when an explicit push probability exists. The underlying observations remain preserved.

## Fractional Kelly and units

For net odds `b = d - 1`, the push-aware full-Kelly candidate is:

```text
f* = max(0, (b*p_win - p_loss) / (b*(p_win+p_loss)))
```

`fractional-kelly-risk-budget-v1` multiplies this by `0.25`, then by uncertainty, classification, and portfolio-state factors. It never uses full Kelly and never increases a subminimum calculated stake merely to place a bet. Stake is rounded down to cents after all caps.

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

## Parlay of the Day

`cross-event-parlay-v1` searches only verified executable combined quotes over two or three already-qualified straight candidates. It never derives the sportsbook payout by multiplying leg prices. Each quote must link every leg to an exact stored source observation.

V1 permits the product of marginal fair probabilities only for different events with disjoint teams. Same-game, shared-team, unknown-correlation, missing-provenance, malformed, nonpositive-EV, or unquoted combinations are rejected. There is no production-quality same-game correlation model. Selection maximizes joint EV after a deterministic duplicate-exposure penalty; it does not mechanically choose ranks one through three.

The parlay Kelly multiplier is `0.10`, the default single-parlay cap is `0.5%` of equity (configurable only up to `0.75%`), and the daily parlay sleeve is capped at `1%`. The stake also consumes the straight portfolio's day, game, and team budgets. A duplicate single/parlay event is counted in both economic exposures.

The current The Odds API adapter does not provide executable parlay quotes. The public recommendation endpoint therefore cannot accept caller-invented parlay payouts and normally returns `PARLAY OF THE DAY: PASS`. The optimizer is complete behind a provider-neutral service contract and deterministic tests; a future trusted parlay-price adapter may supply verified quotes without changing portfolio math. This limitation is preferable to fabricating payout or independence.

## Persistence, approval, and accounting

`recommendation_decision_runs` freezes portfolio equity, state, policy versions, PASS reasons, input/output hashes, and rejection counts. Expanded `recommendations` rows preserve fair value, exact executable price, alternatives, Kelly values, stake, units, classification, risk adjustments, and provenance. `recommendation_legs` preserves parlay component economics and registry versions.

Recommendations are proposed strategy-book records. `POST /recommendations/{id}/approve` is the explicit human boundary. Approval atomically marks the recommendation approved, creates one official `bets` row, attaches `bet_approvals`, records the state transition, and appends the negative stake ledger entry. Repeating approval returns the same bet. Rejection never creates a bet. Parlay paper bets use the same bet/ledger/settlement system and retain their legs through the linked recommendation; there is no second bankroll.

Cash is the ledger sum. Reserved exposure is open stake. Equity is cash plus reserved exposure at stake value. Settlement returns stake plus net P&L to cash. Performance reports add peak equity, maximum drawdown, turnover, available closing-price CLV observations, and attribution by sport, market, sportsbook, CORE/OPPORTUNISTIC, straight/parlay, edge bucket, odds bucket, confidence, and model version.

## Phase 6.5 backend contract

Authenticated routes added for a presentation layer:

| Route | Purpose |
| --- | --- |
| `POST /portfolio/{id}/recommendations/analyze` | Build and persist today's NCAAF decision run; returns straights, parlay/PASS, state, stake, policies, and hashes. |
| `GET /portfolio/{id}/recommendations` | List strategy-book recommendation history, optionally by slate date. |
| `POST /recommendations/{id}/approve` | Explicitly approve and reserve one paper position. |
| `POST /recommendations/{id}/reject` | Record a human rejection without placing a bet. |
| `GET /portfolio/{id}/risk?slate_date=...` | Current cash/equity/drawdown and exposure by game, team, market, and kind. |

Existing portfolio, history, stats, settlement, pricing, authentication, and `uvicorn main:app` contracts remain available. The dashboard must display fair value separately from executable price and must not label a proposal as an official bet before approval.

## Offline simulator and limitations

`app.domain.portfolio_simulator.simulate_portfolio` replays chronological decision slates through the exact qualification, sizing, risk, PASS, and parlay logic. Outcomes must have timestamps after their decision cutoff; future leakage raises an error. It reports ending bankroll, P&L, turnover, maximum drawdown, straight/parlay counts, PASS slates, and decision hashes. It is for risk-policy validation, not post-2025 predictive-model tuning.

The v1 defaults remain empirical paper policies. Same-game correlation, trusted executable parlay acquisition, partial-cashout/voided-leg repricing, mature CLV conventions, PostgreSQL concurrency load testing, and sufficiently powered sleeve-disable rules remain future work. No part of Phase 6 authorizes autonomous sportsbook execution.
