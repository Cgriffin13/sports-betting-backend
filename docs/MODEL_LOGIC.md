# Model, Pricing, EV, and Staking Logic

This document defines shared terminology and intended mathematical semantics. It clearly distinguishes current behavior from planned V2 behavior.

## Implementation status

| Capability | Current prototype | Planned V2 |
| --- | --- | --- |
| American odds retrieval | Implemented | Retain behind provider adapters |
| First-class NCAAF support | Provider key, aliases, and core market retrieval implemented | Expand through normalized snapshots and modeling |
| Implied-probability calculation | Not implemented | Deterministic pricing primitive |
| Vig removal | Not implemented | Versioned method per market |
| Multi-book consensus | Not implemented | Initial fair-price baseline and benchmark |
| Proprietary predictive model | Not implemented | NCAAF track after baseline engine, then NFL/NBA |
| Structured sports/news signals | Not implemented | Traceable league-specific inputs |
| Edge calculation | Caller-supplied, unverified | Calculated and versioned |
| EV calculation | Caller-supplied, unverified | Calculated and versioned |
| Stake recommendation | Not implemented | Fractional-Kelly-informed, conservatively capped |
| Portfolio exposure control | Not implemented | Required before recommendations become official |
| Parlay recommendation | Not implemented | Optional later research sleeve after the straight-bet pipeline is proven |
| Closing line value | Data fields exist; calculation absent | Capture and calculate consistently |
| Calibration/learning | Not implemented | Offline, evidence-based, and versioned |

The current `model_prob`, `book_prob`, `edge`, and `ev_per_1` fields are passive metadata supplied by the caller. Their names do not prove that a model or calculation occurred.

The prototype supports both NCAAF and NCAAB as distinct canonical leagues. NCAAB is college basketball; it must never be substituted for college football in model data, league identifiers, or evaluation.

## League and market modeling sequence

Development priority is NCAAF, NFL, then NBA; MLB, NHL, and WNBA are secondary.

- **NCAAF:** begin with full-game moneyline, spreads, and totals. Candidate model inputs may include team strength, opponent adjustment, returning production, coaching/system continuity, tempo, efficiency, travel, venue, weather, injuries/availability, and other validated features.
- **NFL:** follow the same initial game-market progression. Sport-specific inputs may include team efficiency, personnel/availability, rest, travel, weather, matchup, and market context.
- **NBA:** support game markets first and later player props. Player availability, projected minutes, usage, pace, rest, lineup combinations, and matchup data are central candidates.

Alternate spreads/totals and half/quarter markets follow only after the full-game pipeline is validated. Player props are later because they require player-level projections, market-specific settlement rules, and substantially more data/modeling.

These are candidate feature domains, not permission to add them heuristically. Every historical variable must earn weight through reproducible out-of-sample evidence.

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

### Consensus probability

A fair-price estimate derived from multiple market observations after normalization and vig removal. Consensus construction may account for book quality, liquidity proxies, staleness, outliers, and observation time.

Only equivalent markets may be combined. A spread at `-3.0` is not the same price object as a spread at `-3.5`; totals, periods, overtime rules, and participant identity also matter.

A consensus probability is market-derived. It is not a proprietary predictive model. It is the initial baseline and ongoing benchmark for measuring whether a proprietary model adds predictive or economic value.

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

### Confidence and uncertainty

Probability is an estimate of event likelihood. Confidence describes the reliability of that estimate; uncertainty describes its dispersion or error. They are not interchangeable, and confidence must not be added to probability as an arbitrary bonus.

V2 should represent uncertainty through defensible evidence such as:

- dispersion among comparable no-vig books;
- price staleness and market liquidity proxies;
- historical calibration error for the model and probability region;
- disagreement between market consensus and proprietary estimates;
- sample size and out-of-sample stability; and
- known data-quality flags.

The uncertainty representation and any adjustment to ranking or staking must be versioned and tested.

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

This provides a testable baseline. An NCAAF predictive-model track should begin as soon as the baseline pricing engine is reproducible; it does not wait until the final roadmap phase. NFL and NBA follow. Proprietary models should be promoted into final-fair-probability decisions only when out-of-sample evidence shows value relative to the consensus benchmark.

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

The precise score is an open decision. Prefer explicit filters and interpretable components over an unexplained composite score.

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

Unresolved policies include permitted leg counts, minimum EV, independence tests, correlation thresholds/models, same-game eligibility, parlay Kelly multiplier, stake and sleeve exposure caps, league/day scope, executable-price freshness, CLV convention, and promotion/disablement evidence gates. Full Kelly remains prohibited.

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

