# Roadmap

The roadmap prioritizes a trustworthy paper-trading platform before predictive sophistication or real-money operation. Phases are ordered by dependency, but small vertical slices are preferred over a long-lived rewrite.

## Phase 0 — Repository and safety baseline

Goal: make the prototype safe to change and honest about its behavior.

- Add durable project documentation and a concise root README.
- Remove the tracked virtual environment and bytecode from version control while retaining appropriate ignore rules.
- Pin or lock dependencies and document the supported Python version.
- Add formatting, linting, type-checking, and test configuration.
- Add CI for deterministic checks.
- Add characterization tests for current endpoints and bankroll settlement.
- Sanitize provider failures so secrets and credential-bearing URLs cannot escape.
- Validate finite numeric inputs, odds domains, probabilities, stake, and payout consistency where current contracts permit.
- Correct or redesign the misleading odds `date` contract.

Exit criteria:

- A clean checkout contains only source-controlled project assets.
- Tests reproduce current critical behavior without live provider calls.
- Provider errors cannot reveal credentials.
- Known behavior changes are explicit and documented.

## Phase 1 — Modularize without changing product semantics

Goal: establish boundaries that can support V2.

- Introduce application configuration with explicit validation.
- Separate API routes, Pydantic contracts, provider adapters, domain calculations, persistence interfaces, and application services.
- Wrap The Odds API behind a provider-neutral interface.
- Add structured logging and request correlation without logging secrets.
- Define versioned internal identifiers and UTC timestamp conventions.
- Preserve current externally required behavior through tests while extracting pure logic.

Exit criteria:

- Routes contain orchestration, not provider parsing or financial formulas.
- Provider responses are normalized through tested adapters.
- Core logic can be tested without FastAPI, disk, or network access.

## Phase 2 — Durable portfolio and bet ledger

Goal: replace mutable JSON state with auditable transactional persistence.

- Select the relational database and data-access approach; PostgreSQL is the leading candidate but not yet decided.
- Define schemas for users/owners, portfolios, bankroll ledger entries, recommendations, approvals, bets, state transitions, and settlements.
- Capture full event, market, selection, point, provider, book, entry price, timestamps, bankroll, and version metadata.
- Add migrations, constraints, transactions, and backup/recovery procedures.
- Add authentication and portfolio ownership.
- Add idempotency to every mutation.
- Migrate or explicitly archive prototype JSON data with reconciliation totals.

Exit criteria:

- Concurrent requests cannot lose bankroll or settlement updates.
- Every balance can be reconstructed from ledger entries.
- Duplicate requests do not create duplicate bets or settlements.
- Unauthorized portfolio access is rejected.

## Phase 3 — Market-data ingestion and normalization

Goal: create reproducible, provider-neutral market snapshots.

- Persist raw provider responses and normalized observations.
- Normalize events, participants, start times, market periods, selections, exact spread/total points, books, and prices.
- Implement event matching with confidence and review paths for ambiguity.
- Add freshness, quota, cache, retry, and rate-limit policies.
- Support scheduled snapshots and closing-price capture.
- Design for additional providers without requiring a second provider immediately.

Exit criteria:

- Every normalized price traces back to a raw observation.
- Only truly equivalent markets are compared.
- Stale or ambiguous data is identifiable and excluded from automated recommendations.

## Phase 4 — Baseline pricing and EV engine

Goal: generate transparent market-consensus opportunities without claiming a proprietary model.

- Implement and test American/decimal odds conversion.
- Implement a versioned initial vig-removal method.
- Build a transparent multi-book consensus policy with outlier and staleness handling.
- Calculate offered implied probability, consensus/fair probability, probability edge, and EV.
- Attach source, version, inputs, and uncertainty/data-quality indicators to every calculation.
- Create deterministic fixtures and offline replay/backtest tooling.

Exit criteria:

- Every recommendation can reproduce its fair price and EV from stored observations.
- Market consensus is labeled accurately.
- Numerical and market-identity edge cases are covered by tests.

## Phase 5 — Portfolio risk, staking, and approval

Goal: turn positive-EV observations into conservative, reviewable portfolio recommendations.

- Define a fractional-Kelly candidate policy; never use full Kelly.
- Add per-bet, daily, aggregate, sport/market, event, and correlation exposure limits.
- Add confidence/data-quality adjustments and drawdown-aware reductions.
- Define ranking rules that consider EV, uncertainty, liquidity/freshness, and portfolio impact—not edge alone.
- Make “no bet” a first-class decision.
- Implement immutable recommendation snapshots and explicit human approve/reject actions.
- Keep official bets as paper bets; do not add autonomous sportsbook execution.

Exit criteria:

- Risk invariants hold under deterministic scenario tests.
- An analysis cannot become an official bet without recorded human approval.
- Stake recommendations are explainable and reproducible.

## Phase 6 — Closing, settlement, and analytics

Goal: measure outcomes without compromising the historical record.

- Capture closing observations using a defined benchmark and time policy.
- Implement validated settlement rules and provenance.
- Calculate realized P&L, ROI/yield, CLV, drawdown, hit rate, and exposure histories.
- Segment results by stable dimensions including model/version, sport, market, sportsbook, edge, and probability buckets.
- Clearly separate cash, reserved stake, equity, realized P&L, and open exposure.

Exit criteria:

- Entry, close, settlement, and bankroll movements reconcile.
- Analytics are reproducible from immutable source records.
- Metric definitions match `MODEL_LOGIC.md` and are covered by fixtures.

## Phase 7 — Calibration and model experimentation

Goal: improve estimates through statistically defensible evidence.

- Add Brier score, log loss, reliability plots/tables, uncertainty intervals, and sample-size reporting.
- Establish time-based out-of-sample evaluation and model registries/versioning.
- Compare proprietary sport-specific models against the market-consensus baseline.
- Define conservative promotion, rollback, and weight-change criteria.
- Prevent small samples or recent streaks from automatically increasing confidence or stakes.

Exit criteria:

- Model changes are supported by reproducible out-of-sample evidence.
- Historical predictions remain tied to the version that produced them.
- No online “learning” silently mutates production policy.

## Phase 8 — Paper-trading production hardening

Goal: operate the research platform reliably over long observation periods.

- Add monitoring, alerts, audit logs, restore drills, provider health, quota dashboards, and runbooks.
- Add performance and load testing, security review, and data-retention policy.
- Run extended paper-trading evaluations across seasons and market conditions.
- Define explicit evidence gates before any discussion of meaningful real-money use.

Autonomous real-money execution remains out of scope. Any change to that boundary requires a new explicit product decision and a separate security, legal, operational, and risk review.

## Immediate recommended sequence

1. Complete Phase 0 hygiene and security fixes.
2. Add characterization tests before restructuring `main.py`.
3. Extract provider and domain boundaries.
4. Decide the database/ownership architecture.
5. Build the durable ledger before implementing sophisticated pricing or staking.

