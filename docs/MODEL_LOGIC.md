# Model, Pricing, EV, and Staking Logic

This document defines shared terminology and intended mathematical semantics. It clearly distinguishes current behavior from planned V2 behavior.

## Implementation status

| Capability | Current prototype | Planned V2 |
| --- | --- | --- |
| American odds retrieval | Implemented | Retain behind provider adapters |
| Raw and normalized market snapshots | Implemented for current game markets | Use as the reproducible input to pricing, closing capture, and backtests |
| First-class NCAAF support | Provider key, aliases, raw snapshots, and normalized full-game markets implemented | Expand through pricing and modeling |
| Implied-probability calculation | Implemented with Decimal for Phase 4 baseline pricing | Retain and extend to additional market conventions |
| Vig removal | `proportional-v1` implemented for complete two-outcome book markets | Evaluate alternatives without rewriting historical outputs |
| Multi-book consensus | `unweighted-median-v1` implemented with dispersion/outlier reporting | Remain the baseline; evaluate evidence-backed weighting later |
| Proprietary predictive model | Offline NCAAF candidates were evaluated and not promoted; none supplies current fair value | Continue prospective diagnostics and later independently validated league tracks |
| Structured sports/news signals | Not implemented | Traceable league-specific inputs |
| Edge calculation | Calculated by Phase 4 and persisted by the Phase 6 recommendation path; legacy direct bet fields remain caller-supplied | Extend to additional leagues and market conventions |
| EV calculation | Phase 4 binary EV and Phase 6 push-aware recommendation EV are implemented; legacy direct bet fields remain caller-supplied | Extend to additional leagues and market conventions |
| Stake recommendation | Implemented for NCAAF v1 paper recommendations | Push-aware quarter-Kelly input with uncertainty/state adjustments and conservative caps |
| Portfolio exposure control | Implemented for NCAAF paper recommendations and revalidated at approval | Validate and evolve versioned limits from prospective evidence |
| Parlay recommendation | A conservative cross-event optimizer is implemented; without a trusted combined-price quote the result is PASS | Add trusted quote acquisition and independently validated correlation methods |
| Closing line value | Data fields exist; calculation absent | Capture and calculate consistently |
| Calibration/learning | Offline Phase 5 evidence, immutable registry, and 2026 shadow records implemented; no online mutation | Continue prospective, evidence-based, versioned evaluation |

The legacy direct bet-entry `model_prob`, `book_prob`, `edge`, and `ev_per_1` fields remain passive metadata supplied by the caller. Their names do not prove that the Phase 4 engine produced them. The Phase 6 recommendation path is separate: it reconstructs pricing from stored observations, obtains retained fair value through the registry, freezes both inputs in a proposed recommendation, and copies that snapshot into an official bet only after explicit approval.

Phase 4 distinguishes a **calculable candidate** from a **qualified opportunity**. A calculable side has a valid supported-book pair, exact event/market/period/line identity, at least two books, fresh unambiguous observations, a no-vig consensus fair probability, and a best executable price. Its edge, EV, dispersion, provenance, and failed pricing gates are retained even when edge or EV is below the baseline threshold. Phase 4's public `opportunities` response remains threshold-qualified and Top-N bounded; the Phase 6 decision service consumes the internal untruncated calculable set. This separation changes visibility, not fair-value mathematics or qualification thresholds.

The prototype supports both NCAAF and NCAAB as distinct canonical leagues. NCAAB is college basketball; it must never be substituted for college football in model data, league identifiers, or evaluation.

## League and market modeling sequence

Development priority is NCAAF, NFL, then NBA; MLB, NHL, and WNBA are secondary.

- **NCAAF:** begin with full-game moneyline, spreads, and totals. Candidate model inputs may include team strength, opponent adjustment, returning production, coaching/system continuity, tempo, efficiency, travel, venue, weather, injuries/availability, and other validated features.
- **NFL:** follow the same initial game-market progression. Sport-specific inputs may include team efficiency, personnel/availability, rest, travel, weather, matchup, and market context.
- **NBA:** support game markets first and later player props. Player availability, projected minutes, usage, pace, rest, lineup combinations, and matchup data are central candidates.

Alternate spreads/totals and half/quarter markets follow only after the full-game pipeline is validated. Player props are later because they require player-level projections, market-specific settlement rules, and substantially more data/modeling.

These are candidate feature domains, not permission to add them heuristically. Every historical variable must earn weight through reproducible out-of-sample evidence.

## Canonical market observation identity

Phase 3 defines an observation by stable event UUID, canonical sportsbook, canonical market type, period, selection side, and exact point identity. Initial canonical values are:

- market type: `moneyline`, `spread`, or `total`;
- period: `full_game`;
- side: `home`, `away`, `draw`, `over`, or `under`;
- point: null/`none` for moneyline and exact `NUMERIC(10,3)` for spread/total; and
- price: valid integer American odds.

