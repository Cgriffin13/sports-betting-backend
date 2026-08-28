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

## Product goal

The desired product is a quantitative sports-betting portfolio-management platform, not a sports-picks chatbot.

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

## What exists today

The current implementation is a single-file FastAPI prototype in `main.py`. It currently provides:

- health information;
- live/current odds retrieval from The Odds API;
- basic sport, market, and sportsbook filtering;
- JSON-backed portfolios;
- manual bet recording and settlement;
- bankroll accounting; and
- basic ROI and hit-rate summaries overall and by sport/market bucket.

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

An initial legitimate V2 pricing engine may derive a fair estimate from no-vig, multi-book market prices. That is a market-consensus estimate. It must not be labeled a proprietary predictive model. Sport-specific models may later supplement or replace the consensus estimate, with their source and version recorded.

### Learning must be statistical, not reactive

The platform should improve through calibration analysis, controlled backtests, versioned models, and sufficient sample sizes. Recent wins alone are not evidence that confidence or stake sizes should increase. Small samples must not cause large automatic changes in weights or risk policy.

### Auditability matters

An official bet should eventually preserve enough information to reconstruct the recommendation and outcome exactly:

- provider event ID and normalized internal event ID;
- sport, league, participants, and scheduled start;
- market, selection, and spread/total point where relevant;
- sportsbook and entry odds;
- implied, no-vig, consensus, and/or proprietary probability as applicable;
- edge, EV, uncertainty/confidence, and recommended stake;
- actual stake and bankroll before/after;
- recommendation, pricing, model, and policy versions;
- approval and entry timestamps;
- closing price/probability and capture time;
- result, settlement source, and realized P&L.

## Current technical debt

The following are known current-state problems, not solved capabilities:

- committed virtual environment and bytecode;
- no README, automated tests, or CI;
- unpinned dependencies;
- single-file architecture;
- unsafe shared JSON persistence and silent I/O failures;
- a request `date` that does not filter provider odds;
- raw provider exceptions that may expose credential-bearing URLs;
- no authentication or portfolio ownership;
- caller-supplied and unverified probabilities, edge, EV, and payouts;
- insufficient event, selection, and line metadata in recorded bets;
- no idempotency;
- no CLV calculation;
- no pricing/fair-probability engine;
- no staking or portfolio-risk engine; and
- no genuine model-learning or calibration loop.

## Success for V2

V2 should first become a trustworthy paper-trading system: reproducible prices, explicit financial semantics, durable data, conservative risk policy, human approval, deterministic tests, and honest measurement. Predictive sophistication is valuable only after those foundations make experiments auditable.

