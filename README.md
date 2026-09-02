# Sports Betting Portfolio Backend

Experimental FastAPI backend for a quantitative sports-wagering portfolio manager. It stores raw sportsbook snapshots and provider-neutral market observations, calculates a transparent market-consensus pricing/EV baseline, produces conservative approval-ready NCAAF paper recommendations and stakes, enforces portfolio risk, replays pricing/risk logic offline, maintains an auditable bankroll ledger, settles results, and reports segmented performance. It does not place real-money wagers or claim proprietary NCAAF predictive edge.

NCAAF/College Football is the immediate league priority, followed by NFL and NBA. Python **3.12.x** is the supported development and CI runtime.

The POLARIS NCAAF Portfolio dashboard lives in `frontend/` and uses Node.js **22+**, pnpm **11.x**, React, TypeScript, and Vite. See [`docs/DASHBOARD.md`](docs/DASHBOARD.md) for local setup and Cloudflare Pages configuration.

## Local setup

```bash
python -m venv .venv
python -m pip install --upgrade pip
python -m pip install -r requirements-dev.txt
```

Offline NCAAF research transforms additionally require the pinned, non-web runtime:

```bash
python -m pip install -r requirements-research.txt
```

Activate `.venv`, copy `.env.example` to `.env`, and replace all placeholders. PostgreSQL is the production database. SQLite is supported only for deterministic tests and disposable local validation.

| Variable | Required | Purpose |
| --- | --- | --- |
| `DATABASE_URL` | Yes | Vendor-neutral PostgreSQL connection URL. Generic `postgres://` and `postgresql://` URLs use psycopg. |
| `APP_API_KEY` | Yes | Secret sent by private clients as `X-API-Key`. |
| `APP_OWNER_ID` | No | Stable owner/principal identifier; defaults to `default`. |
| `APP_OWNER_NAME` | No | Owner display label; defaults to `Default Owner`. |
| `ODDS_API_KEY` | For `/odds` | The Odds API credential. |
| `CFBD_API_KEY` | For CFBD research ingestion | CollegeFootballData bearer credential; never included in request hashes or manifests. |
| `NCAAF_RESEARCH_DATABASE_URL` | No | Optional separate PostgreSQL research-index URL; falls back to `DATABASE_URL`. |
| `NCAAF_ARTIFACT_DIR` | No | Ignored local/object-mounted immutable source-artifact root; defaults to `.ncaaf-data`. |
| `CFBD_TIMEOUT_SECONDS` | No | CFBD research request timeout; defaults to `30`. |
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
| `PORTFOLIO_MINIMUM_EV` / `PORTFOLIO_MINIMUM_EDGE` | No | Phase 6 straight qualification defaults `0.015` / `0.0075`. |
| `PORTFOLIO_KELLY_FRACTION` | No | Conservative Kelly multiplier; defaults to `0.25` and must remain below one. |
| `PORTFOLIO_MAXIMUM_CORE_BET_FRACTION` / `PORTFOLIO_MAXIMUM_OPPORTUNISTIC_BET_FRACTION` | No | Per-position equity caps; defaults `0.02` / `0.01`. |
| `PORTFOLIO_MAXIMUM_DAILY_FRACTION` | No | Combined slate exposure cap; defaults to `0.08`. |
| `PORTFOLIO_UNIT_FRACTION` | No | Display-unit share of decision-time equity; defaults to `0.04`. |
| `PORTFOLIO_REDUCED_RISK_DRAWDOWN` / `PORTFOLIO_PAUSED_DRAWDOWN` | No | State thresholds; defaults `0.10` / `0.20`. |
| `PARLAY_ENABLED` / `PARLAY_MAXIMUM_FRACTION` | No | Optional verified-quote sleeve; defaults enabled and `0.005` (0.5% equity). |
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

