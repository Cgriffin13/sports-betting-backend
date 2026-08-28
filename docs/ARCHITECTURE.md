# Architecture

This document separates the architecture that exists in code from the architecture proposed for V2. Planned components must not be represented as implemented.

## Current architecture

### Runtime shape

The application is a synchronous FastAPI service contained entirely in `main.py`.

```text
Custom ChatGPT client / API caller
              |
              v
       FastAPI routes in main.py
          |              |
          v              v
   The Odds API     process-global DB dict
                           |
                           v
                 data/portfolio_db.json
```

Render is the intended host. `ODDS_API_KEY`, `STARTING_BANKROLL`, and `DATA_DIR` are read from environment variables at process startup. Comments in the code recommend a Render Disk mounted at `/var/data` for persistence.

### Current modules and files

- `main.py`: application creation, environment loading, models, normalization, provider calls, persistence, bankroll logic, settlement, and statistics.
- `requirements.txt`: unpinned runtime dependencies.
- `data/.gitkeep`: placeholder for runtime data.
- `.gitignore`: ignores local secrets, virtual environments, and bytecode.
- `venv/` and root `__pycache__/`: tracked development artifacts that should not be repository source.

### Current API surface

| Endpoint | Current behavior |
| --- | --- |
| `GET /health` | Reports service status, whether an odds key exists, storage paths, and UTC time. |
| `POST /odds` | Fetches current/upcoming odds for configured sports, markets, and books. The request date is echoed but not sent to the provider. |
| `GET /portfolio/{portfolio_id}` | Auto-creates missing portfolios and returns bankroll plus recent bets. |
| `POST /bets` | Records a caller-provided bet and deducts its stake. |
| `POST /bet-result` | Records a caller-provided result and net payout, then updates bankroll. |
| `GET /portfolio/{portfolio_id}/stats` | Computes settled-bet totals and sport/market buckets. |

### Current data flow

Odds retrieval:

1. Normalize requested sport and market labels.
2. Query The Odds API sequentially for each supported sport.
3. Keep US-region American odds from allowed books.
4. Flatten provider events into games and offers.
5. Return results without persisting a market snapshot.

Bet lifecycle:

1. The caller supplies descriptive fields, stake, and optional model metadata.
2. The API checks only that the stake is positive and cash is sufficient.
3. The stake is deducted and the bet is appended to the portfolio JSON structure.
4. A later caller supplies win/loss/push plus net payout.
5. Settlement returns stake plus net payout to bankroll.
6. Aggregate statistics are calculated on demand from settled records.

### Current persistence properties

The database is a process-global Python dictionary loaded once from a JSON file. Writes use a temporary file and replacement, which reduces partial-file risk for a single writer. It is not safe for concurrent requests, multiple processes, multiple instances, or transactional financial updates.

Load and save exceptions are swallowed. An invalid file can silently produce a new default database, and a failed save can still be followed by a successful API response.

### Current external integration

The Odds API is directly embedded in route logic. The integration uses synchronous `requests`, a 12-second timeout, one sequential request per sport, American odds, US region, and exact sportsbook-title filtering. There is no provider interface, cache, retry policy, quota guard, stored snapshot, or sanitized error boundary.

### Current security and operational boundaries

There is no authentication, authorization, rate limiting, idempotency, structured logging, metrics, tracing, CI, or automated test suite. Portfolio IDs function as unprotected lookup keys. The `main` branch is currently unprotected.

## Proposed V2 architecture

The target is a modular paper-trading platform with explicit boundaries and auditable domain records.

```text
Odds/Data Providers
        |
        v
Provider Adapters --> Raw Market Snapshots
        |
        v
Event & Market Normalization
        |
        v
Pricing / Probability Engine
        |
        v
EV & Opportunity Engine
        |
        v
Portfolio & Risk Engine
        |
        v
Recommendation Engine
        |
        v
Explicit Human Approval
        |
        v
Bet Ledger --> Closing Price Capture --> Settlement
        |                                  |
        +----------------+-----------------+
                         v
             Performance & Calibration
```

### Proposed component responsibilities

#### API layer

Own request/response contracts, authentication, authorization, idempotency keys, and error mapping. It should orchestrate application services without containing pricing formulas or provider parsing.

#### Market-data adapters

Implement a provider-neutral interface for The Odds API and future providers. Preserve raw snapshots for reproducibility, sanitize failures, track quotas, and convert provider payloads into normalized records.

#### Normalization

Resolve stable internal IDs for events, participants, markets, selections, and exact line points. Ensure prices are compared only when event, market, period, selection, and line are equivalent.

#### Pricing and probability engine

Provide pure, versioned calculations for odds conversion, vig removal, consensus construction, proprietary-model inputs, uncertainty, edge, and EV. Every output must identify its source and calculation version.

#### Portfolio and risk engine

Recommend stakes from bankroll, EV, uncertainty, open exposure, daily risk, and correlation constraints. Full Kelly is prohibited; final policy remains to be validated through paper trading.

#### Recommendation and approval workflow

Create immutable recommendation snapshots and record explicit human approval or rejection. Approval creates an official paper bet; analysis alone must not mutate the ledger.

#### Bet ledger and settlement

Use durable transactional storage. Preserve entry context, bankroll movements, closing data, result, and settlement provenance. Repeated requests must be idempotent.

#### Analytics and calibration

Compute reproducible portfolio, model, calibration, and risk metrics from ledger and market snapshots. Model changes should follow versioned evaluation rather than mutating production behavior from recent outcomes.

### Proposed persistence

A relational database is the expected production direction because transactions, constraints, indexed historical analysis, and auditability are core requirements. PostgreSQL is a likely candidate for Render, but the database product and ORM are not yet an accepted decision.

The conceptual data model should include:

- providers and sportsbooks;
- normalized events, markets, selections, and lines;
- raw and normalized price snapshots;
- pricing/model versions and probability estimates;
- recommendations and approval records;
- portfolios, bankroll ledger entries, bets, and bet state transitions;
- closing-price observations and settlements; and
- analytics runs or reproducible derived views.

### Cross-cutting requirements

- UTC, timezone-aware timestamps.
- Decimal or explicitly rounded money representation; no non-finite numbers.
- Database constraints for probability ranges and financial invariants.
- Transactions and row-level concurrency controls for bankroll mutations.
- Idempotency for all mutating endpoints.
- Secrets only in runtime configuration and sanitized provider errors.
- Deterministic unit tests for financial logic and contract/integration tests for boundaries.
- Structured logs, metrics, provider quota visibility, backups, and recovery procedures.
- Versioned schemas, pricing logic, risk policies, and model outputs.

## Migration strategy

V2 should evolve incrementally. First characterize current behavior with tests, then extract pure domain logic, introduce normalized contracts, and move persistence behind an interface. Replace JSON storage only with an explicit migration and reconciliation plan. Do not combine every architectural change into a single rewrite.

Detailed sequencing appears in `ROADMAP.md`.

## Open architecture decisions

- PostgreSQL and ORM/query-layer choice.
- Deployment topology and worker model on Render.
- Authentication and portfolio-ownership model.
- Raw snapshot retention and compression policy.
- Background job/scheduler technology.
- Provider failover and consensus weighting policy.
- Event identity and cross-provider matching strategy.
- API versioning and compatibility policy.