Equivalent-price calculations in Phase 4 must additionally reject observations marked stale, suspended, `needs_review`, or `conflict`. For example, Over 52.5 and Over 53.5 are different identities, as are home -3.5 and home -4.0. Period is explicit so later first-half/quarter markets cannot collide with full-game markets.

For spread pairing, the opposing point must be the exact additive inverse: home -3.5 pairs with away +3.5, never away +4.0. Totals require the identical point on over and under. At a historical cutoff, Phase 4 first removes observations whose provider observation time or database ingestion time is after the cutoff, then selects the latest snapshot state per event/book/market/period. This prevents both future information leakage and a superseded line from remaining falsely executable.

Every normalized observation points to an immutable raw snapshot and raw array indexes. Its provider update time, effective observation time, ingestion time, age, freshness-policy version, threshold, and stale flag are retained. The first and last pre-start observations can therefore be selected later by identity and time. Phase 3 does not define which book set/time is the official close and does not calculate CLV.

## Core terminology

### Sportsbook implied probability

The probability mechanically implied by one offered price before removing the bookmaker margin. It is not a fair probability.

For American odds `A`, with `A != 0`:

```text
if A > 0: decimal_odds = 1 + A / 100
if A < 0: decimal_odds = 1 + 100 / abs(A)

implied_probability = 1 / decimal_odds
```

Equivalent direct formulas are:

```text
if A > 0: q = 100 / (A + 100)
if A < 0: q = abs(A) / (abs(A) + 100)
```

Odds of zero are invalid. Inputs and outputs must be finite, and probabilities must be constrained to `[0, 1]` with stricter interior constraints where required by scoring formulas.

### No-vig market probability

A probability obtained after removing estimated sportsbook margin from all mutually exclusive outcomes in the same market. For the initial proportional method:

```text
q_i = raw implied probability for outcome i
p_i = q_i / sum(q_j for all outcomes j)
```

The method must use a complete, coherent market at one book and one observation time. More sophisticated methods may be evaluated later, but the method and version must be stored.

Implemented Phase 4 policy is `proportional-v1`. It uses Decimal arithmetic, rounds normalized probabilities to 12 decimal places using `ROUND_HALF_EVEN`, and assigns the final outcome the residual so a paired market sums exactly to one. Raw implied probabilities, their sum, overround, both observation IDs, and the version remain visible.

### Consensus probability

A fair-price estimate derived from multiple market observations after normalization and vig removal. Consensus construction may account for book quality, liquidity proxies, staleness, outliers, and observation time.

Only equivalent markets may be combined. A spread at `-3.0` is not the same price object as a spread at `-3.5`; totals, periods, overtime rules, and participant identity also matter.

A consensus probability is market-derived. It is not a proprietary predictive model. It is the initial baseline and ongoing benchmark for measuring whether a proprietary model adds predictive or economic value.

Implemented Phase 4 policy is `unweighted-median-v1`:

1. Require a configurable minimum number of supported books with complete exact-market pairs.
2. Calculate each book's `proportional-v1` no-vig probability.
3. Take the unweighted median for each selection. No “sharp book” weights are assumed.
4. Report dispersion as the maximum minus minimum contributing no-vig probability.
5. Identify any book whose absolute deviation from the median exceeds the configured outlier threshold.
6. Reject the exact market if dispersion exceeds the configured maximum.

The default outlier threshold is 0.03 and maximum dispersion is 0.08. These are configurable conservative operational baselines, not permanent empirically validated claims.

### Proprietary/model probability

A probability produced by a separately defined predictive model using features beyond mechanical market aggregation, or by a documented blend in which the proprietary component is explicit. Every estimate must identify model name, version, training/evaluation window, and creation time.

### Fair probability

The probability selected by a declared pricing policy for decision-making. Its source may initially be market consensus and later be a documented selection or blend of market consensus and a sport-specific proprietary model. Consensus is not assumed to remain the final estimate indefinitely. `fair_probability_source`, component probabilities, blend/selection policy, and calculation version must accompany the value.

### Edge

Probability edge against an offered sportsbook price is:

```text
edge = fair_probability - offered_implied_probability
```

Edge is a probability-point difference, not expected profit. It should be labeled clearly—for example, `probability_edge`—and must not be used as the sole ranking criterion.

### Expected value

For a binary market with decimal odds `d`, fair win probability `p`, and no push probability:

```text
net_profit_if_win = d - 1
ev_per_unit = p * (d - 1) - (1 - p)
            = p * d - 1
expected_profit = stake * ev_per_unit
```

When a push is possible:

```text
ev_per_unit = p_win * (d - 1) - p_loss
```

The push contributes zero net profit. Rules for half-wins, half-losses, voids, and partial settlements must be modeled explicitly rather than forced into the binary formula.

Positive edge does not always imply positive EV across differently priced opportunities, and a large uncertain edge should not automatically outrank a smaller reliable EV estimate.