After installing `requirements-research.txt`, run all deterministic application and research gates (no live provider credential is required):

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
| `POST /portfolio/{portfolio_id}/recommendations/analyze` | Persist NCAAF straight recommendations, stake/risk detail, PASS reasons, and optional verified-quote parlay result. |
| `GET /portfolio/{portfolio_id}/recommendations` | Read proposed/approved/rejected strategy-book history. |
| `POST /recommendations/{recommendation_id}/approve` | Explicit human approval; atomically creates the official paper bet and ledger reservation. |
| `POST /recommendations/{recommendation_id}/reject` | Record a declined proposal without creating a bet. |
| `GET /portfolio/{portfolio_id}/risk` | Cash/equity/drawdown and current exposure by game, team, market, and straight/parlay kind. |
| `GET /dashboard/system` | Safe read-only policy/model/freshness status for the dashboard; never returns credentials. |
| `GET /dashboard/market-movement` | Bounded stored observation history for one UTC slate date and optional cutoff; never calls the provider. |
| `GET /dashboard/market-history` | Exact event/market/side history from stored scalar observations; never selects raw snapshot payloads or calls the provider. |
| `POST /dashboard/portfolio/{portfolio_id}/refresh-markets` | Explicit authenticated NCAAF refresh: fetches h2h/spreads/totals once, persists the snapshot, and evaluates all upcoming slates. Page loads never invoke it. |

`payout` remains a compatibility field meaning **net profit/loss**, not gross returned cash. Settlement adds `stake + payout` to cash. Open stake reduces available cash but remains part of equity as reserved exposure.

The flattened `/odds` game/offer shape remains compatible and now adds `snapshot_ids` plus `snapshot_id` for a single successful league fetch. Raw provider payloads never include locally supplied credentials, and persisted request parameters omit `apiKey`.

`/opportunities` remains the pricing-only baseline and returns no stake. The Phase 6 recommendation route independently consumes the retained registry fair value and exact executable observation, then applies stricter qualification, quarter-Kelly risk budgeting, CORE/OPPORTUNISTIC classification, Top-N/PASS behavior, and human approval. See [`PORTFOLIO_RISK_AND_RECOMMENDATIONS.md`](docs/PORTFOLIO_RISK_AND_RECOMMENDATIONS.md).

Opportunity reads preserve all raw snapshot history for audit while using a bounded scalar SQL projection of only the latest time-eligible market state. Raw snapshot JSON is never selected or deserialized by the pricing path. Historical cutoffs continue to require both observation time and ingestion time at or before `as_of`.

## Render deployment

Keep the existing web service and start command `uvicorn main:app`. Attach any PostgreSQL service reachable by `DATABASE_URL` (Render PostgreSQL is supported but not required), configure the environment variables above, run `alembic upgrade head` as a pre-deploy/release step, and deploy. A Render Disk is no longer required for primary portfolio state. Application database code contains no Render-specific host or credential logic.

## Structure and durable context

- `app/api/`: HTTP validation, authentication dependencies, and error mapping.
- `app/services/`: independently callable market ingestion, stored-observation pricing/replay, odds, and portfolio orchestration.
- `app/providers/`: provider-neutral interface and The Odds API adapter.
- `app/db/`: SQLAlchemy ledger and provider-neutral market-data schemas plus session/engine construction.
- `app/persistence/`: transactional portfolio/market-data repositories, read-only pricing queries, and legacy/test adapters.
- `app/research/ncaaf/`: offline normalized-fact, point-in-time feature, artifact, reconciliation, and reporting code.
- `migrations/`: Alembic environment and revisions.
- `app/migration/` and `app/cli/`: explicit legacy JSON import, market ingestion, and offline pricing replay.
- `tests/`: deterministic API, provider, pricing, replay, domain, ledger, migration-boundary, and service coverage.
- `frontend/`: responsive React/TypeScript paper-trading dashboard and Cloudflare Pages Function API bridge.

Read [`AGENTS.md`](AGENTS.md) and the durable product/architecture documents in [`docs/`](docs/) before making changes.

Phase 5B-3 adds an offline chronological baseline tournament over the Phase 5B-2 point-in-time feature artifacts. It creates naive, sequential power-rating, and fold-local Ridge out-of-fold predictions for margin and total, while keeping all three horizons separate. These are research candidates only: they are not loaded by FastAPI, do not change `/opportunities`, and do not establish betting edge. Market consensus remains the implemented pricing source. See [`NCAAF_BASELINE_MODEL_REPORT.md`](docs/NCAAF_BASELINE_MODEL_REPORT.md) and the durable research contracts linked there.

