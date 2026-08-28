# Model, Pricing, EV, and Staking Logic

This document defines shared terminology and intended mathematical semantics. It clearly distinguishes current behavior from planned V2 behavior.

## Implementation status

| Capability | Current prototype | Planned V2 |
| --- | --- | --- |
| American odds retrieval | Implemented | Retain behind provider adapters |
| Implied-probability calculation | Not implemented | Deterministic pricing primitive |
| Vig removal | Not implemented | Versioned method per market |
| Multi-book consensus | Not implemented | Initial fair-price input |
| Proprietary predictive model | Not implemented | Optional later supplement |
| Edge calculation | Caller-supplied, unverified | Calculated and versioned |
| EV calculation | Caller-supplied, unverified | Calculated and versioned |
| Stake recommendation | Not implemented | Fractional-Kelly-informed, conservatively capped |
| Portfolio exposure control | Not implemented | Required before recommendations become official |
| Closing line value | Data fields exist; calculation absent | Capture and calculate consistently |
| Calibration/learning | Not implemented | Offline, evidence-based, and versioned |

The current `model_prob`, `book_prob`, `edge`, and `ev_per_1` fields are passive metadata supplied by the caller. Their names do not prove that a model or calculation occurred.

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

A consensus probability is market-derived. It is not a proprietary predictive model.

### Proprietary/model probability

A probability produced by a separately defined predictive model using features beyond mechanical market aggregation, or by a documented blend in which the proprietary component is explicit. Every estimate must identify model name, version, training/evaluation window, and creation time.

### Fair probability

The probability selected by a declared pricing policy for decision-making. Its source may initially be market consensus and later be a documented blend with a proprietary model. `fair_probability_source` and calculation version must accompany the value.

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

This provides a testable baseline. Sport-specific predictive models can later be evaluated against that baseline. They should be adopted only when out-of-sample evidence supports the change.

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

## Staking philosophy

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

Required risk concepts include:

- maximum risk per bet;
- maximum aggregate open exposure;
- maximum daily new risk and/or loss;
- exposure by sport, league, event, market, and model;
- correlation groups and mutually dependent outcomes;
- drawdown-aware risk reduction; and
- minimum confidence/data-quality thresholds.

## Bet and bankroll semantics

The current prototype treats `payout` as net profit/loss and deducts stake at placement:

```text
placement:  cash_bankroll -= stake
settlement: cash_bankroll += stake + net_payout
```

That arithmetic is consistent for a win, loss, or push if the supplied payout is correct. V2 should calculate settlement from immutable entry terms and a validated outcome rather than trusting arbitrary payout input.

V2 should distinguish:

- cash balance;
- reserved/open stake;
- total portfolio equity;
- realized P&L; and
- unrealized/open exposure.

Money rounding, currency, and sportsbook settlement rules must be explicit. Bankroll changes should be represented by auditable ledger entries rather than only a mutable balance.

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