Phase 4 uses the binary identity only for two-outcome moneylines and half-point spreads/totals. Integer spread/total observations remain stored and replayable, but they are excluded from EV qualification under `baseline-qualification-v1` because push probability is not yet modeled. This is a conservative Phase 4 limitation, not a permanent product decision. A later version may qualify integer lines only after explicit win/loss/push probabilities and settlement conventions are implemented and tested.

### Confidence and uncertainty

Probability is an estimate of event likelihood. Confidence describes the reliability of that estimate; uncertainty describes its dispersion or error. They are not interchangeable, and confidence must not be added to probability as an arbitrary bonus.

V2 should represent uncertainty through defensible evidence such as:

- dispersion among comparable no-vig books;
- price staleness and market liquidity proxies;
- historical calibration error for the model and probability region;
- disagreement between market consensus and proprietary estimates;
- sample size and out-of-sample stability; and
- known data-quality flags.

The uncertainty representation and any adjustment to ranking or staking must be versioned and tested. Phase 6 implements `ncaaf-qualification-v3`, `expected-log-growth-risk-budget-v2`, and `cross-event-parlay-v2`; the exact current rules are documented in `PORTFOLIO_RISK_AND_RECOMMENDATIONS.md`.

## Initial V2 pricing philosophy

A legitimate first engine does not require machine learning:

```text
sportsbook odds
  -> implied probabilities
  -> vig removal within coherent markets
  -> multi-book consensus / market fair estimate
  -> compare executable offer with fair probability
  -> calculate probability edge and EV
  -> apply uncertainty and portfolio-risk rules
  -> recommend stake
```

This is now the implemented `market-baseline-v1` path. It provides a testable baseline. An NCAAF predictive-model track should begin next; it does not wait until the final roadmap phase. NFL and NBA follow. Proprietary models should be promoted into final-fair-probability decisions only when out-of-sample evidence shows value relative to the consensus benchmark.

## Phase 4 qualification and replay

`baseline-qualification-v1` defaults to a minimum of two books, EV per unit of 0.01, probability edge of 0.005, maximum consensus dispersion of 0.08, and canonical supported books DraftKings, FanDuel, and BetMGM. Thresholds and book keys are environment-configurable. These values are research starting points, not staking rules or evidence of profitability.

Qualified opportunities rank deterministically by EV, contributing-book count, dispersion, event time, and stable identity. Top N is then applied independently per league; its default is 10 and it remains a ceiling. No threshold changes when fewer results qualify, and zero is correct.

Every output contains the event and exact market identity; best executable observation/book/odds and implied probability; each book's no-vig inputs; median consensus, dispersion, outliers, edge, and EV; null proprietary probability; `market_consensus` fair source; policy versions; observation/snapshot provenance; and cutoff/calculation timestamp. Phase 4 returns no stake.

Historical pricing replay is deterministic and offline. It requires a timezone-aware cutoff and enforces both:

```text
observation.observed_at <= replay_as_of
observation.ingested_at <= replay_as_of
```

It applies the same latest-state, freshness, ambiguity, exact-pairing, consensus, and qualification policies as current stored-observation analysis. Replay outputs what pricing knew at that time. It does not fabricate results and must be distinguished from an outcome backtest or portfolio simulation, neither of which is implemented in Phase 4.

## Structured data and research signals

The model platform should combine normalized market data with sport-specific structured statistics and traceable injury/news/research signals.

Every non-market signal should preserve:

- source and source URL or stable identifier;
- publication and ingestion timestamps;
- affected league, event, team, player, or market;
- extracted fact and structured category;
- confidence in extraction and any conflicting sources;
- transformation/feature version; and
- the model or policy version that consumed it.

An LLM may discover sources, extract facts, summarize evidence, and generate a human-readable explanation. It must not silently convert prose into arbitrary probability points. A probability adjustment is permitted only through a documented, testable feature or explicit policy whose input and effect are reproducible.

## Ranking philosophy

Recommendations must not be ranked by edge alone. A ranking policy should consider at least:

- EV per unit and expected profit at the proposed stake;
- source and uncertainty of fair probability;
- offered price quality and market freshness;
- model calibration in the relevant probability range;
- bankroll fraction and downside;
- total daily and sport/market exposure;
- correlated open positions; and
- operational/data-quality warnings.

The implemented NCAAF paper policy uses an interpretable expected-log-growth score after qualification. At projected bankroll fraction `f` and net decimal profit `b`, `g = p_win ln(1 + f*b) + p_loss ln(1 - f)`; pushes contribute zero. The projected fraction uses the existing push-aware quarter-Kelly sizing multipliers and current standalone exposure caps. The primary robustness score is the minimum `g` across the contributing books' paired no-vig probabilities at the same executable price and fraction. This makes raw EV a qualification/tie-break input rather than the sole definition of “best.” Book depth, dispersion, quote-integrity labels, and a late moderate-odds tie-break resolve otherwise similar candidates without market-type quotas.