The completed aggregate corpus evidence is available as [`NCAAF_CORPUS_REPORT.md`](docs/NCAAF_CORPUS_REPORT.md) and machine-readable [`NCAAF_CORPUS_2014_2024.json`](docs/reports/NCAAF_CORPUS_2014_2024.json).

Research ingestion uses `CFBD_API_KEY`, `NCAAF_RESEARCH_DATABASE_URL` (or `DATABASE_URL`), and optional `NCAAF_ARTIFACT_DIR`/`CFBD_TIMEOUT_SECONDS`. Raw artifacts default to `.ncaaf-data/`, which is ignored by Git. Commands plan by default and require `--execute` for network use:

```bash
python -m app.cli.audit_cfbd
python -m app.cli.audit_cfbd --execute
python -m app.cli.ingest_ncaaf_history --start-season 2014 --end-season 2024
python -m app.cli.ingest_ncaaf_history --start-season 2014 --end-season 2024 --execute
python -m app.cli.validate_ncaaf_corpus --output .ncaaf-data/reports/corpus-2014-2024.json
python -m app.cli.inspect_source_manifests --limit 20
```

Development ingestion rejects 2025+ by default. `--allow-holdout-access` is deliberately explicit and must not be used for ordinary development.

Phase 5B-2 commands are offline by construction and reject `--network`. They default to 2014–2024 and fail closed at 2025:

```bash
python -m app.cli.normalize_ncaaf_research --plan
python -m app.cli.normalize_ncaaf_research
python -m app.cli.build_ncaaf_features --plan
python -m app.cli.build_ncaaf_features
python -m app.cli.validate_ncaaf_features --namespace normalized
python -m app.cli.validate_ncaaf_features --namespace features
python -m app.cli.inspect_ncaaf_features --feature home_off_ppa_blend
python -m app.cli.inspect_ncaaf_features --game-id 401628334
python -m app.cli.report_ncaaf_features
```

Phase 5B-3 uses the research-only dependency stack and is also offline/fail-closed:

```powershell
python -m app.cli.run_ncaaf_baselines --plan
python -m app.cli.run_ncaaf_baselines
python -m app.cli.validate_ncaaf_models
python -m app.cli.inspect_ncaaf_model --metric-prefix "24_hours_before_kickoff|margin"
```

Binary fold-model artifacts and OOF predictions remain under ignored `.ncaaf-data/`; only aggregate, non-holdout reports are committed.

Phase 5B-4 converts the frozen OOF point predictions into offline, push-aware probability distributions. These commands also reject network access and 2025+:

```powershell
python -m app.cli.run_ncaaf_probability_calibration --plan
python -m app.cli.run_ncaaf_probability_calibration
python -m app.cli.validate_ncaaf_probabilities
python -m app.cli.summarize_ncaaf_calibration
python -m app.cli.calculate_ncaaf_line_probability --market spread --mean 6.5 --scale 17 --line -7
python -m app.cli.inspect_ncaaf_probability 401628334 --target margin
```

The probability engine is research-only and is not connected to `/opportunities`. Phase 4 market consensus remains the production fair-probability source, and its conservative integer-line EV exclusion remains in force. See [`NCAAF_PROBABILITY_CALIBRATION_REPORT.md`](docs/NCAAF_PROBABILITY_CALIBRATION_REPORT.md).

Phase 5B-5 adds an equal-budget offline XGBoost/LightGBM/CatBoost tournament and chronological empirical-discrete margin refinement. The tree libraries remain in `requirements-research.txt`; Render's production `requirements.txt` is unchanged:

```powershell
python -m app.cli.run_ncaaf_strong_models --plan
python -m app.cli.run_ncaaf_strong_models
python -m app.cli.run_ncaaf_key_numbers
python -m app.cli.run_ncaaf_challenger_distribution
python -m app.cli.validate_ncaaf_strong_models
python -m app.cli.calculate_ncaaf_discrete_margin --mean 6.5 --scale 17 --line -7
```

