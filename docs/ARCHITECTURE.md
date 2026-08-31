# Architecture

This document describes implemented architecture first. The later target is explicitly proposed, not shipped behavior.

## Current implemented architecture

The runtime is a synchronous FastAPI service composed in `app/main.py`. Root `main.py` only re-exports `app`, preserving Render's `uvicorn main:app` contract.

```text
private client -- X-API-Key / request ID --> FastAPI routers
                          |                         |                 |
                          v                         v                 v
                     OddsService              PricingService   PortfolioService
                          |                         |                 |
                          v                         v                 v
               MarketIngestionService     Consensus/EV domain   Ledger Repo
                  |                |                |
                  v                v                v
          MarketDataProvider  MarketDataRepo  Pricing read repo
                  |                |                |
                  v                +--------+-------+
          TheOddsApiProvider                v
                  |                     PostgreSQL
                  v
            The Odds API
```

`GET /health` is public. `/odds`, `/opportunities`, portfolio reads, bet placement, settlement, and statistics require `X-API-Key`. Authentication resolves a replaceable `Principal`; every portfolio has an owner, and cross-owner access returns 403. This is a private single-user boundary, not a full identity platform.

### Module responsibilities

- `app/api/`: Pydantic-backed HTTP contracts, authentication dependency, service calls, and known-error mapping. Routes contain no raw SQL or provider HTTP.
- `app/services/`: provider-neutral market ingestion, stored-observation pricing/replay, flattened odds behavior, portfolio orchestration, and canonical idempotency hashing. Ingestion and pricing are callable without FastAPI.
- `app/domain/`: league, canonical book, market/period/side/point identity, pure Decimal pricing/vig/consensus/EV rules, money rules, principals, and errors.
- `app/providers/`: provider-neutral fetch records and The Odds API adapter. The adapter owns URL/auth construction, bounded retry/backoff, cache, quota metadata, timeout, sanitized errors, raw response capture, and provider parsing.
- `app/db/`: SQLAlchemy 2.x ledger and market-data models, database URL normalization, engine, and session factory.
- `app/persistence/market_repository.py`: atomic raw snapshot, event matching, book mapping, and observation persistence.
- `app/persistence/pricing_repository.py`: read-only, time-bounded projection of normalized observations into provider-neutral pricing inputs.
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
| `market_snapshots` | Exact raw provider response, credential-free request parameters, provider/request timestamps, quota/source metadata, warnings/errors, and ingestion status. PostgreSQL uses JSONB. |
| `canonical_events` | Stable internal event UUID, league/participants/start/status, and match confidence/review/provenance. Display strings are attributes, not identity. |
| `provider_event_mappings` | Provider sport/event identifiers mapped to canonical event candidates with confidence and review state. Conflicts may retain multiple candidates. |
| `sportsbooks` | Canonical book key, display name, active flag, and timestamps. |
| `provider_sportsbooks` | Provider-specific book identifier/display mapped separately to a canonical sportsbook. |
| `market_observations` | Snapshot-linked exact price: event, book, canonical market, period, side, exact point identity, American odds, source path, observation/ingestion times, freshness, and match review state. |

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

### Market ingestion and identity

A successful fetch produces a provider-neutral `ProviderFetchResult` containing the exact raw JSON payload, sanitized request parameters, response/quota metadata, warnings, provider retrieval time, and parsed games/offers. `MarketIngestionService` persists that fetch through `MarketDataRepository` in one transaction; raw snapshot, new event candidates, provider mappings, book mappings, and observations all commit or all roll back. Sanitized provider failures are recorded as failed snapshots when request context is available.

The Odds API's provider event ID is the deterministic first matching key within its provider sport. A repeat with identical league, home team, away team, and UTC start reuses the canonical event. A reused provider ID with conflicting identity creates a distinct candidate and marks all candidates `conflict`; missing IDs create `needs_review` events and are never silently string-matched. Observations copy the match-review state so later automation can reject ambiguity.

