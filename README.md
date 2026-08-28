# Sports Betting Portfolio Backend

Experimental FastAPI backend for a quantitative sports-wagering portfolio manager. It retrieves current sportsbook odds, records explicitly approved paper bets, maintains an auditable bankroll ledger, settles results, and reports basic performance statistics. It does not place real-money wagers or yet calculate fair probability, EV, recommendations, or stakes.

NCAAF/College Football is the immediate league priority, followed by NFL and NBA. Python **3.12.x** is the supported development and CI runtime.

## Local setup

```bash
python -m venv .venv
python -m pip install --upgrade pip
python -m pip install -r requirements-dev.txt
```

Activate `.venv`, copy `.env.example` to `.env`, and replace all placeholders. PostgreSQL is the production database. SQLite is supported only for deterministic tests and disposable local validation.

| Variable | Required | Purpose |
| --- | --- | --- |
| `DATABASE_URL` | Yes | Vendor-neutral PostgreSQL connection URL. Generic `postgres://` and `postgresql://` URLs use psycopg. |
| `APP_API_KEY` | Yes | Secret sent by private clients as `X-API-Key`. |
| `APP_OWNER_ID` | No | Stable owner/principal identifier; defaults to `default`. |
| `APP_OWNER_NAME` | No | Owner display label; defaults to `Default Owner`. |
| `ODDS_API_KEY` | For `/odds` | The Odds API credential. |
| `STARTING_BANKROLL` | No | Positive paper capital for a newly created portfolio; defaults to `200.00`. |
| `DATA_DIR` | No | Legacy JSON import location only; defaults to `data`. |

Never commit `.env`, API keys, or database credentials.

## Database and migrations

Create or select a PostgreSQL database, set `DATABASE_URL`, then run:

```bash
python -m alembic upgrade head
```

The application intentionally does not create production tables at startup. Validate a rollback with `python -m alembic downgrade -1`; create future revisions with `python -m alembic revision --autogenerate -m "description"` and inspect generated SQL before applying it.

Enable encrypted, provider-managed PostgreSQL backups and retention appropriate to the paper-trading environment. Before relying on the deployment, perform a restore drill into a separate database, run `alembic current`, and reconcile portfolio cash against the ledger sum. Do not test restores over the active database.

Legacy `data/portfolio_db.json` data is not imported automatically. Import it explicitly and safely rerun the command if needed:

```bash
python -m app.cli.import_json data/portfolio_db.json
```

The importer reports portfolio, bet, and reconciliation-adjustment counts. Preserve the source JSON until the report and relational balances have been reviewed.

## Run and validate

Apply migrations, then start the unchanged Render-compatible entry point:

```bash
python -m uvicorn main:app --reload
```

Run all deterministic gates (no live Odds API credential is required):

```bash
python -m ruff check .
python -m mypy app main.py tests migrations
python -m pytest
```

## API

`GET /health` remains public. All other endpoints require `X-API-Key`. Mutation clients should send a stable `Idempotency-Key`; omitting it preserves compatibility but permits a repeated request to create a second mutation.

| Endpoint | Purpose |
| --- | --- |
| `GET /health` | Service, provider configuration, database dialect, and UTC time. |
| `POST /odds` | Current/upcoming prices filtered by requested UTC calendar date. |
| `GET /portfolio/{portfolio_id}` | Cash, reserved stake, equity, realized P&L, and recent bets. |
| `POST /bets` | Record an approved paper bet and reserve stake transactionally. |
| `POST /bet-result` | Settle a bet transactionally as win, loss, or push. |
| `GET /portfolio/{portfolio_id}/stats` | Settled-bet and sport/market statistics plus ledger-derived balances. |

`payout` remains a compatibility field meaning **net profit/loss**, not gross returned cash. Settlement adds `stake + payout` to cash. Open stake reduces available cash but remains part of equity as reserved exposure.

## Render deployment

Keep the existing web service and start command `uvicorn main:app`. Attach any PostgreSQL service reachable by `DATABASE_URL` (Render PostgreSQL is supported but not required), configure the environment variables above, run `alembic upgrade head` as a pre-deploy/release step, and deploy. A Render Disk is no longer required for primary portfolio state. Application database code contains no Render-specific host or credential logic.

## Structure and durable context

- `app/api/`: HTTP validation, authentication dependencies, and error mapping.
- `app/services/`: odds and portfolio orchestration.
- `app/providers/`: provider-neutral interface and The Odds API adapter.
- `app/db/`: SQLAlchemy schema and session/engine construction.
- `app/persistence/`: database-neutral contract, transactional SQL repository, and legacy/test adapters.
- `migrations/`: Alembic environment and revisions.
- `app/migration/` and `app/cli/`: explicit legacy JSON import.
- `tests/`: deterministic API, provider, domain, ledger, migration-boundary, and service coverage.

Read [`AGENTS.md`](AGENTS.md) and the durable product/architecture documents in [`docs/`](docs/) before making changes.