These commands are offline, reject 2025+, and do not affect FastAPI. See [`NCAAF_STRONG_MODEL_REPORT.md`](docs/NCAAF_STRONG_MODEL_REPORT.md).

Phase 5B-6 adds a bounded CFBD source audit and reconstructed preseason/personnel feature experiment. Network access is opt-in only for the source command; normalization, validation, inspection, and modeling are offline. The standard commands reject 2025+:

```powershell
python -m app.cli.ingest_ncaaf_preseason
python -m app.cli.ingest_ncaaf_preseason --execute
python -m app.cli.ingest_ncaaf_preseason --info-only --execute --refresh
python -m app.cli.build_ncaaf_preseason
python -m app.cli.validate_ncaaf_preseason
python -m app.cli.inspect_ncaaf_preseason --season 2024 --program-id PROGRAM_UUID
python -m app.cli.run_ncaaf_preseason_models --plan
python -m app.cli.run_ncaaf_preseason_models
python -m app.cli.validate_ncaaf_preseason_models
python -m app.cli.run_ncaaf_preseason_supplement
python -m app.cli.validate_ncaaf_preseason_supplement
python -m app.cli.summarize_ncaaf_preseason
```

The source command requires `CFBD_API_KEY` only when `--execute` is present. It never includes credentials in parameters, hashes, filenames, manifests, or output. Repeated source requests use the Phase 5B-1 immutable cache unless `--refresh` explicitly checks for corrections. See [`NCAAF_PRESEASON_SOURCE_AUDIT.md`](docs/NCAAF_PRESEASON_SOURCE_AUDIT.md) and [`NCAAF_PRESEASON_MODEL_REPORT.md`](docs/NCAAF_PRESEASON_MODEL_REPORT.md).

Phase 5B-7A adds a bounded The Odds API historical coverage audit. Planning is the default and cannot spend credits; `--execute` requires `ODDS_API_KEY`, performs only the frozen 76-logical-request plan, and writes raw responses only beneath ignored `.ncaaf-data/`:

```powershell
python -m app.cli.audit_ncaaf_historical_odds
python -m app.cli.audit_ncaaf_historical_odds --execute
```

The completed audit used 67 unique requests and 2,010 credits. Its conditional-GO result approves FBS-vs-FBS morning h2h/spreads/totals and 60-minute h2h/spreads/totals, plus near-close spreads/totals, subject to the documented two-supported-book and completeness gates. It does not establish market edge. See [`NCAAF_HISTORICAL_ODDS_AUDIT.md`](docs/NCAAF_HISTORICAL_ODDS_AUDIT.md).

Phase 5B-7B materializes the approved canonical research dataset. Network access is explicit; `plan` is offline, `execute` enforces phase-specific call/credit ceilings and a 5,000-credit reserve, and every later build uses the immutable cache:

```powershell
python -m app.cli.historical_market_dataset plan --phase morning
python -m app.cli.historical_market_dataset execute --phase morning
python -m app.cli.historical_market_dataset validate-cache --phase morning
python -m app.cli.historical_market_dataset plan --phase later
python -m app.cli.historical_market_dataset execute --phase later
python -m app.cli.historical_market_dataset validate-cache --phase later
python -m app.cli.historical_market_dataset build
python -m app.cli.historical_market_dataset validate
python -m app.cli.historical_market_dataset summarize
python -m app.cli.historical_market_dataset inspect --event-id EVENT_UUID --horizon morning_first_kickoff_minus_3h
```

The complete 2020–2024 morning cohort is primary evidence. The deterministic 60-minute/near-close sample is robustness evidence only; it is not full-cohort coverage. Raw payloads and normalized Parquet remain ignored under `.ncaaf-data/`. See [`NCAAF_HISTORICAL_MARKET_DATASET_REPORT.md`](docs/NCAAF_HISTORICAL_MARKET_DATASET_REPORT.md).

Phase 5B-7C builds the offline market-consensus and common-cohort artifacts from that immutable dataset and the existing 5B-3 OOF predictions. It never loads `.env` or calls a provider:

```powershell
python -m app.cli.market_comparison build
python -m app.cli.market_comparison validate
python -m app.cli.market_comparison summarize
python -m app.cli.market_comparison inspect --event-id EVENT_UUID
```

