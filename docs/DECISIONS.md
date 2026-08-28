# Decision Log

This file is the durable Architecture Decision Record (ADR) index for product and engineering choices. Add a dated entry when a decision changes architecture, model semantics, risk policy, data contracts, or product boundaries. Do not rewrite prior decisions to hide history; mark them superseded and link the replacement.

Statuses used here:

- **Accepted**: current intended direction, whether or not fully implemented.
- **Current prototype**: describes an implementation choice that exists but is not necessarily the target.
- **Proposed**: a likely direction requiring an explicit future decision.
- **Superseded**: replaced by a later decision.

## ADR-001 — Paper trading before meaningful real-money use

- Date: 2026-08-28
- Status: Accepted

The platform is experimental and should validate its methodology through extensive paper trading. Reliable data, auditability, calibration, and risk measurement take priority over real-money operation.

Consequences:

- Roadmap success is measured first by reproducible evidence and operational correctness.
- Paper results must not be presented as proof of future profitability.
- Meaningful real-money use requires a later explicit decision and evidence gate.

## ADR-002 — Human approval for every official bet

- Date: 2026-08-28
- Status: Accepted

Automated analysis and recommendations are allowed, but an official bet requires explicit human approval. Autonomous real-money sportsbook execution is outside the current roadmap.

Consequences:

- Recommendation and approval are separate persisted states.
- Analysis must not directly mutate the official bet ledger.
- Approval identity, timestamp, and accepted stake/price should be auditable.

## ADR-003 — Code and documentation have different truth domains

- Date: 2026-08-28
- Status: Accepted

The repository code is the source of truth for currently implemented behavior. These documents are the source of truth for intended product behavior and architectural direction.

Consequences:

- Planned features must be labeled as planned.
- A conflict must be surfaced and resolved, not silently rationalized.
- Behavior and architecture changes should update documentation in the same change.

## ADR-004 — Initial market data provider

- Date: Historical; recorded 2026-08-28
- Status: Current prototype

The prototype uses The Odds API and is hosted through Render. Provider calls currently live directly in `main.py`.

Consequences:

- Existing behavior depends on provider sport keys, book titles, quotas, and payloads.
- V2 should preserve The Odds API as an initial adapter while removing it from domain logic.
- Multi-provider support is a design requirement, not an implemented capability.

## ADR-005 — Market consensus is the initial V2 pricing baseline

- Date: 2026-08-28
- Status: Accepted

An initial V2 fair-price engine may use implied probabilities, vig removal, and normalized multi-book consensus. Sophisticated machine learning is not required for the first legitimate pricing engine. Consensus remains the baseline and benchmark against which proprietary models are evaluated, but it is not assumed to be the final long-term fair probability.

Consequences:

- Consensus methodology and inputs must be transparent and versioned.
- A market-derived estimate must not be called a proprietary predictive model.
- Proprietary models should be evaluated against this reproducible baseline, beginning with NCAAF after the baseline engine exists.
- Consensus, proprietary-model, and final fair probabilities must remain separately observable.

## ADR-006 — Recommendations are not ranked by edge alone

- Date: Historical; recorded 2026-08-28
- Status: Accepted

Probability edge alone is insufficient for ranking. EV, estimated probability, uncertainty, confidence, price quality, bankroll risk, exposure, and correlation all matter.

Consequences:

- Ranking logic must expose its components.
- Large uncertain edges may be rejected or ranked below smaller reliable opportunities.
- “No bet” is a valid output.

## ADR-007 — Never blindly use full Kelly

- Date: Historical; recorded 2026-08-28
- Status: Accepted

Full Kelly staking is too aggressive for the intended experimental system and estimation uncertainty. V2 should investigate fractional Kelly combined with conservative caps and portfolio controls.

Historical 1–3% normal and 5–10% exceptional stake ranges are context only, not fixed policy.

Consequences:

- Full Kelly must not be the automatic stake.
- Confidence, daily risk, aggregate exposure, correlation, and drawdown controls are required.
- Exact multipliers and caps remain an open, testable policy decision.

## ADR-008 — Production persistence must be transactional and auditable

- Date: 2026-08-28
- Status: Accepted

Shared mutable JSON state is inadequate for V2. Production persistence must support transactions, constraints, concurrency, idempotency, migrations, and reconstruction of bankroll changes.

Consequences:

