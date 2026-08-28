# Project Context

## What this project is

This project began as a sports-betting portfolio agent connected to a custom ChatGPT interface. Its backend is hosted through Render and uses The Odds API for sportsbook market data.

The prototype workflow was:

1. A user asks the agent to analyze available games.
2. The agent retrieves sportsbook odds.
3. The agent identifies potentially attractive bets.
4. The user reviews the recommendations.
5. The user gives an explicit “green light” before a pick becomes official.
6. The official bet is recorded by the backend.
7. Bankroll and results are tracked.
8. Historical evidence is intended to improve later decisions.

The initial experimental bankroll was approximately $200. The code still defaults new portfolios to `$200.00`, configurable through `STARTING_BANKROLL`.

This is an experimental system. Its near- and medium-term purpose is extensive paper trading, methodology validation, and reliable measurement—not meaningful real-money deployment.

## League and market priorities

Immediate development priority is:

1. **NCAAF / College Football**
2. **NFL**
3. **NBA**

MLB, NHL, and WNBA are secondary. The current prototype supports NCAAB, which means men's college basketball. NCAAF is college football and is not currently a first-class supported league in code; V2 must add it explicitly rather than reusing or relabeling NCAAB behavior.

Initial NCAAF and NFL scope should emphasize full-game moneyline, spreads, and totals. Alternate spreads/totals and half/quarter markets follow after the core pricing and modeling pipeline is validated. Player props are later work because they require materially more player-level data and modeling.

NBA should ultimately support game markets and player props. Relevant NBA modeling inputs include player availability, projected minutes, usage, pace, rest, lineups, and matchup context.

## Product goal

The desired product is a quantitative sports-wagering portfolio-management platform, not a sports-picks chatbot or merely a market-consensus line scanner.

The intended platform combines:

- a market-pricing engine;
- sport-specific predictive models;
- structured sports and statistical data;
- injury, news, and research signals; and
- a portfolio-risk and bankroll engine.

Market consensus provides the initial pricing baseline and the benchmark against which proprietary models are evaluated. It is not assumed to be the final long-term fair probability for every sport or market.

The complete product should be able to:

- retrieve current prices across sportsbooks;
- normalize providers, events, markets, selections, lines, and prices;
- convert odds to implied probabilities and remove vig where appropriate;
- estimate and version fair probabilities;
- compare fair probabilities with executable sportsbook prices;
- calculate edge and expected value;
- rank opportunities using value, uncertainty, confidence, and portfolio risk;
- recommend defensible position sizes;
- enforce portfolio exposure and loss limits;
- require human approval before an official bet is recorded;
- preserve entry and closing prices and the full recommendation context;
- settle bets and maintain an auditable ledger;
- measure ROI/yield, CLV, drawdown, calibration, Brier score, log loss, hit rate, and sample size;
- analyze performance by sport, market, model/version, edge bucket, probability bucket, sportsbook, and other stable dimensions; and
- improve calibration and decision-making only when supported by sufficient evidence.

The recommendation interface should return up to a configurable Top N qualified opportunities for each selected league, with 10 as the normal display maximum. Top N is a ceiling, not a target: the system must return fewer recommendations, including zero, when fewer opportunities pass pricing, confidence, data-quality, and portfolio-risk rules.

## What exists today

The current implementation is a modular FastAPI prototype under `app/`, with a small root `main.py` compatibility entry point. It currently provides:

- health information;
- live/current odds retrieval from The Odds API;
- first-class NCAAF mapping alongside NFL, NCAAB, NBA, MLB, NHL, and WNBA;
- basic sport, market, sportsbook, and requested UTC calendar-date filtering;
- JSON-backed portfolios;
- manual bet recording and settlement;
- bankroll accounting; and
- basic ROI and hit-rate summaries overall and by sport/market bucket.

Phase 0 adds a Python 3.12 development baseline, pinned direct dependencies, deterministic tests with mocked provider calls, lint/type/test CI, sanitized provider errors, and finite/range validation for current financial metadata. The `/odds` date is a UTC filter over current/upcoming provider results; it is not a historical-odds query.

The backend accepts optional probability, edge, and EV fields, but it does not calculate or verify them. It stores optional closing data but does not calculate CLV. It does not learn or recalibrate models from history.

See `ARCHITECTURE.md` and `MODEL_LOGIC.md` for exact implemented-versus-planned boundaries.

## Product principles

### Human approval remains mandatory

