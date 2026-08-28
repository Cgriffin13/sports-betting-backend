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

An initial V2 fair-price engine may use implied probabilities, vig removal, and normalized multi-book consensus. Sophisticated machine learning is not required for the first legitimate pricing engine.

Consequences:

- Consensus methodology and inputs must be transparent and versioned.
- A market-derived estimate must not be called a proprietary predictive model.
- Proprietary models should later be evaluated against this reproducible baseline.

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

## Open decisions

Create separate ADR entries when these are resolved:

- relational database and data-access tooling;
- authentication and portfolio ownership;
- money representation and rounding policy;
- primary vig-removal method and consensus weighting;
- uncertainty representation and recommendation ranking;
- fractional-Kelly multiplier and exposure caps;
- primary CLV definition and closing benchmark;
- event matching and cross-provider identity;
- scheduler/background-job technology; and
- API versioning and migration policy.