This risk-adjusted ranking—not an odds band—is the primary treatment of high-variance prices. A `-110` spread can outrank a `+1000` or `+2000` moneyline with higher raw EV when the spread supports more prudent Kelly capital and stronger worst-book expected growth. Separately, because no longshot sleeve exists, `ncaaf-qualification-v3` keeps prices above `+500` as calculable research rows but excludes them from ordinary recommendations. The guardrail does not modify fair probability, edge, EV, or the ranking score and does not apply a hard negative-odds boundary.

`material_book_outlier` means one complete book's no-vig probability differs from the unweighted median by more than the configured 3-point diagnostic threshold. The median still defines fair value, and the label alone is informational. A best executable price with that label is not automatically bad data: it remains actionable only if the book is supported/active, the quote is current, the pair is valid, and total dispersion remains within hard limits. Unknown integrity warnings and excessive dispersion remain hard failures.

### Qualified Top N behavior

The interface returns up to a configurable Top N opportunities for each selected league, with 10 as the normal display maximum. Qualification occurs before ranking and truncation.

```text
normalized candidates
  -> data-quality and freshness gates
  -> positive-EV and uncertainty gates
  -> portfolio/risk eligibility
  -> rank qualified opportunities
  -> return first min(Top N, qualified_count)
```

The system must never reduce thresholds, duplicate markets, or manufacture recommendations to fill Top N. Zero recommendations is valid.

Every returned recommendation must preserve and expose:

- best executable sportsbook and American/decimal price;
- offered implied probability;
- no-vig market inputs where applicable;
- market-consensus probability;
- proprietary model probability when available;
- final fair probability and source/policy version;
- probability edge and EV per unit;
- uncertainty/confidence and data-quality indicators;
- recommended stake, portfolio-equity percentage, and displayed units;
- pricing, model, and risk-policy versions; and
- a human-readable explanation with traceable research sources/signals.

## Optional Parlay of the Day (planned later phase)

The Parlay of the Day is an optional featured recommendation alongside—not inside or above—the core ranked straight-bet portfolio. It must not change the objective of maximizing long-term risk-adjusted bankroll growth through individually qualified positions.

The system may return at most one featured parlay per day/league scope; zero is a correct and expected result. It must not loosen filters, duplicate legs, or manufacture a combination to satisfy the feature. Each leg must independently pass the applicable straight-bet data-quality, pricing, EV, uncertainty, and portfolio-eligibility gates before combination is considered.

For executable parlay decimal odds `d_parlay` and modeled joint win probability `p_joint`:

```text
parlay_ev_per_unit = p_joint * (d_parlay - 1) - (1 - p_joint)
```

Qualification must compare the sportsbook's executable combined payout with `p_joint`; it must not infer the offered payout merely by multiplying displayed leg odds when the sportsbook supplies a distinct parlay price.

For defensibly independent cross-event legs, an initial research estimate may use:

```text
p_joint = product(p_leg_i)
```

That product is invalid when material dependence is present. Same-game parlays and other correlated combinations require explicit correlation modeling, simulation, a validated joint distribution, or another reproducible joint-probability method before production-quality use. Early experimentation should prefer cross-event combinations with documented independence checks. Unknown correlation is a reason to reject the candidate, not to assume independence.

Parlays must use a separate, conservative portfolio risk budget and generally lower per-position caps than qualified straight bets. Their exposure must still count toward total portfolio, league, event, daily, and correlation limits. The parlay sleeve must be independently versioned and capable of automatic risk reduction or disablement when sufficiently powered out-of-sample evidence shows detrimental risk-adjusted performance.

Track parlays separately from straight bets, including at minimum component legs and their decision-time probabilities, executable combined price, joint fair probability and method/version, expected value at entry, stake, realized P&L, ROI/yield, hit rate, and sample size. Capture closing observations so CLV and calibration can be defined and evaluated later where mathematically meaningful.

Phase 6 freezes initial paper defaults of two or three legs, 5% joint EV, 10%-Kelly, a 0.5% per-parlay cap, and a 1% daily sleeve. Only cross-event disjoint-team independence is supported. Same-game/shared-team/unknown-correlation combinations fail closed, and the public API cannot accept caller-manufactured combined prices. These are versioned experimental defaults, not permanent product decisions. CLV convention and sufficiently powered sleeve promotion/disablement gates remain unresolved. Full Kelly remains prohibited.

## Staking philosophy

The objective is long-term risk-adjusted bankroll growth, not reaching a fixed bankroll target. Stakes should scale automatically from current portfolio equity rather than use static dollar amounts.

Historical discussion used approximately 1–3% of bankroll for normal positions and 5–10% only for unusually strong opportunities. These are historical heuristics, not V2 constants or authorization to risk those amounts.

