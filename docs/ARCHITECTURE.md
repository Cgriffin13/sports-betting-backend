# Architecture

This document describes implemented architecture first. The later target is explicitly proposed, not shipped behavior.

## Current implemented architecture

The runtime is a synchronous FastAPI service composed in `app/main.py`. Root `main.py` only re-exports `app`, preserving Render's `uvicorn main:app` contract.

```text
private client -- X-API-Key / request ID --> FastAPI routers
                                                |       |
                                                v       v
                                        OddsService  PortfolioService
                                             |              |
                                             v              v
                                    MarketDataProvider  PortfolioRepository
                                             |              |
                                             v              v
                                    TheOddsApiProvider  SQLAlchemy repository
                                             |              |
                                             v              v
                                      The Odds API      PostgreSQL
```

`GET /health` is public. `/odds`, portfolio reads, bet placement, settlement, and statistics require `X-API-Key`. Authentication resolves a replaceable `Principal`; every portfolio has an owner, and cross-owner access returns 403. This is a private single-user boundary, not a full identity platform.

### Module responsibilities

- `app/api/`: Pydantic-backed HTTP contracts, authentication dependency, service calls, and known-error mapping. Routes contain no raw SQL or provider HTTP.
- `app/services/`: provider and portfolio orchestration plus canonical idempotency request hashing.
- `app/domain/`: sports/market normalization, money rules, principals, and application errors.
- `app/providers/`: provider-neutral `MarketDataProvider` and The Odds API adapter. The adapter owns URL/auth construction, timeout, requests, sanitized errors, and parsing.
- `app/db/`: SQLAlchemy 2.x metadata, relational models, database URL normalization, engine, and session factory.
- `app/persistence/sqlalchemy_repository.py`: primary runtime persistence, transactions, row locking, ledger-derived balances, settlements, ownership, and idempotency records.
- `app/persistence/json_repository.py`: legacy compatibility only; not composed into the runtime.
- `app/persistence/memory_repository.py`: SQLAlchemy/SQLite test factory.
- `app/migration/` and `app/cli/`: explicit, rerunnable JSON import and reconciliation.
- `migrations/`: Alembic configuration and schema revisions. Production startup never calls `Base.metadata.create_all()`.
- `app/config.py`, `app/time.py`, `app/logging.py`, and `app/middleware.py`: environment configuration, UTC time, structured logs, and request IDs.

### Relational schema

| Table | Purpose and key invariants |
| --- | --- |
| `owners` | Stable UUID, external principal ID, display name, status, creation time. External ID is unique. |
| `portfolios` | UUID, compatibility external ID, owner, starting capital, currency, status, creation time. Starting capital is not fixed at $200. |
| `recommendations` | Future-compatible decision snapshot for later engines. The current application does not create recommendations. |
| `bets` | Reconstructable entry snapshot: event/team/time fields, league/sport, market/period/selection/point, book/price/stake, optional probability and version metadata, approval/placement, closing, result, and realized P&L. |
| `bet_approvals` | One approval audit record per official bet, associated with the authenticated owner and optional future recommendation. |
| `bet_state_transitions` | Append-only placement and settlement state transitions with source and time. |
| `settlements` | One auditable settlement per bet with outcome, net payout, source, closing metadata, and timestamp. Unique `bet_id` prevents a second settlement. |
| `ledger_entries` | Immutable bankroll events with signed `NUMERIC(18,2)` amount, type, bet link, unique portfolio reference, optional idempotency key/metadata, and timestamp. |
| `idempotency_records` | Owner + endpoint + key uniqueness, canonical request hash, and successful response snapshot. |

Foreign keys use restrictive deletion because financial history must not cascade away. Check constraints bound statuses, results, entry types, and positive stakes. UUIDs are internal identities; existing external IDs preserve API compatibility.

### Money and ledger semantics