Analysis and recommendations may be automated. For the foreseeable future, an official wager must require explicit human approval. Autonomous real-money sportsbook execution is outside the current roadmap.

### Value is not edge alone

A large modeled probability difference on a highly uncertain event is not automatically better than a smaller, more reliable advantage. Ranking and sizing must consider:

- offered price and implied probability;
- fair probability and its source;
- expected value;
- uncertainty and confidence;
- bankroll and current exposure;
- correlation with existing positions; and
- model quality and sample size.

### Market consensus is not a proprietary model

An initial legitimate V2 pricing engine may derive a fair estimate from no-vig, multi-book market prices. That is a market-consensus estimate. It must not be labeled a proprietary predictive model. Consensus is the baseline and benchmark; versioned sport-specific models should begin with NCAAF after the baseline engine exists and may supplement or outperform that baseline when reproducible out-of-sample evidence supports them.

### Recommendations must be complete and sparse when appropriate

Every recommendation should preserve and expose:

- best executable sportsbook and price;
- sportsbook implied probability;
- market-consensus probability;
- proprietary model probability when available;
- final fair probability and its derivation/version;
- probability edge and EV;
- model uncertainty/confidence;
- recommended stake and percentage of bankroll/equity; and
- a human-readable, source-traceable research explanation.

Qualification thresholds must remain independent of the requested Top N. The interface must never manufacture marginal bets merely to fill the display.

### Bankroll growth and risk are core product functions

The objective is long-term risk-adjusted bankroll growth, not reaching a fixed bankroll target. Position sizes should scale automatically with current portfolio equity through a conservative, versioned fractional-Kelly and risk-budget policy rather than static dollar bets.

One unit is a display abstraction tied to current bankroll/equity. It is not a permanently fixed dollar amount. The exact unit definition, Kelly fraction, confidence adjustment, and exposure caps remain empirical policy decisions that require paper-trading validation.

### Research signals must be traceable

News, injuries, and research should be ingested as timestamped, sourced, structured signals. An LLM may discover, extract, summarize, and explain research, but it must not make undocumented arbitrary probability adjustments. Any signal that affects a probability or stake must enter through a defined, versioned model or policy feature with provenance.

### Learning must be statistical, not reactive

The platform should improve through calibration analysis, controlled backtests, versioned models, and sufficient sample sizes. Recent wins alone are not evidence that confidence or stake sizes should increase. Historical trends and narratives should not influence predictions automatically; candidate historical variables must earn model weight through reproducible out-of-sample evidence. Small samples must not cause large automatic changes in weights or risk policy.

### Auditability matters

An official bet should eventually preserve enough information to reconstruct the recommendation and outcome exactly:

- provider event ID and normalized internal event ID;
- sport, league, participants, and scheduled start;
- market, selection, and spread/total point where relevant;
- sportsbook and entry odds;
- implied, no-vig, consensus, and/or proprietary probability as applicable;
- edge, EV, uncertainty/confidence, and recommended stake;
- bankroll/equity percentage, unit display value, and risk-policy version;
- traceable research sources and structured signals used;
- actual stake and bankroll before/after;
- recommendation, pricing, model, and policy versions;
- approval and entry timestamps;
- closing price/probability and capture time;
- result, settlement source, and realized P&L.

## Current technical debt

The following are known current-state problems, not solved capabilities:

- modular boundaries are established, but records remain untyped dictionaries and the prototype contracts still need V2 domain models;
- unsafe shared JSON persistence and non-failing I/O behavior that can still acknowledge an unsaved mutation;
- no authentication or portfolio ownership;
- caller-supplied EV and probabilities that are range-validated but not independently calculated or verified;
- caller-supplied win payouts that are sign-validated but not derived from entry odds;
- insufficient event, selection, and line metadata in recorded bets;
- no idempotency;
- no CLV calculation;
- no pricing/fair-probability engine;
- no structured sports/statistical or injury/news signal pipeline;
- no proprietary sport-specific predictive models;
- no staking or portfolio-risk engine; and
- no genuine model-learning or calibration loop.

## Success for V2

V2 should first become a trustworthy paper-trading system: reproducible prices, explicit financial semantics, durable data, conservative risk policy, human approval, deterministic tests, and honest measurement. The first vertical target is a complete NCAAF paper-trading baseline, followed closely by an evidence-based NCAAF model track. Predictive sophistication is valuable only when the foundations make experiments auditable.