For decimal odds `d`, net odds `b = d - 1`, win probability `p`, and loss probability `q = 1 - p`, the binary Kelly fraction is:

```text
kelly_fraction = (b * p - q) / b
```

V2 may use the positive part of Kelly as one input, but must never blindly use full Kelly. A candidate recommendation should resemble:

```text
raw_fraction = max(0, kelly_fraction)
adjusted_fraction = raw_fraction
                    * fractional_kelly_multiplier
                    * confidence_adjustment
recommended_fraction = min(
    adjusted_fraction,
    per_bet_cap,
    remaining_daily_risk,
    remaining_group/correlation_capacity
)
```

All multipliers and caps require paper-trading validation. The engine should also support “no bet” when EV is non-positive, uncertainty is too high, data is stale, limits are reached, or market identity is ambiguous.

Phase 2 defines current portfolio equity as cash plus reserved open stake at original stake value. Future sizing should capture that equity value at recommendation time. How to value more complex open positions or pending/partial settlements remains unresolved and requires a superseding versioned policy.

One unit is a display abstraction derived from current equity under a versioned unit policy:

```text
unit_dollars_at_recommendation = portfolio_equity * unit_fraction(policy_version)
display_units = recommended_stake / unit_dollars_at_recommendation
```

The formula is illustrative, not an accepted `unit_fraction`. Store both dollars and equity percentage so historical recommendations remain interpretable after bankroll changes.

Required risk concepts include:

- maximum risk per bet;
- maximum aggregate open exposure;
- maximum daily new risk and/or loss;
- exposure by sport, league, event, market, and model;
- correlation groups and mutually dependent outcomes;
- drawdown-aware risk reduction; and
- minimum confidence/data-quality thresholds.

## Bet and bankroll semantics

The current ledger implementation preserves the compatibility API's `payout` as net profit/loss and reserves stake at placement:

```text
placement:  cash_bankroll -= stake
settlement: cash_bankroll += stake + net_payout
```

That arithmetic is consistent for a win, loss, or push if the supplied payout is correct. A loss must equal negative stake and a push must be zero; a win remains caller-supplied rather than derived from odds. A later settlement engine should calculate profit from immutable entry terms and a validated outcome.

Phase 2 distinguishes:

- cash balance;
- reserved/open stake;
- total portfolio equity;
- realized P&L; and
- unrealized/open exposure.

Cash is the sum of signed ledger entries. Reserved/open stake is the sum of open bet stakes. Equity is cash plus reserved stake, and realized P&L is the sum of settled bet P&L; therefore an open stake is exposure, not an immediate realized loss.

Money uses Python `Decimal` and SQL `NUMERIC(18,2)`, rounded to cents with `ROUND_HALF_UP`. JSON responses may contain numbers for compatibility, but floats are not authoritative. Currency is stored per portfolio and is currently USD; conversion and sport/book-specific settlement rules remain unimplemented. Historical ledger entries are immutable under normal operations, with explicit adjustments reserved for reconciliations/corrections.

## Closing line value

CLV should compare the captured entry price with a defined closing benchmark for the same event, market, selection, and line. Candidate representations include:

- change in no-vig probability: `closing_fair_probability - entry_fair_probability` for the selected outcome; and
- price-ratio or implied-probability comparisons between entry and close.

The chosen primary CLV convention is not yet decided. The system must store raw entry and closing observations so alternative definitions can be reproduced. Closing capture time and benchmark books must be recorded.

## Performance and calibration

### ROI / yield

```text
ROI = realized_net_profit / total_settled_stake
```

Open stakes should not be counted as realized losses. Reports should state whether pushes are excluded from denominators.

### Hit rate

At minimum, report wins, losses, and pushes separately. If hit rate is used, prefer `wins / (wins + losses)` and identify any alternative convention.

### Brier score

For binary outcome `y` in `{0, 1}` and predicted probability `p`:

```text
Brier = mean((p - y)^2)
```

Lower is better. Predictions must be evaluated using the probability actually recorded at recommendation time.

### Log loss

```text
LogLoss = -mean(y * ln(p) + (1 - y) * ln(1 - p))
```

Probabilities require a documented numerical clipping policy for calculation, while retaining the original prediction for audit.

### Calibration

Calibration compares predicted probability with observed frequency across sufficiently populated bins or with continuous calibration methods. Reports must include sample size and uncertainty intervals; bin-level noise must not directly trigger large staking or weighting changes.

### Drawdown

Track peak-to-trough decline on a clearly defined portfolio-equity series, with both currency and percentage values. Cash-only drawdown is misleading while stakes remain open.

### Segmentation

Eventually evaluate results by model/version, sport, league, market, sportsbook, edge bucket, probability bucket, confidence bucket, and time period. Multiple comparisons and small samples must be treated cautiously.

