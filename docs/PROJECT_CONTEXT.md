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

The initial experimental bankroll was approximately $200. The code defaults new portfolios to `$200.00`, configurable through `STARTING_BANKROLL`; this is configuration, not a schema or product constant.

This is an experimental system. Its near- and medium-term purpose is extensive paper trading, methodology validation, and reliable measurement—not meaningful real-money deployment.

## League and market priorities

Immediate development priority is:

1. **NCAAF / College Football**
2. **NFL**
3. **NBA**

MLB, NHL, and WNBA are secondary. The prototype supports NCAAB, which means men's college basketball. NCAAF is college football, is first-class in code, remains distinct from NCAAB, and maps to The Odds API's `americanfootball_ncaaf` key.

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

After the core straight-bet pricing, predictive-model, and portfolio-risk pipeline is proven, the platform may also offer an optional **Parlay of the Day**. This is a separate featured research sleeve, not a replacement for or quota within the ranked straight-bet portfolio. It may return at most one parlay per day/league scope, and zero is valid. The feature must never manufacture a parlay or weaken leg-level qualification standards merely to produce one.

## What exists today

The current implementation is a modular FastAPI prototype under `app/`, with a small root `main.py` compatibility entry point. It currently provides:

- health information;
- live/current odds retrieval from The Odds API;
- first-class NCAAF mapping alongside NFL, NCAAB, NBA, MLB, NHL, and WNBA;
- provider-neutral raw market snapshots and normalized full-game moneyline, spread, and total observations;
- stable events/provider mappings, canonical sportsbooks, exact line/period/side identity, freshness, and source provenance;
- Decimal implied-probability, proportional no-vig, unweighted-median consensus, edge, and EV calculations for a versioned market baseline;
- authenticated Top-N baseline opportunity analysis with explicit zero-result behavior, best executable price, uncertainty/data-quality fields, null proprietary probability, and complete source provenance;
- deterministic offline pricing replay that enforces both provider-observation and database-ingestion cutoff times;
- basic sport, market, sportsbook, and requested UTC calendar-date filtering in the compatibility API;
- PostgreSQL-backed owned portfolios and an auditable relational bankroll ledger;
- Decimal/NUMERIC money, transactional bet placement/settlement, persistent idempotency, and API-key authentication;
- manual bet recording and settlement;
- bankroll accounting; and
- basic ROI and hit-rate summaries overall and by sport/market bucket.

Phases 0–4 establish a Python 3.12 development baseline, modular boundaries, PostgreSQL/SQLAlchemy/Alembic persistence, a transactional ledger, raw and normalized market history, a reproducible consensus/EV baseline and offline replay, deterministic tests with mocked provider calls, lint/type/test CI, sanitized provider errors, finite/range validation, ownership, and an explicit legacy JSON import path. The `/odds` date is a UTC filter over current/upcoming provider results; it is not a historical-odds query.

Phase 5A has now produced the research specification for an NCAAF model tournament, data-source strategy, time-aware feature catalog, chronological evaluation protocol, and Phase 5B implementation sequence. It deliberately added no production model or application behavior. The first model hypothesis is a pair of calibrated margin/total predictive distributions, evaluated alongside component-score and direct-win challengers across naive, Elo, regularized, boosted-tree, hierarchical, residual, and learned-ensemble approaches. Market consensus remains the implemented final fair probability until a candidate proves incremental out-of-sample value and completes shadow evaluation.

Phase 5B-2 now provides the offline, leakage-tested research input layer: normalized immutable Parquet facts, explicit historical availability, three separate prediction horizons, rolling/prior/opponent-adjusted features, quality/missingness fields, chronological folds, and reproducible manifests. It did not train a model, inspect the sealed 2025 outcomes, or change production pricing behavior.

Phase 5B-6 adds a separate reconstructed preseason/personnel research layer from bounded CFBD products. It preserves exact source manifests and real retrieval time, uses conservative versioned availability, keeps missing coverage distinct from zero, and evaluates features only through chronological offline ablations. It does not create a production proprietary probability or change the API.

The Phase 4 pricing path calculates probability, edge, and EV independently, but the legacy bet-entry endpoint still accepts optional caller-supplied fields and does not assert that they came from Phase 4. Pricing outputs remain transient until a later official recommendation boundary. The backend stores optional closing data but does not calculate CLV. It does not learn or recalibrate models from history.

See `ARCHITECTURE.md` and `MODEL_LOGIC.md` for exact implemented-versus-planned boundaries.

The Phase 5A design details are in `NCAAF_MODEL_RESEARCH.md`, `NCAAF_DATA_SOURCES.md`, `NCAAF_FEATURE_CATALOG.md`, `NCAAF_BACKTEST_DESIGN.md`, and `NCAAF_EXPERIMENT_PLAN.md`.

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

### Parlays are an optional, subordinate research sleeve

The primary objective remains long-term risk-adjusted bankroll growth through individually qualified straight bets. A featured parlay is a later-phase experiment and may be considered only when every component leg independently satisfies the same applicable qualification standards.