Initial normalized identity is:

```text
event UUID + canonical sportsbook + market type + period + selection side + exact point
```

Canonical market types are `moneyline`, `spread`, and `total`; initial period is `full_game`; sides are `home`, `away`, `draw`, `over`, or `under`. Moneyline point identity is `none`; spreads/totals require a `NUMERIC(10,3)` point and normalized point key. Therefore Over 52.5 differs from Over 53.5, and a future first-half spread will differ from a full-game spread without changing the core observation key design.

Every observation retains its snapshot FK and raw payload indexes, making source reconstruction direct. Ordering equivalent identities by `observed_at` supports first-observed and most-recent-pre-start selection. The same records contain enough entry and pre-start timing/line identity for a later closing-price/CLV policy, but Phase 3 does not label a close or calculate CLV.

### Baseline pricing, qualification, and replay

Phase 4 adds no tables. Pricing is a transient deterministic projection from immutable Phase 3 observations; an official future recommendation remains the persistence boundary. Every output includes source observation/snapshot IDs, best executable observation, calculation cutoff, and vig, consensus, pricing, and qualification versions.

```text
time-bounded stored observations
  -> latest snapshot state per event/book/market/period
  -> supported/active/fresh/matched gates
  -> exact coherent two-outcome book pairs
  -> proportional no-vig probability per book
  -> unweighted median across books
  -> dispersion and material-outlier diagnostics
  -> separate best executable offer
  -> probability edge and binary EV
  -> versioned qualification
  -> deterministic EV/data-quality ranking
  -> Top N per league (ceiling, never quota)
```

Initial policy versions are `proportional-v1`, `unweighted-median-v1`, `market-baseline-v1`, and `baseline-qualification-v1`. Proportional no-vig probabilities use Decimal arithmetic, round to 12 decimal places with half-even rounding, and force the final outcome to the residual so paired probabilities sum exactly to one. Consensus is the unweighted median of complete paired book probabilities; no unsupported empirical “sharp book” weights exist. Dispersion is the across-book probability range. Deviations above the configurable outlier threshold are surfaced, while dispersion above the configurable maximum rejects the market.

Exact pairing uses canonical event, market, period, and line. A spread pair requires opposite signed points; a total pair requires the identical point. The consensus source may only include complete pairs. The best executable offer is selected separately from the same eligible exact market, so it cannot become its own fair-probability source.

The initial binary EV qualification supports two-outcome moneylines and half-point spreads/totals. Integer spread/total lines are rejected with `push_probability_not_modeled`; Phase 4 does not invent a push probability. Default operational thresholds are two books, 1% EV per unit, 0.5 percentage-point edge, 3 percentage-point outlier deviation, and 8 percentage-point maximum dispersion. All are environment-configurable starting values, not evidence-backed permanent standards.

`POST /opportunities` is authenticated and reads stored observations only. It labels outputs `market_consensus_baseline`, keeps proprietary probability null, returns no stake, and accepts an optional historical cutoff/date. The replay CLI uses the same service and policy code.

Historical replay enforces `observed_at <= as_of` and `ingested_at <= as_of`. It then selects the latest snapshot state for each event/book/market/period, preventing a later ingestion or line move from leaking into an earlier replay and preventing superseded exact lines from remaining falsely executable. Event start, freshness, ambiguity, supported-book, pair, and qualification gates are evaluated at the cutoff. The cutoff is also the deterministic calculation timestamp. Pricing replay produces decision-time prices only; it is not an outcome backtest or bankroll simulation.

#### Bounded pricing read path

Raw Phase 3 snapshots remain the immutable audit source, but opportunity analysis does not retrieve their JSON documents. The SQLAlchemy pricing repository uses scalar projections and two deterministic SQL window rankings: first one representative row per snapshot state, then the latest eligible snapshot per event, sportsbook, market type, and period. The final projection retrieves only the normalized observation, event, sportsbook, and `requested_at` fields consumed by Phase 4.