The `consensus`, `join`, `residuals`, and `features` actions expose the same deterministic pipeline boundaries for automation. Outputs remain ignored beneath `.ncaaf-data/market-comparison/`; only the aggregate [`NCAAF_MARKET_COMPARISON_DATASET_REPORT.md`](docs/NCAAF_MARKET_COMPARISON_DATASET_REPORT.md) and machine-readable summary are committed.

Full Phase 5B-7 runs the frozen morning market-aware tournament entirely offline:

```powershell
python -m app.cli.run_ncaaf_market_aware_tournament run --root .ncaaf-data
python -m app.cli.run_ncaaf_market_aware_tournament validate --root .ncaaf-data
python -m app.cli.run_ncaaf_market_aware_tournament inspect --root .ncaaf-data
```

The tournament writes content-addressed point and push-aware probability artifacts beneath ignored `.ncaaf-data/market-aware-v1/`. It rejects 2025 and non-morning selection rows and makes no provider calls. See [`NCAAF_MARKET_AWARE_MODEL_REPORT.md`](docs/NCAAF_MARKET_AWARE_MODEL_REPORT.md).

Phase 5B-8 freezes the exact pre-2025 finalist slate and promotion/fallback gates without retraining or provider access:

```powershell
python -m app.cli.freeze_ncaaf_finalists build
python -m app.cli.freeze_ncaaf_finalists validate --require-local-artifacts
```

The committed manifest is reproducible without local binary artifacts; `--require-local-artifacts` additionally checks ignored Phase 5B-7 source hashes. See [`NCAAF_FINALIST_FREEZE.md`](docs/NCAAF_FINALIST_FREEZE.md).

Phase 5B-9 executed the single locked 2025 holdout. The one-time `unlock` command is intentionally non-repeatable; ordinary development paths still reject 2025. The remaining commands validate or deterministically reproduce the already-authorized holdout from ignored immutable inputs:

```powershell
python -m app.cli.ncaaf_holdout verify-unlock
python -m app.cli.ncaaf_holdout build-market --normalized-manifest MANIFEST_ID
python -m app.cli.ncaaf_holdout evaluate --feature-manifest MANIFEST_ID --market-manifest MANIFEST_ID
python -m app.cli.ncaaf_holdout validate-evaluation
```

The frozen total blend failed its predeclared MAE, Brier, and log-loss improvement gates, so market consensus remains the total fallback and the already-frozen margin/spread/moneyline benchmark. See [`NCAAF_2025_HOLDOUT_REPORT.md`](docs/NCAAF_2025_HOLDOUT_REPORT.md).

Generated research artifacts remain under ignored `.ncaaf-data/`; only aggregate, non-secret reports are committed. See [`NCAAF_FEATURE_DATASET_REPORT.md`](docs/NCAAF_FEATURE_DATASET_REPORT.md) and [`NCAAF_PBP_RECONCILIATION.md`](docs/NCAAF_PBP_RECONCILIATION.md).

Phase 5B-10 registers the retained NCAAF market-consensus benchmark and provides prospective shadow records without creating recommendations:

```powershell
python -m app.cli.ncaaf_model_registry validate
python -m app.cli.ncaaf_model_registry sync
python -m app.cli.ncaaf_model_registry list
python -m app.cli.ncaaf_shadow plan-slate --date YYYY-MM-DD
python -m app.cli.ncaaf_shadow summarize
```

See [`NCAAF_MODEL_REGISTRY_AND_SHADOW.md`](docs/NCAAF_MODEL_REGISTRY_AND_SHADOW.md). Registry inspection requires no provider call; live market ingestion remains a separate explicit operation.

Before using the Phase 6 recommendation endpoint in a new database, apply migrations. Application startup then validates and idempotently loads the retained registry manifest; the explicit sync command remains available for repair and inspection:

```powershell
python -m alembic upgrade head
python -m app.cli.ncaaf_model_registry sync
```

The Parlay of the Day requires a trusted provider-neutral executable combined quote. The current public route does not accept caller-supplied parlay payouts, so a parlay PASS is expected until such an adapter exists.