Market-consensus and proprietary-model predictions should be scored separately against outcomes and closing markets. A model should not receive weight merely because a historical trend recently succeeded; promotion requires time-aware out-of-sample evaluation, calibration evidence, and sufficient sample size.

## Phase 5B-2 NCAAF feature foundation (implemented offline)

The current offline research pipeline materializes only corpus-supported, point-in-time features: rolling efficiency/PPA, success/explosiveness, yards and drive efficiency, plays/drives pace proxies, a conservative havoc proxy, context, explicit quality/missingness, early-season prior shrinkage, and prior-only opponent adjustment. Reconstructed postgame facts become available no earlier than kickoff plus 24 hours. The target game and all future team/opponent results are excluded by construction and regression tests.

These values are candidate inputs, not probabilities, feature importance, or evidence of betting edge. The builder does not impute missing values, learn weights, select transformations, or train a model. The 2020 regime is retained and flagged. Game-day morning, 24-hour, and 60-minute rows remain distinct even when independent-football values coincide.

## Phase 5A NCAAF model specification (planned model, implemented feature inputs)

The primary research targets are:

```text
margin = home_points - away_points
total  = home_points + away_points
```

Candidates must produce predictive distributions from which moneyline, spread and total `P(win)`, `P(push)`, and `P(loss)` can be derived. A continuous distribution is discretized to the integer football-score lattice; for margin CDF `F`, `P(M = k) = F(k + 0.5) - F(k - 0.5)`. Normal, Student-t, chronological out-of-fold empirical residual, heteroskedastic, quantile/distributional, and joint component-score approaches are experiments—not assumptions. Direct win classification is a moneyline challenger/calibration check and cannot price spreads or totals by itself.

Phase 5B-3 implements the first falsification tier: training-mean/home-field/prior-team naive baselines, a chronological margin power rating, and fold-local Ridge for margin and total. Ridge uses training-fold median imputation with missing indicators, constant removal, standardization, and a four-value alpha grid selected only on 2019–2023 development OOF error. Elastic Net was attempted on its predeclared small grid but deferred because the wide v1 design did not converge reliably; unstable complexity is not reported as a challenger result.

All three horizons are evaluated independently. Phase 5B-4 now converts earlier OOF point residuals into experimental distributions and probabilities offline. These are still not a production model, final fair probability, recommendation, or claim of betting edge.

### Phase 5B-4 offline predictive distributions

For target point prediction `mu` and a residual distribution fitted only from earlier OOF seasons:

```text
outcome = mu + residual
```

The implemented candidates are homoskedastic Normal, bounded-grid Student-t, chronological kernel-smoothed empirical residual, a transparent early/late × high/low-quality Normal scale, and a total-only skew-normal. Each output preserves target, horizon, point model/version, fit cutoff, residual-pool ID/rows, distribution parameters, dataset/feature hashes, and calibration version.

The integer lattice assigns `P(X = k) = F(k + 0.5) - F(k - 0.5)`. A home spread `s` settles against integer margin `M + s`; a total `L` settles against integer `T - L`. Integer lines can therefore have nonzero push mass and half-points have exactly zero. Win/push/loss is normalized to one without presentation rounding. Modern completed NCAAF moneyline outcomes cannot tie, so the zero-margin lattice mass is retained as an audit field and home/away probabilities are conditioned on non-tie settlement.

V1 advances the chronological margin power rating with quality-grouped Normal scale and total Ridge without opponent adjustment with an empirical residual distribution for later offline comparison. Normal remains the falsification benchmark. No post-hoc binary transform is promoted, and no market odds are used. This does **not** remove Phase 4's integer-line exclusion because the offline distribution has not passed locked/shadow or market-relative promotion gates and is not connected to pricing.

### Phase 5B-5 strong challengers and empirical discrete mass

XGBoost, LightGBM, and CatBoost use the same frozen folds, feature groups, three-configuration budget, and predeclared advancement gates. No margin tree displaced the chronological power rating. CatBoost `full_v1` improved total point MAE enough to advance as an offline point challenger, but its empirical-residual probability pairing did not beat Ridge plus empirical residual with paired intervals wholly below zero. Ridge therefore remains the total probability benchmark.

The empirical-discrete margin method starts with the quality-aware Normal probability mass on each integer margin `k` and applies a chronological residual-ratio correction learned only from earlier OOF seasons:

```text
base_mass(k) = F(k + 0.5) - F(k - 0.5)
ratio(r) = smoothed_observed_residual_mass(r) / smoothed_Normal_reference_mass(r)
adjusted_mass(k) proportional_to base_mass(k) * ratio(k - rounded_location)
```

The finite lattice is normalized exactly. This captures observed key-number clustering without hand-assigning probability to 3, 7, 10, or 14. It advances only for offline evaluation. Phase 4 still excludes integer-line EV because offline probability research has not passed locked 2025, prospective 2026 shadow, market-relative, and integration gates.

### Phase 5B-6 reconstructed preseason/personnel experiment