The query applies league, market, UTC event-date, `observed_at <= as_of`, and `ingested_at <= as_of` bounds before ranking. Event-start eligibility remains in the shared pricing domain so rejection semantics stay consistent. Result cardinality follows the latest market state rather than the number or size of retained historical snapshots. A prior implementation joined complete `MarketSnapshot` ORM entities—including `raw_payload` and other JSON metadata—to every observation row and reduced history in Python; repeated snapshots amplified deserialized JSON in memory and could exhaust a constrained Render process. The raw records were not themselves the defect and are not deleted.

Each pricing request emits safe structured counts for fetched observations, represented snapshots/events/books, returned opportunities, and query/calculation elapsed milliseconds. It never logs raw payloads, credentials, or credential-bearing URLs.

### Freshness, retry, cache, and quota policy

Freshness policy `market-freshness-v1` stores provider update time where available, effective observation time, ingestion time, age in seconds, the configured threshold, and materialized `is_stale`. The initial 120-second threshold is configurable through `MARKET_FRESHNESS_SECONDS`; it is an operational baseline, not a permanent empirical claim.

The provider retries only timeouts, connection failures, HTTP 408/425/429, and 5xx, with configurable bounded attempts and exponential backoff. Authentication and other client errors are not retried. A configurable short process-local cache reduces duplicate calls; cache hits can still become separately timestamped persisted snapshots. Returned usage headers are stored as structured source metadata, and low remaining quota becomes a structured warning. API keys and credential-bearing URLs are never persisted or logged.

## Proposed architecture after Phase 4

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

Next phases add an early NCAAF proprietary-model track, recommendation/risk policy, and closing-label policy. Market consensus is the implemented baseline and benchmark, not a proprietary probability. The existing nullable bet metadata provides a durable destination without claiming those future engines exist.

### Phase 5B-4 probability layer (implemented offline)

```text
Phase 5B-3 OOF point predictions and residuals
  -> strictly prior-season residual pool per target/horizon/point model
  -> versioned Normal / Student-t / empirical / grouped-scale candidates
  -> predictive CDF, PDF, quantiles, scale, and fit provenance
  -> integer-score lattice discretization
  -> moneyline win/loss and spread/total win/push/loss probabilities
  -> proper scores, PIT, intervals, buckets, segments, and paired uncertainty
  -> ignored Parquet/JSON research artifacts
```

`app.research.ncaaf.probability` is a provider- and market-source-neutral distribution/settlement library. `app.research.ncaaf.calibration` owns the chronological tournament, artifact manifests, proper-score summaries, and validation. CLI entry points run, validate, inspect, and calculate synthetic-line probabilities without provider access.

This layer is deliberately absent from the FastAPI dependency graph. It adds no endpoint, migration, Render dependency, or production inference path. `/opportunities` continues to use Phase 4 market consensus, with proprietary probability null. Large probability artifacts remain content-hashed under ignored `.ncaaf-data/models/probability-v1/`.

### Phase 5B-5 strong-model layer (implemented offline)

`app.research.ncaaf.strong_models` consumes the frozen Phase 5B-2 matrices and Phase 5B-3 fold contract. It runs an equal-budget, deterministic XGBoost/LightGBM/CatBoost tournament with bounded configurations, fold-local missing-value handling, OOF predictions, ablations, sensitivity checks, permutation diagnostics, and content-hashed manifests. `app.research.ncaaf.key_numbers` fits chronological empirical-discrete margin mass from strictly earlier OOF residuals. `app.research.ncaaf.challenger_distribution` performs only the frozen limited distribution pairing for a point challenger that clears its gates.

All dependencies and artifacts remain research-only. The web service does not import these modules, production requirements are unchanged, and no endpoint or migration was added. A future Phase 6 recommendation boundary must retain two immutable views: the strategy/model book of every qualified opportunity and the actual/executed paper book after human approval. That separation is required for selection-bias and execution attribution.