Python `Decimal` and SQL `NUMERIC(18,2)` are authoritative. Inputs round to cents with `ROUND_HALF_UP`; floats exist only at the JSON compatibility boundary.

Cash is the sum of signed ledger entries. Reserved stake/open exposure is the sum of stakes on open bets. Equity is `cash + reserved stake`. Realized P&L is the sum of settled bet P&L. An open stake reduces cash but is not a realized loss.

For a `$200.00` portfolio placing a `$10.00` bet:

```text
initial_funding  +200.00  => cash 200.00, reserved 0.00, equity 200.00
bet_stake         -10.00  => cash 190.00, reserved 10.00, equity 200.00
```

Settlement uses the legacy API's net-profit `payout` semantics:

- win with `payout=+9.09`: settlement ledger `+19.09`; cash/equity `$209.09`, realized P&L `+$9.09`;
- loss with `payout=-10.00`: settlement ledger `+0.00`; cash/equity `$190.00`, realized P&L `-$10.00`;
- push with `payout=0.00`: settlement ledger `+10.00`; cash/equity `$200.00`, realized P&L `$0.00`.

The ledger is append-only under normal ORM operations; corrections require explicit adjustment entries rather than editing history.

### Transaction and concurrency boundaries

Portfolio creation, initial funding, bet placement, settlement, their ledger entries, and an optional idempotency record commit atomically in repository-managed `Session.begin()` blocks. Any exception rolls the whole mutation back.

PostgreSQL locks the owner row before portfolio mutation, serializing changes across all that owner's portfolios, and additionally locks the target portfolio/bet where relevant. This conservative scope prevents concurrent overspending and double settlement. SQLite test transactions exercise atomicity and constraints but ignore `SELECT ... FOR UPDATE`; they do not prove PostgreSQL lock scheduling. Production concurrency validation should therefore include PostgreSQL integration tests before horizontal scaling.

An `Idempotency-Key` is scoped to authenticated owner and endpoint. Same key plus the same canonical payload returns the stored successful response without a second mutation. Same key plus different payload returns 409. Missing keys are allowed for backward compatibility and repeated requests are treated as distinct. Failed transactions do not retain an idempotency record.

### Runtime and deployment

`DATABASE_URL` and `APP_API_KEY` are required at startup; owner metadata, starting bankroll, Odds API key, and legacy data directory are environment-controlled. Generic `postgres://` or `postgresql://` URLs are normalized to psycopg without vendor-specific logic. PostgreSQL is the documented production database; SQLite is test-only.

Render remains the backend host. Configure a PostgreSQL `DATABASE_URL`, private API key, and other environment values; run `alembic upgrade head` before the web process; keep `uvicorn main:app`. A persistent disk is no longer the primary portfolio store.

Odds behavior is unchanged: current/upcoming The Odds API results are filtered by timezone-aware `commence_time` to the requested UTC calendar date. NCAAF maps to `americanfootball_ncaaf` and remains distinct from NCAAB.

## Proposed architecture after Phase 2

```text
Odds providers -> normalization -> no-vig/consensus pricing ----+
Sports data -> league feature pipeline -> predictive models ----+-> final fair probability
Research/news -> traceable structured signals ------------------+          |
                                                                          v
                                                           EV / qualification
                                                                          |
Portfolio ledger -> risk budget / correlation controls -> stake/rank -> Top N
                                                                          |
                                                               human approval
                                                                          |
                                  bet ledger -> close -> settlement -> analytics/calibration
```

Next phases add normalized market snapshots, pricing/EV, recommendation/risk policy, and an early NCAAF model track. Market consensus is the baseline and benchmark, not necessarily the final proprietary probability. The existing nullable bet metadata provides a durable destination without claiming those engines exist.

Not implemented: implied-probability calculation, vig removal, consensus pricing, proprietary models, Kelly sizing, recommendation ranking, structured sports/news ingestion, CLV calculation, autonomous settlement, autonomous sportsbook execution, or frontend work.