- The current JSON file remains prototype debt.
- A ledger-style representation is preferred for bankroll movements and bet states.
- PostgreSQL is a likely candidate on Render, but the database and data-access tooling are not yet selected.

## ADR-009 — Preserve immutable decision-time context

- Date: 2026-08-28
- Status: Accepted

Official bets and recommendations must preserve the information available at decision time, including exact event/market identity, line, offered price, probability sources, EV, stake logic, bankroll, versions, approval, and timestamps.

Consequences:

- Later model outputs must not overwrite historical predictions.
- Entry and closing observations should be stored as reproducible snapshots.
- Analytics must trace back to immutable source records.

## ADR-010 — Learning is offline, versioned, and evidence-based

- Date: 2026-08-28
- Status: Accepted

The current system does not learn. V2 learning should use calibration, Brier score, log loss, CLV, ROI, drawdown, segmentation, sample size, and out-of-sample evaluation. Recent wins or small samples must not automatically increase confidence, weights, or stakes.

Consequences:

- Model and policy changes require versioning and reproducible evaluation.
- Silent online mutation of production logic is not allowed.
- Promotion and rollback criteria must be defined before automated model updates.

## ADR-011 — Initial bankroll is configuration, not a product invariant

- Date: Historical; recorded 2026-08-28
- Status: Accepted

The original test bankroll was approximately $200, and the current code defaults to `$200.00`. This value is historical test context and runtime configuration, not a universal staking assumption.

Consequences:

- Calculations should operate on explicit portfolio state.
- Tests may use fixed bankroll fixtures but should not embed `$200` as a domain rule.

## ADR-012 — League development priority is NCAAF, NFL, then NBA

- Date: 2026-08-28
- Status: Accepted

Immediate development priority is NCAAF/College Football, followed by NFL and NBA. MLB, NHL, and WNBA are secondary. The prototype's NCAAB support is college basketball and must not be confused with NCAAF.

Consequences:

- NCAAF becomes the first new first-class league and predictive-model track.
- League identifiers, provider mappings, datasets, features, and evaluation remain explicit.
- Shared platform components should not erase sport-specific modeling requirements.

## ADR-013 — The product combines market, model, research, and portfolio evidence

- Date: 2026-08-28
- Status: Accepted

The ultimate product is a quantitative sports-wagering portfolio manager, not merely a market-consensus line scanner. It combines market pricing, sport-specific predictive models, structured sports/statistical data, traceable injury/news/research signals, and portfolio-risk controls.

Consequences:

- Market consensus is a baseline and benchmark, not necessarily the final estimate.
- Final fair probability must expose its component probabilities and versioned policy.
- Sport/statistical and research-data ingestion are architectural components, not informal prompt context.

## ADR-014 — Top N is a maximum, never a quota

- Date: 2026-08-28
- Status: Accepted

The recommendation interface returns up to a configurable Top N qualified opportunities per selected league, with 10 as the normal display maximum. Qualification standards do not change to fill the display.

Consequences:

- Ranking and Top N truncation occur only after data, EV, uncertainty, and portfolio-risk qualification.
- Fewer than Top N, including zero, is correct behavior.
- Duplicate or marginal opportunities must not be manufactured to meet a count.

## ADR-015 — Recommendations expose the complete decision basis

- Date: 2026-08-28
- Status: Accepted

Every recommendation preserves and exposes the best executable sportsbook price, implied probability, consensus probability, proprietary model probability when available, final fair probability, edge, EV, uncertainty/confidence, recommended stake, portfolio-equity percentage, and a human-readable research explanation.

Consequences:

- Probability sources and pricing/model/risk versions remain separately identifiable.
- Explanations link to traceable structured research signals.
- A missing proprietary model is represented explicitly, not fabricated or relabeled from consensus.

## ADR-016 — Stakes scale with equity under versioned conservative risk policy

- Date: 2026-08-28
- Status: Accepted

The bankroll objective is long-term risk-adjusted growth rather than a fixed target. Position sizes scale with current portfolio equity under a conservative fractional-Kelly/risk-budget framework rather than static dollar bets. A unit is a display abstraction tied to current bankroll/equity.

Consequences:

- Store stake dollars, equity percentage, displayed units, equity basis, and policy version at recommendation time.
- Full Kelly remains prohibited.
- Exact unit fraction, equity definition, Kelly multiplier, and exposure budgets require empirical validation.