### Phase 5B-6 preseason/personnel layer (implemented offline)

```text
bounded CFBD preseason/personnel products
  -> Phase 5B-1 credential-free immutable source manifests/raw cache
  -> exact team/player identity mapping and reconstructed availability policies
  -> content-addressed program-season Parquet facts
  -> additive join to each Phase 5B-2 horizon matrix
  -> fold-local Ridge / power-prior / bounded CatBoost experiments
  -> deterministic OOF predictions, ablations, gates, and aggregate reports
```

`app.research.ncaaf.preseason` owns normalization, point-in-time eligibility, feature-family provenance, content hashes, and the additive model-ready matrices. `app.research.ncaaf.preseason_modeling` owns the bounded chronological experiment. The associated CLIs plan or explicitly execute the credentialed source audit, build and validate local artifacts, inspect one program-season row, run the tournament, and validate OOF outputs.

The source facts are reconstructed, not historical publication snapshots. Returning production, recruiting, talent, roster, and head-coach state use a versioned season-start boundary and retain the real 2026 ingestion time. Portal records additionally require a provider transfer date before that boundary. Missing source coverage remains null with explicit flags; it is not silently converted to zero. Coordinator history is deferred because the selected structured provider has no verified historical product.

No Phase 5B-6 module is imported by FastAPI. PyArrow, psutil, scikit-learn, and CatBoost remain research-only dependencies; all large/binary artifacts stay ignored. No endpoint, migration, production requirement, pricing probability, recommendation, or Render process changed.

### Phase 5B-1 NCAAF source architecture (implemented)

```text
CFBD / approved sports sources    historical/future odds    structured reports/weather
              |                           |                            |
        immutable raw extracts     Phase 3 snapshots          immutable source records
              +---------------------------+----------------------------+
                                          |
                             bitemporal canonical facts
                      effective_at / observed_at / ingested_at
                                          |
                         as-of feature and target builder
                           |                         |
          partitioned Parquet matrices/OOF       PostgreSQL manifests,
          predictions and immutable artifacts    registry and provenance
                           |                         |
                           +-> chronological model tournament
                                      |
                     calibration/distribution evaluation
                                      |
                       candidate -> shadow -> production
                                      |
                future distinct market/model/final probabilities
```

PostgreSQL is now the system of record for source manifests, artifact indexes, canonical program and venue identities, effective-dated program aliases/conference membership, versioned game facts, explicit eligibility/exclusion reasons, and links to existing `CanonicalEvent`/`ProviderEventMapping` rows. The new tables are additive; the Phase 2 ledger and Phase 3/4 market path are unchanged.

CFBD responses are stored outside Git as content-addressed `raw-json-gzip-v1` artifacts partitioned by provider, league, season, week, and endpoint. The compressed payload is the provider's exact response bytes, not re-serialized JSON. This is the approved “equivalently lean immutable format” for raw source responses: it keeps the Render web dependency set small, compresses the measured 1.22 GB response corpus to about 92.6 MB, and remains lossless. A later feature build may produce Parquet matrices without rewriting the raw-source contract.

The retrieval transaction is one request/manifest partition at a time. The artifact is written atomically before relational normalization; the database manifest, artifact index, identities, and facts commit together. If relational normalization rolls back, a content-addressed orphan file may remain safely reusable by a resumed run; no partial relational state is committed. Cache hits re-run idempotent normalization from the immutable artifact, enabling recovery when a prior run retrieved data but did not complete downstream normalization.

`canonical request + content hash` uniquely identifies one source version. A changed response creates a new immutable manifest linked by `supersedes_manifest_id`; an identical response reuses the prior manifest. Authentication headers are never part of request parameters, hashes, filenames, manifests, warnings, or logs.