The additive `ncaaf-preseason-personnel-v1` feature layer evaluates source-supported preseason state without assigning hand-authored point values. Returning production, recruiting/talent, roster continuity, prior-leading-passer continuity, dated transfer activity, and head-coach continuity enter only through fold-local candidate models. The existing efficiency feature set and chronological power rating remain frozen benchmarks.

Historical CFBD preseason products retrieved in 2026 are reconstructed evidence, not genuine historical publication snapshots. Under `preseason-reconstructed-season-start-v1`, a team-season fact becomes eligible at the season's first scheduled FBS kickoff; a portal record also requires `transferDate` at or before that boundary. Actual ingestion time remains 2026. This permits an offline usefulness test but not a strict claim about what a game-day operator knew.

Missing coverage is distinct from a true zero. Portal counts before provider coverage begins are null with `portal_available=false`; a covered team-season with no observed movement may be zero. Reconstructed roster membership supports provider-ID overlap and whether the prior leading passer appears on the season roster, but does not identify the announced starter. Coach IDs support continuity/tenure only; they are excluded as categorical model features, and no coordinator or subjective coach-quality value is inferred.

The bounded experiment compares a preseason-residual adjustment to the chronological margin power rating, preseason-augmented Ridge to its frozen margin/total baselines, and a preseason-augmented CatBoost total challenger. Advancement uses predeclared paired, early-week, segment, validation, and complexity gates. Any successful candidate remains offline and cannot alter Phase 4 fair probability, EV, or recommendations.

Distribution evaluation uses NLL, quantile-integrated CRPS, PIT bins, 50/80/90/95% coverage and width, moneyline Brier/log loss, and synthetic three-way line scoring. Score clipping is used only to avoid `log(0)`; stored probabilities are not rounded. Full evidence and limitations are in `NCAAF_PROBABILITY_CALIBRATION_REPORT.md`.

Calibration is fitted only on earlier validation/OOF predictions and versioned separately. Candidate methods include distribution location/scale correction, empirical residual calibration, Platt/logistic, beta, and sufficiently supported isotonic calibration. Model uncertainty remains numerical and decomposed where possible: predictive scale/quantiles, aleatoric and epistemic components, model disagreement, calibration interval, effective sample, data completeness, roster/QB/weather flags, and market dispersion. Phase 5 does not decide how Phase 6 converts these into stakes.

The approved first operational workflow is one game-day-morning run at first scheduled kickoff minus three hours. Phase 5B-7A also approved the 60-minute research horizon but rejected 24 hours for the first market-aware corpus because 2020 failed its per-season coverage gate. Horizons must never be combined or substituted. A historical row may use only source and feature records available at its cutoff, including observation, source-snapshot/effective, and ingestion semantics appropriate to its declared availability mode. Closing lines, final availability, realized weather, postgame corrections, and future opponent results cannot leak backward.

Phase 5B-7C applies the existing `proportional-v1` calculation independently to each complete supported sportsbook pair, then uses `unweighted-median-v1` across books at one exact line. For spread and total, a book contributes only when its opposing sides are coherent; the consensus chooses the most-supported exact line deterministically and never averages probabilities from different points. A home spread of `-7` implies market expected home margin `+7`, because margin is `home_points - away_points`. Integer-line pushes remain separate labels and are not folded into wins or losses.

Full Phase 5B-7 compares all architectures on the frozen morning common cohorts. Residual models predict `actual - market expectation`; direct models add namespaced morning market fields to the frozen football feature set. A constrained blend uses `market + w * (football - market)`, with `w` fit only from prior-season OOF pairs and clipped to `[0,1]`. There is no manual 2024 weighting. Candidate uncertainty uses a chronological empirical residual pool by target and candidate; integer-lattice settlement produces separate win/push/loss mass.

Measured development/validation evidence did not support a proprietary margin or moneyline replacement. The margin blend shrank to zero football weight by 2022. A total market/Ridge blend improved paired MAE and three-way scores by a very small amount and advances only for a frozen Phase 5B-8 test. These results do not alter Phase 4 consensus, fair probability, EV, or recommendations.

Phase 5B-8 freezes that result rather than extending the search. Margin, spread, and moneyline use market consensus as the only holdout finalist; football power is diagnostic only. The total challenger is exactly `market + 0.17854145992095644 * (Ridge-no-opponent-adjustment - market)`, using the already-fitted 2024-evaluation Ridge artifact and chronological empirical push-aware calibration. Any failed practical-effect, proper-score, calibration, uncertainty, or broad-segment gate falls back to market consensus. See `NCAAF_FINALIST_FREEZE.md`.

Promotion requires reproducible versioned data/features/artifacts, automated leakage checks, chronological OOS evaluation, calibration, stable predefined segments, incremental proper-score evidence versus same-horizon market consensus, and prospective shadow performance. Phase 5B-8 freezes the one-time 2025 thresholds and minimum samples; passing them permits only shadow-candidate advancement, not recommendation influence.

