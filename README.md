# Sports Betting Portfolio Backend

Experimental FastAPI backend for a quantitative sports-wagering portfolio manager. It stores raw sportsbook snapshots and provider-neutral market observations, calculates a transparent market-consensus pricing/EV baseline, replays historical pricing offline, records explicitly approved paper bets, maintains an auditable bankroll ledger, settles results, and reports basic performance statistics. It does not place real-money wagers, produce proprietary model probabilities, or size stakes.

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
| `PROVIDER_TIMEOUT_SECONDS` | No | Per-request timeout; defaults to `12.0`. |
| `PROVIDER_MAX_RETRIES` | No | Bounded retries after the first attempt for timeouts, connection failures, HTTP 408/425/429, and 5xx; defaults to `2`. |
| `PROVIDER_BACKOFF_SECONDS` | No | Initial exponential-backoff delay; defaults to `0.25`. |
| `PROVIDER_CACHE_TTL_SECONDS` | No | Process-local successful-fetch cache TTL; defaults to `15.0`. |
| `PROVIDER_LOW_QUOTA_THRESHOLD` | No | Remaining-request threshold for a structured quota warning; defaults to `10`. |
| `MARKET_FRESHNESS_SECONDS` | No | Versioned v1 stale-price threshold; defaults to `120`. |
| `PRICING_MINIMUM_BOOKS` | No | Complete paired books required for consensus; defaults to `2`. |
| `PRICING_MINIMUM_EV` | No | Minimum EV per unit for baseline opportunity qualification; defaults to `0.01`. |
| `PRICING_MINIMUM_PROBABILITY_EDGE` | No | Minimum probability-point edge; defaults to `0.005`. |
| `PRICING_OUTLIER_THRESHOLD` | No | Absolute no-vig probability deviation from consensus that raises an outlier warning; defaults to `0.03`. |
| `PRICING_MAXIMUM_DISPERSION` | No | Maximum eligible across-book no-vig probability range; defaults to `0.08`. |
| `PRICING_SUPPORTED_BOOKS` | No | Comma-separated canonical book keys; defaults to `draftkings,fanduel,betmgm`. |
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

Market ingestion is also callable without FastAPI, making it suitable for a manual run or a future Render cron/worker trigger:

```bash
python -m app.cli.ingest_market_data --sport NCAAF --markets h2h spreads totals
```

This command persists the exact raw response and normalized observations. It does not calculate CLV or place a recommendation in the portfolio ledger.

Replay pricing entirely from stored observations without a provider call:

```bash
python -m app.cli.replay_market_pricing \
  --sport NCAAF \
  --date 2026-08-29 \
  --as-of 2026-08-29T20:00:00+00:00
```

Replay requires a timezone-aware cutoff. It excludes observations not yet ingested at that cutoff, future provider observations, stale prices, ambiguous events, unsupported books, incomplete pairs, and superseded book/market states. Pricing replay is not an outcome backtest or portfolio simulation.

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
| `POST /odds` | Current/upcoming prices filtered by requested UTC calendar date; successful runtime fetches also persist a snapshot. |
| `POST /opportunities` | Authenticated, paper/research-only market-consensus pricing from stored observations, optionally at a historical cutoff. |
| `GET /portfolio/{portfolio_id}` | Cash, reserved stake, equity, realized P&L, and recent bets. |
| `POST /bets` | Record an approved paper bet and reserve stake transactionally. |
| `POST /bet-result` | Settle a bet transactionally as win, loss, or push. |
| `GET /portfolio/{portfolio_id}/stats` | Settled-bet and sport/market statistics plus ledger-derived balances. |

`payout` remains a compatibility field meaning **net profit/loss**, not gross returned cash. Settlement adds `stake + payout` to cash. Open stake reduces available cash but remains part of equity as reserved exposure.

The flattened `/odds` game/offer shape remains compatible and now adds `snapshot_ids` plus `snapshot_id` for a single successful league fetch. Raw provider payloads never include locally supplied credentials, and persisted request parameters omit `apiKey`.

`/opportunities` returns up to `top_n` qualified results per requested league; 10 is the default and zero is valid. It exposes each book's paired no-vig calculation, consensus dispersion/outliers, best executable price, implied probability, market-consensus fair probability, edge, EV, source observation/snapshot IDs, and policy versions. `proprietary_model_probability` is explicitly null and `final_fair_probability_source` is `market_consensus`. No stake is returned.

Opportunity reads preserve all raw snapshot history for audit while using a bounded scalar SQL projection of only the latest time-eligible market state. Raw snapshot JSON is never selected or deserialized by the pricing path. Historical cutoffs continue to require both observation time and ingestion time at or before `as_of`.

## Render deployment

Keep the existing web service and start command `uvicorn main:app`. Attach any PostgreSQL service reachable by `DATABASE_URL` (Render PostgreSQL is supported but not required), configure the environment variables above, run `alembic upgrade head` as a pre-deploy/release step, and deploy. A Render Disk is no longer required for primary portfolio state. Application database code contains no Render-specific host or credential logic.

## Structure and durable context

- `app/api/`: HTTP validation, authentication dependencies, and error mapping.
- `app/services/`: independently callable market ingestion, stored-observation pricing/replay, odds, and portfolio orchestration.
- `app/providers/`: provider-neutral interface and The Odds API adapter.
- `app/db/`: SQLAlchemy ledger and provider-neutral market-data schemas plus session/engine construction.
- `app/persistence/`: transactional portfolio/market-data repositories, read-only pricing queries, and legacy/test adapters.
- `migrations/`: Alembic environment and revisions.
- `app/migration/` and `app/cli/`: explicit legacy JSON import, market ingestion, and offline pricing replay.
- `tests/`: deterministic API, provider, pricing, replay, domain, ledger, migration-boundary, and service coverage.

Read [`AGENTS.md`](AGENTS.md) and the durable product/architecture documents in [`docs/`](docs/) before making changes.

Phase 5A NCAAF research is documented separately in [`NCAAF_MODEL_RESEARCH.md`](docs/NCAAF_MODEL_RESEARCH.md), [`NCAAF_DATA_SOURCES.md`](docs/NCAAF_DATA_SOURCES.md), [`NCAAF_FEATURE_CATALOG.md`](docs/NCAAF_FEATURE_CATALOG.md), [`NCAAF_BACKTEST_DESIGN.md`](docs/NCAAF_BACKTEST_DESIGN.md), and [`NCAAF_EXPERIMENT_PLAN.md`](docs/NCAAF_EXPERIMENT_PLAN.md). These are specifications only; market consensus remains the implemented pricing source.