The 2014–2024 development command uses year-level calendars, teams, games and drives plus weekly regular/postseason plays and team game statistics. Development commands reject 2025+ outcomes unless the operator supplies the explicit holdout-access flag. Initial training remains offline. Spark, Databricks, distributed ML infrastructure, and a separate inference service remain deferred.

### Phase 5B-2 feature architecture (implemented offline)

```text
Phase 5B-1 immutable raw JSON.gz + PostgreSQL identity/manifests
                              |
                 bounded column-projected transforms
                              |
       immutable normalized Parquet facts by dataset/season
                              |
        as-of rolling/prior/opponent-adjusted feature builder
                              |
        three separately versioned horizon Parquet matrices
                              |
       manifests + hashes + QA/reconciliation/fold metadata
```

`app/research/ncaaf/` owns these offline boundaries. It reads compact relational identity/game metadata and project-selects Parquet columns; it does not load 1.7 million plays into ORM objects or change synchronous FastAPI behavior. Bulky normalized facts and feature matrices remain content-addressed under ignored `.ncaaf-data/`. PostgreSQL continues to store the authoritative Phase 5B-1 source indexes and identities; Phase 5B-2 required no relational schema change.

Normalized artifacts preserve source-manifest IDs/hashes, transformation/schema versions, row counts, input hashes, exact file hashes, and immutable paths. The feature manifest records the normalized input, feature-set/availability/fold policy versions, season range, eligibility counts, schema hash, and content hash. A mutable `current.json` pointer is only a convenience reference and never mutates prior content-addressed artifacts.

### Broader Phase 5 production architecture (planned, not implemented)

### Phase 5B-3 baseline-model architecture (implemented offline)

`app/research/ncaaf/modeling.py` consumes the immutable horizon-specific feature Parquet files and freezes a model-input manifest before training. Reusable expanding folds evaluate 2019–2023 as development seasons and 2024 as validation; 2025 is rejected. Every Ridge fold owns its median imputation, missing indicators, constant-column removal, scaling, and fit. Sequential power ratings predict before updating. Naive, power, and Ridge OOF rows plus JSON-safe fold parameters are written beneath ignored `.ncaaf-data/models/` with dataset, feature, preprocessing, fold, package, and artifact hashes.

The three horizons are never pooled. The first full run found small legitimate feature differences caused by their point-in-time availability boundaries, so each horizon is fitted independently. No database migration or production dependency was added. FastAPI does not import the research modeling stack, and market consensus remains the production pricing source.

Phase 5B-3 does not implement probability calibration, production inference, model/market blending, recommendations, or stake sizing. Those require later promotion gates and the still-sealed holdout.

Every time-sensitive model input must carry `effective_at`, `observed_at`, `ingested_at`, source, provenance, schema version, and reconstructed-versus-contemporaneous status. The as-of builder requires all applicable time boundaries to be at or before the prediction cutoff. Provider corrections supersede rather than overwrite historical versions. Large training and calibration jobs run offline; a future FastAPI inference path may load one approved small artifact only after schema/hash verification and a golden prediction check. Batch refresh or computationally heavy models may later justify a worker.

The proposed research/news pipeline stores cited structured facts through source discovery, entity matching, extraction, reliability tier, corroboration, and versioning. An LLM may assist those steps and explanation rendering; it cannot directly adjust probability. See `NCAAF_MODEL_RESEARCH.md`, `NCAAF_DATA_SOURCES.md`, `NCAAF_SOURCE_AUDIT.md`, `NCAAF_FEATURE_CATALOG.md`, `NCAAF_BACKTEST_DESIGN.md`, and `NCAAF_EXPERIMENT_PLAN.md`.

Not implemented in production: proprietary-model inference, model blending, push-aware EV integration, Kelly sizing, bankroll-aware ranking/stakes, structured sports/news ingestion, portfolio simulation, CLV calculation, autonomous settlement, autonomous sportsbook execution, or frontend work. Offline proprietary point models and push-aware probability research now exist but do not feed FastAPI.