The system must compare an executable sportsbook parlay payout with a modeled joint fair probability. Marginal leg probabilities may be multiplied only when the independence assumption is defensible. Correlated outcomes—especially same-game combinations—require explicit correlation modeling, simulation, or another validated joint-probability method before they can be treated as production-quality recommendations. Early experiments should prefer cross-event legs where independence assumptions are more credible.

Parlays use a separate conservative risk budget and generally lower stake caps than qualified straight bets. Their performance must be segmented from straight bets, and the portfolio engine must be able to reduce or disable the parlay sleeve when out-of-sample evidence indicates that it harms risk-adjusted performance.

### Bankroll growth and risk are core product functions

The objective is long-term risk-adjusted bankroll growth, not reaching a fixed bankroll target. Position sizes should scale automatically with current portfolio equity through a conservative, versioned fractional-Kelly and risk-budget policy rather than static dollar bets.

One unit is a display abstraction tied to current bankroll/equity. It is not a permanently fixed dollar amount. The exact unit definition, Kelly fraction, confidence adjustment, and exposure caps remain empirical policy decisions that require paper-trading validation.

### Research signals must be traceable

News, injuries, and research should be ingested as timestamped, sourced, structured signals. An LLM may discover, extract, summarize, and explain research, but it must not make undocumented arbitrary probability adjustments. Any signal that affects a probability or stake must enter through a defined, versioned model or policy feature with provenance.

### Learning must be statistical, not reactive

The platform should improve through historical prediction snapshots, closing prices, outcomes, calibration analysis, CLV, drawdown, segmented performance, controlled backtests, versioned models, and sufficient sample sizes. Short winning or losing streaks are not evidence for mechanical probability, model-weight, or stake changes. Historical trends and narratives should not influence predictions automatically; candidate variables and predictive-model changes must earn weight through reproducible out-of-sample evidence.

Portfolio-risk policies may respond to current equity, open exposure, drawdown, uncertainty, and validated model performance, but those responses must be explicit, bounded, versioned, and reproducible. Small samples must not cause large automatic changes in model weights, qualification standards, or risk policy.

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
- caller-supplied EV and probabilities on legacy official-bet input that are range-validated but not reconciled to Phase 4 outputs;
- caller-supplied win payouts that are sign-validated but not derived from entry odds;
- insufficient event, selection, and line metadata in recorded bets;
- lightweight API-key authentication is suitable only for the private service, not a mature identity system;
- SQLite unit tests do not reproduce PostgreSQL row-lock scheduling; production concurrency still needs PostgreSQL integration/load validation;
- operational PostgreSQL backup/restore drills remain future hardening work;
- integer spreads/totals are preserved but conservatively excluded from Phase 4 EV qualification because push probability is not yet modeled;
- no persisted official recommendation snapshot connecting a Phase 4 opportunity to later approval/placement;
- no outcome backtest or portfolio simulation beyond deterministic pricing replay;
- no CLV calculation;
- no structured sports/statistical or injury/news signal pipeline;
- no proprietary sport-specific predictive models;
- no staking or portfolio-risk engine; and
- no genuine model-learning or calibration loop.

## Success for V2

V2 should first become a trustworthy paper-trading system: reproducible prices, explicit financial semantics, durable data, conservative risk policy, human approval, deterministic tests, and honest measurement. The first vertical target is a complete NCAAF paper-trading baseline, followed closely by an evidence-based NCAAF model track. Predictive sophistication is valuable only when the foundations make experiments auditable.

> Current research status (2026-08-30): Phase 5B-6 completed bounded reconstructed preseason/personnel research. Recruiting/talent and a preseason-adjusted margin power candidate advance only offline; the existing probability benchmarks remain. These candidates do not feed the live API; market consensus remains the implemented fair-probability source, and 2025 remains sealed.

> Phase 5B-7A then completed the bounded historical-odds acquisition gate with 67 unique requests and 2,010 credits. It is a conditional GO for specified FBS-vs-FBS morning/60-minute/near-close market combinations only. It establishes data feasibility, not model edge, profitability, or production readiness.
>
> Phase 5B-7B subsequently built the canonical 2020–2024 historical-market dataset. Complete-cohort morning observations are primary evidence; an outcome-blind stratified 60-minute/near-close sample is secondary robustness evidence only. The dataset remains offline and does not alter production pricing, recommendations, or fair probabilities.

> Phase 5B-7C now provides the deterministic offline comparison layer: exact-line book pairing, versioned no-vig/median consensus, selected same-horizon OOF joins, explicit push labels, residual targets, and common model-ready cohorts. It performs no provider calls and fits no market-aware model. Near-close remains consensus-only because no same-horizon football OOF prediction exists.

> Full Phase 5B-7 completed the morning market-aware tournament. Market consensus remained the clear margin and moneyline benchmark; standalone football, residual, and direct market-feature candidates did not add stable market-relative value. A constrained market/Ridge total blend produced a statistically detectable but practically tiny improvement and advances only as a narrow Phase 5B-8 challenger. Nothing is promoted or connected to production, and 2025 remains sealed.