These semantics are specified in the five `NCAAF_*` research documents. They do not alter Phase 4: proprietary probability remains null, consensus remains the final fair-probability source, and integer spreads/totals remain excluded until push probability is actually modeled and validated.

Model changes must be driven by reproducible out-of-sample evidence rather than short winning or losing streaks. Versioned portfolio-risk policies may adapt to equity, exposure, drawdown, uncertainty, and validated model performance, but any adaptation must be bounded, auditable, and evaluated separately from predictive-model changes. Straight-bet and future parlay-sleeve results must remain separately segmented.

## Testing requirements

All pricing and portfolio functions should be pure and deterministically tested for:

- positive and negative American odds;
- invalid zero, non-finite, and boundary inputs;
- two-way, three-way, and push-capable markets;
- vig-removal normalization invariants;
- equivalent-line matching;
- EV identities and sign behavior;
- Kelly boundaries and all exposure caps;
- rounding and settlement invariants;
- idempotent ledger mutations; and
- reproducible metric calculations from fixed fixtures.

Golden fixtures should preserve raw provider input, normalized records, and expected calculations without requiring live API access.


## Locked 2025 result

Phase 5B-9 opened the locked 2025 holdout once and applied the frozen Phase 5B-8 specification without refitting. On 758 identical total-market games, the blend failed the frozen MAE, multiclass Brier, and multiclass log-loss improvement gates. Market consensus therefore remains the total estimator as well as the margin/spread/moneyline benchmark. The holdout result cannot be used to tune the rejected blend or search for a replacement. See `NCAAF_2025_HOLDOUT_REPORT.md`.

## Registered NCAAF v1 fair value and shadow semantics

Phase 5B-10 registers market consensus as `retained_benchmark` for NCAAF margin, moneyline, spread, and total. Football power and Ridge remain `diagnostic`; the constrained market/Ridge total blend is `rejected`. Registry identities and versions are immutable, so a later lifecycle decision creates a new version rather than rewriting historical status.

The Phase 6 handoff is `ncaaf-fair-value-v1`: a retained benchmark emits canonical event/market/side, fair probability and line, explicit push probability where applicable, source as-of, contributing books, dispersion, quality, policy versions, and provenance. It emits no executable sportsbook price. Phase 6 must obtain the best executable offer separately before calculating edge or EV.

For retained consensus, half-point spread/total lines may carry zero push probability. An integer line cannot silently use zero; it requires an explicit validated push estimate. No rejected or diagnostic football probability may substitute into the fair-value contract.

Prospective shadow predictions beginning in 2026 are immutable pregame records at `morning_first_kickoff_minus_3h`. A changed market creates a new prediction version. Final score/outcome and evaluation metrics are appended separately and cannot alter the decision-time fair-value payload. Shadow evaluation is distinct from bankroll/bet settlement and does not authorize recommendations or stakes.

## Dashboard calculation boundary

Phase 6.5 is a rendering and human-approval surface, not another pricing engine. Every displayed fair probability, implied probability, edge, push-aware EV, stake, bankroll fraction, unit value, classification, exposure decision, and parlay status comes from the backend decision snapshot. Formatting percentages, currency, chart points, and stored line history in the browser does not create a competing calculation policy.

The UI always labels retained market consensus separately from the best executable sportsbook offer. Diagnostic football models remain visible as evidence but cannot supply the fair-value fields. A dashboard approval is not assumed successful until the server transaction completes and the client re-fetches portfolio/recommendation state.

## Live snapshot freshness versus provider quote age

Live eligibility uses separate lifecycle clocks under `snapshot-and-provider-quote-freshness-v2`. `MarketSnapshot.requested_at` is when POLARIS started the current provider request and is subject to the hard 120-second snapshot guard. `MarketObservation.observed_at` is the provider's sportsbook/market `last_update`; an unchanged but still-current quote may legitimately be several minutes old, so quote age is quality metadata rather than the snapshot cutoff. `MarketObservation.ingested_at` records local persistence, while an explicit refresh prices at `ingestion_completed_at`, after the transaction commits. This makes the triggering snapshot eligible for its own live decision without relaxing any historical cutoff.

A fresh snapshot with a five-minute-old quote remains eligible. A separate configurable seven-day quote-age ceiling fails closed on pathological source timestamps. Historical replay still enforces observation, snapshot, and ingestion cutoffs and selects the newest eligible snapshot first; it never substitutes the live post-commit cutoff.

The default live allowlist is `betmgm`, `betrivers`, `williamhill_us` (Caesars), `draftkings`, `fanatics`, and `fanduel`. The earlier three-book list was a configurable MVP starting set, not a frozen fair-value requirement. Proportional no-vig, unweighted-median consensus, and the minimum two-complete-book rule remain unchanged.