## ADR-017 — Research signals are traceable; LLM adjustments are not arbitrary

- Date: 2026-08-28
- Status: Accepted

News, injuries, and research are ingested as sourced, timestamped, structured signals. An LLM may discover, extract, summarize, and explain them but may not apply undocumented arbitrary probability adjustments.

Consequences:

- Every probability-affecting signal has provenance and enters through a versioned feature or policy.
- Conflicts, freshness, and extraction confidence remain visible.
- Human-readable explanations do not substitute for reproducible model inputs.

## ADR-018 — Sport-specific modeling starts after the baseline engine

- Date: 2026-08-28
- Status: Accepted

Sport-specific modeling is not deferred until the final experimentation phase. After the market-pricing baseline is reproducible, an NCAAF predictive-model track begins, followed by NFL and NBA.

Consequences:

- NCAAF models are evaluated against consensus with chronological out-of-sample tests.
- Historical variables earn weight only through reproducible evidence.
- A model that does not beat or complement the baseline is not forced into final fair probability.

## ADR-019 — Game markets precede expanded markets and player props

- Date: 2026-08-28
- Status: Accepted

NCAAF and NFL initially prioritize full-game moneyline, spreads, and totals. Alternate spreads/totals and half/quarter markets follow core-pipeline validation. Player props are later because they require player-level projections and more extensive data/modeling. NBA ultimately supports game markets and player props.

Consequences:

- Market expansion requires explicit identity, settlement, data, and test support.
- NBA player availability, minutes, usage, pace, rest, lineup, and matchup inputs are important model requirements.
- No prop recommendation is produced without a reproducible player projection.

## ADR-020 — Opening-weekend NCAAF baseline is an explicit milestone

- Date: 2026-08-28
- Status: Accepted

The project should capture an opening-weekend NCAAF paper-trading baseline with odds, consensus calculations, qualified recommendations, paper stakes, closing prices, and outcomes even if the first proprietary model is not production-ready.

Consequences:

- Consensus may serve as the explicitly labeled final fair source for this milestone.
- Missing proprietary probability remains null/not available.
- The milestone exercises the complete observable lifecycle and creates a benchmark dataset for later NCAAF models.

## ADR-021 — `/odds` date semantics use UTC filtering

- Date: 2026-08-28
- Status: Accepted

The current The Odds API integration is a current/upcoming feed, not a historical query. The required `/odds` request date is interpreted as a UTC calendar date, and the backend retains only provider games whose timezone-aware `commence_time` falls on that UTC date.

Consequences:

- Responses expose `date_timezone: "UTC"`.
- Naive, missing, or invalid provider timestamps are excluded because their calendar date is ambiguous.
- Past dates normally produce no games and must not be described as historical-odds retrieval.
- A future user-local or event-local date convention requires a superseding decision and an explicit timezone contract.

## ADR-022 — Python 3.12 and pinned direct dependencies form the development baseline

- Date: 2026-08-28
- Status: Accepted

Python 3.12.x is the supported local and CI runtime. Runtime and development requirements use exact direct dependency pins, and CI runs Ruff, mypy, and pytest without live provider credentials.

Consequences:

- Runtime changes should remain compatible with Python 3.12 until a superseding decision.
- Dependency updates are explicit reviewed changes rather than implicit floating upgrades.
- Deterministic tests and mocked provider boundaries are required for critical behavior.

## Open decisions

Create separate ADR entries when these are resolved:

- relational database and data-access tooling;
- authentication and portfolio ownership;
- money representation and rounding policy;
- primary vig-removal method and consensus weighting;
- final fair-probability selection/blending and proprietary-model promotion gates;
- NCAAF structured-data providers, feature set, model family, and evaluation windows;
- NFL/NBA data providers and league-specific model scope;
- injury/news/research sources, provenance schema, conflict handling, and signal freshness;
- uncertainty representation, qualification thresholds, ranking, Top N tie-breaking, and per-league behavior;
- portfolio-equity definition, unit display policy, fractional-Kelly multiplier, and exposure caps;
- primary CLV definition and closing benchmark;
- event matching and cross-provider identity;
- scheduler/background-job technology; and
- API versioning and migration policy;
- exact calendar/scope and operational readiness criteria for the NCAAF opening-weekend milestone; and
- player-prop expansion gates and required projection quality.

