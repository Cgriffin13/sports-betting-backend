# Architecture

This document describes implemented architecture first. The later target is explicitly proposed, not shipped behavior.

## Current implemented architecture

The runtime is a synchronous FastAPI service composed in `app/main.py`. Root `main.py` only re-exports `app`, preserving Render's `uvicorn main:app` contract.

```text
private client -- X-API-Key / request ID --> FastAPI routers
                          |                         |                        |
                          v                         v                        v
                     OddsService              PricingService       RecommendationService
                          |                         |                  /            \
                          v                         v                 v              v
               MarketIngestionService     Consensus/EV domain   FairValue       Risk/Parlay
                  |                |                |
                  v                v                v
     MarketDataProvider  MarketDataRepo  Pricing read repo
                  |                |                |
                  v                +--------+-------+
          TheOddsApiProvider                v
                  |             Recommendation/Ledger repos
                  v
            The Odds API                  |
                                          v
                                      PostgreSQL
```

`GET /health` is public. `/odds`, `/opportunities`, portfolio/recommendation/risk reads, recommendation analysis/disposition, bet placement, settlement, and statistics require `X-API-Key`. Authentication resolves a replaceable `Principal`; every portfolio has an owner, and cross-owner access returns 403. This is a private single-user boundary, not a full identity platform.

### Module responsibilities

- `app/api/`: Pydantic-backed HTTP contracts, authentication dependency, service calls, and known-error mapping. Routes contain no raw SQL or provider HTTP.
- `app/services/`: provider-neutral market ingestion, stored-observation pricing/replay, retained-registry fair value, portfolio recommendation orchestration, flattened odds behavior, portfolio orchestration, and canonical idempotency hashing. Core pricing, risk, and simulation logic is callable without FastAPI.
- `app/domain/`: league, canonical book, market/period/side/point identity, pure Decimal pricing/vig/consensus/EV, push-aware Kelly, qualification, portfolio allocation, parlay, simulation, money, principal, and error rules.
- `app/providers/`: provider-neutral fetch records and The Odds API adapter. The adapter owns URL/auth construction, bounded retry/backoff, cache, quota metadata, timeout, sanitized errors, raw response capture, and provider parsing.
- `app/db/`: SQLAlchemy 2.x ledger, recommendation/risk, model-registry, and market-data models plus database URL normalization, engine, and session factory.
- `app/persistence/market_repository.py`: atomic raw snapshot, event matching, book mapping, and observation persistence.
- `app/persistence/pricing_repository.py`: read-only, time-bounded projection of normalized observations into provider-neutral pricing inputs.
- `app/persistence/sqlalchemy_repository.py`: primary runtime persistence, transactions, row locking, ledger-derived balances, settlements, ownership, and idempotency records.
- `app/persistence/recommendation_repository.py`: immutable decision/recommendation persistence, current exposure snapshots, transactional approval-time risk revalidation, and official bet/ledger creation.
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
| `recommendation_decision_runs` | Immutable NCAAF slate decision context: equity/state, Top N, policy versions, PASS/rejection reasons, and deterministic input/output hashes. |
| `recommendation_decision_runs` analysis/watchlist metadata | Immutable per-run pricing funnel, rejection counts, analyzed-game summary, and research-only near-qualification rows. Latest-upcoming retrieval changes current research visibility without creating or mutating a recommendation. |
| `recommendations` | Proposed/approved/rejected strategy-book snapshot with exact fair value and executable offer kept separate, alternatives, probability/EV, stake/units/Kelly, classification, risk adjustments, and provenance. |
| `recommendation_legs` | Immutable two/three-leg parlay component snapshots with exact event/market/side/point, marginal probability, price, EV, model version, and provenance. |
| `bets` | Reconstructable official entry snapshot: recommendation kind/class/hash, canonical event/team/time, league/sport, market/period/side/point, book/price/stake, probability/version/decision metadata, approval/placement, closing, result, and realized P&L. |
| `bet_approvals` | One approval audit record per official bet, associated with the authenticated owner and linked recommendation for Phase 6 approvals; legacy direct bets may omit that link. |
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
| `model_registry_entries` | Immutable model/benchmark identity, lifecycle status, source/run hashes, versions, holdout/promotion decision, artifact references, and deterministic entry hash. |
| `artifact_registry_entries` | Immutable governance, model, probability, and holdout artifact metadata with exact content/source hashes and locations. |
| `shadow_predictions` | Append-only prospective event/market/side fair-value payload with producing registry version, frozen morning horizon, source books/timestamps, quality, provenance, and prediction hash. |
| `shadow_prediction_outcomes` | Separate one-per-prediction final score, settlement/evaluation record and outcome hash; it never mutates the pregame prediction. |

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

Portfolio creation, initial funding, recommendation persistence, explicit recommendation approval, bet placement, settlement, their ledger entries, and an optional idempotency record commit atomically in repository-managed `Session.begin()` blocks. Approval locks the owner and recommendation, rechecks current cash/drawdown/exposure, marks the proposal approved, creates the official bet/approval/transition, and reserves stake in one transaction. Any exception rolls the whole mutation back.

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

Phase 4 itself added no tables. Pricing remains a transient deterministic projection from immutable Phase 3 observations; Phase 6 now persists its output only when creating a decision/recommendation snapshot. Every pricing output includes source observation/snapshot IDs, best executable observation, calculation cutoff, and vig, consensus, pricing, and qualification versions.

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

Phase 5 completed the NCAAF model research and retained market consensus after the locked holdout. Phase 6 adds the recommendation/risk/approval boundary shown above while keeping market consensus correctly labeled as a benchmark, not a proprietary probability. Future phases extend prospective monitoring, closing-label automation, and additional leagues without rewriting this boundary.

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

### Phase 5B-7A historical-odds audit layer (implemented offline)

`app.providers.odds_api_historical` owns the credential-bearing historical transport, sanitized failures, provider usage metadata, and exact returned snapshot timestamp. `app.research.ncaaf.historical_odds_audit` owns the frozen 76-logical-request plan, immutable credential-free cache/manifests, deterministic event reconciliation, market completeness checks, predeclared gates, and aggregate reporting. `app.cli.audit_ncaaf_historical_odds` plans by default and requires explicit `--execute` before any historical request.

Raw JSON gzip responses and manifests stay beneath ignored `.ncaaf-data/odds-audit-v1/`; Git contains only code and aggregate reports. Backfilled rows use `the-odds-api-provider-archive-snapshot-v1`: the provider archive timestamp is the historical market-state boundary while local retrieval remains its real 2026 time. This is not equivalent to contemporaneous Phase 3 ingestion. No audit code is imported by FastAPI, and no production endpoint, database schema, dependency, or Render process changed.

### Phase 5B-7B canonical historical-market layer (implemented offline)

`app.research.ncaaf.historical_market_dataset` plans the canonical FBS-vs-FBS acquisition from the Phase 5B-1 schedule, reuses exact or market-superset 7A cache entries, validates closest-prior cutoffs, reconciles provider events, and writes deterministic book-level Parquet observations plus event/horizon/market eligibility groups. `app.cli.historical_market_dataset` keeps planning, explicit acquisition, cache validation, normalization, artifact validation, inspection, and coverage reporting separate.

The primary corpus contains every eligible 2020–2024 game at the versioned first-scheduled-kickoff-minus-three-hours cutoff for h2h, spreads, and totals. The secondary corpus is an outcome-blind, stable-hash sample stratified by season, early/middle/late regular season or postseason, and kickoff window. It covers 60-minute h2h/spreads/totals and near-close spreads/totals, reusing all eligible 7A anchors. Secondary results are diagnostic robustness evidence and cannot be represented as full-cohort estimates.

Every observation retains canonical/provider event identity, programs, kickoff, requested and returned snapshot timestamps, exact book/market/side/point/price, derived decimal odds and implied probability, and immutable source hashes. Eligibility requires a reliable event mapping, an at-or-before cutoff snapshot within the frozen provider cadence, coherent opposing sides/lines, valid prices, and at least two complete DraftKings/FanDuel/BetMGM books. Missing data is classified, never interpolated. Consensus, vig removal, model comparison, EV, CLV, and production inference remain outside this layer.

### Phase 5B-7C market-comparison plumbing (implemented offline)

`app.research.ncaaf.market_comparison` reads only the immutable 7B Parquet observations and 5B-3 OOF prediction artifact. It pairs supported book sides at an exact line, applies `proportional-v1` no-vig independently per book, and produces `unweighted-median-v1` consensus without weights. For spread and total, the deterministic most-supported exact line is selected; probabilities at different points are never averaged. Individual-book pairs, best prices, source hashes, cutoffs, snapshot times, book depth, and dispersion remain attached to each consensus state.

Four content-addressed offline artifacts sit beneath ignored `.ncaaf-data/market-comparison/`: market consensus, same-horizon football/market joins, residual targets, and model-ready market features. Morning maps explicitly from `morning_first_kickoff_minus_3h` to the OOF `game_day_morning` identifier. Sixty-minute rows are `diagnostic_only`; near-close remains consensus-only because no same-horizon football prediction exists. Exact canonical identity, OOF fold provenance, training cutoff, and at-or-before snapshot checks reject invalid joins. No FastAPI import, database schema, production dependency, or provider call was added.

### Phase 5B-7 market-aware tournament (implemented offline)

`app.research.ncaaf.market_aware_modeling` consumes the immutable 7C comparison artifacts, the frozen morning football feature matrix, and prior OOF finalist artifacts. It fits expanding 2020-through-prior-year residual/direct models, learns constrained blend weights only from earlier OOF rows, constructs chronological empirical residual distributions, and writes point/probability Parquet artifacts beneath ignored `.ncaaf-data/market-aware-v1/`. `app.cli.run_ncaaf_market_aware_tournament` runs, validates, and inspects the offline artifacts.

The module rejects 2025, non-morning selection rows, in-sample football predictions, and training cutoffs at or after evaluation season. It preserves integer-line push mass and keeps the small 60-minute/near-close sample diagnostic-only. No research model is imported by FastAPI, no migration was required, and Render/production dependencies and fair-probability behavior remain unchanged.

### Phase 5B-8 finalist-freeze layer (implemented offline)

`app.research.ncaaf.finalist_freeze` is a deterministic policy and integrity boundary. It records the Phase 5B-7 source/artifact hashes, candidate allowlist and rejection list, fixed total-blend weight, push-aware versions, common-cohort policy, numeric promotion gates, fallbacks, and one-time holdout protocol. `app.cli.freeze_ncaaf_finalists` rebuilds the committed machine manifest and can validate ignored local Phase 5B-7 artifacts without reading 2025 or contacting a provider.

This layer does not fit a model, add a database table, load research dependencies into FastAPI, or alter production inference. Its output is a precondition for a separate explicit Phase 5B-9 holdout run.

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

## Phase 6.5 dashboard architecture (implemented)

```text
Cloudflare Pages React client
        |
        | same-origin /api (no credential in browser bundle)
        v
Cloudflare Pages Function secret bridge
        |
        | X-API-Key, server-side only
        v
Render FastAPI -> services/repositories -> PostgreSQL
```

`frontend/` owns presentation, routing, server-state caching, responsive layout, and chart rendering. It does not own probability, EV, sizing, qualification, correlation, or accounting. The Pages Function proxies only `GET`, `POST`, and `OPTIONS` and strips browser authorization/cookie headers before adding the server-side API key.

Two bounded read projections support the UI: `/dashboard/system` exposes safe policy/model/freshness metadata, and `/dashboard/market-movement` returns only scalar observation columns within one slate date/cutoff. Neither query materializes `MarketSnapshot.raw_payload`. Existing recommendation reads now include nullable latest-decision/PASS metadata without changing the recommendation list contract.

The frontend uses a same-origin API path in every environment. Vite's local development proxy reads non-`VITE_` backend secrets server-side; Cloudflare Pages Functions do the same in deployment. Cloudflare Access is the required external identity gate for a private dashboard because the backend still uses the replaceable single-owner API-key boundary.

### POLARIS production-readiness path

The dashboard now has one explicit write-like market workflow: `POST /dashboard/portfolio/{portfolio_id}/refresh-markets`. The browser calls the Cloudflare Pages Function; the BFF injects `APP_API_KEY`; FastAPI acquires a process-local nonblocking refresh guard; the provider adapter performs its existing bounded retry/cache policy; `MarketIngestionService` persists raw and normalized state transactionally; `RecommendationService` evaluates each upcoming slate; and the client invalidates and rereads PostgreSQL-backed dashboard queries. Browser reads never call the provider.

Each decision run also freezes `analysis_summary` and `watchlist_items`. Phase 4 now returns two projections: externally compatible Top-N `opportunities` that meet its baseline policy and an internal untruncated `candidates` collection containing every structurally calculable side before edge/EV/dispersion qualification. Recommendation evaluation consumes the latter, so top-N and baseline threshold filters cannot erase research visibility. Watchlist construction retains only positive-edge/positive-EV candidates that narrowly fail research-safe production gates. It never creates a `Recommendation`, stake, approval route, bet, ledger entry, or parlay leg. `GET /portfolio/{id}/watchlist` selects the newest decision per upcoming UTC slate and aggregates persisted funnel/rejection diagnostics; reads never invoke ingestion.

The funnel records games and observations received/considered, latest/eligible observations, exact paired book markets, comparable exact-line groups, calculable sides, positive edge/EV, pricing-qualified, Watchlist, Phase 6-qualified, and PASS counts. Structural failures remain reason-coded before candidate construction. Spread pairing canonicalizes home `-3.5` with away `+3.5`; inconsistent opposing points are diagnosed explicitly. Distinct points remain distinct groups and integer spread/total lines remain stored but unpriced until push probability is validated.

Recommendation timing uses a pure versioned domain policy. Each slate derives its primary cutoff from its first scheduled kickoff. Exact decision and cutoff timestamps remain distinct, and `EARLY_LOOKAHEAD`, `OFFICIAL_PRIMARY_HORIZON`, and `POST_HORIZON` are presentation/audit metadata rather than changes to pricing math.

`SqlAlchemyDashboardRepository` exposes snapshot status and exact stored market history using scalar projections only. Raw payload JSON is never materialized on dashboard read paths. Application health, market freshness/provider status, and portfolio risk are three separate concerns.

Production startup validates and idempotently installs `docs/reports/NCAAF_MODEL_REGISTRY_V1.json` into PostgreSQL. This closes the prior operational gap where deployment depended on a manual CLI sync. The startup decoder uses production domain registrations and hashing only; it never imports `app.research` or its optional PyArrow/data-science stack. Conflicting immutable registry content fails closed.

### Phase 5B-3 baseline-model architecture (implemented offline)

`app/research/ncaaf/modeling.py` consumes the immutable horizon-specific feature Parquet files and freezes a model-input manifest before training. Reusable expanding folds evaluate 2019–2023 as development seasons and 2024 as validation; 2025 is rejected. Every Ridge fold owns its median imputation, missing indicators, constant-column removal, scaling, and fit. Sequential power ratings predict before updating. Naive, power, and Ridge OOF rows plus JSON-safe fold parameters are written beneath ignored `.ncaaf-data/models/` with dataset, feature, preprocessing, fold, package, and artifact hashes.

The three horizons are never pooled. The first full run found small legitimate feature differences caused by their point-in-time availability boundaries, so each horizon is fitted independently. No database migration or production dependency was added. FastAPI does not import the research modeling stack, and market consensus remains the production pricing source.

Phase 5B-3 does not implement probability calibration, production inference, model/market blending, recommendations, or stake sizing. Those require later promotion gates and the still-sealed holdout.

Every time-sensitive model input must carry `effective_at`, `observed_at`, `ingested_at`, source, provenance, schema version, and reconstructed-versus-contemporaneous status. The as-of builder requires all applicable time boundaries to be at or before the prediction cutoff. Provider corrections supersede rather than overwrite historical versions. Large training and calibration jobs run offline; a future FastAPI inference path may load one approved small artifact only after schema/hash verification and a golden prediction check. Batch refresh or computationally heavy models may later justify a worker.

The proposed research/news pipeline stores cited structured facts through source discovery, entity matching, extraction, reliability tier, corroboration, and versioning. An LLM may assist those steps and explanation rendering; it cannot directly adjust probability. See `NCAAF_MODEL_RESEARCH.md`, `NCAAF_DATA_SOURCES.md`, `NCAAF_SOURCE_AUDIT.md`, `NCAAF_FEATURE_CATALOG.md`, `NCAAF_BACKTEST_DESIGN.md`, and `NCAAF_EXPERIMENT_PLAN.md`.

Not implemented in production: proprietary-model inference, model blending, trusted parlay-price acquisition, same-game joint modeling, structured sports/news ingestion, autonomous settlement, autonomous sportsbook execution, or frontend work. Phase 6 now implements push-aware EV, conservative Kelly sizing, bankroll-aware ranking/stakes, recommendation persistence/approval, risk-policy simulation, and basic closing-probability CLV attribution for NCAAF paper operation. Offline proprietary models remain diagnostic/rejected and do not feed fair value.

### Phase 5B-9 locked-holdout layer (implemented offline)

`app.research.ncaaf.holdout` owns the one-time access record, immutable normalized-manifest assembly, and frozen acquisition identifiers. `app.research.ncaaf.holdout_evaluation` verifies every Phase 5B-8 hash before reading holdout inputs, reconstructs the serialized Ridge preprocessing without invoking a fit API, validates it against saved 2024 predictions, applies the fixed blend, reconstructs the frozen chronological empirical probability state from pre-2025 OOF artifacts, and evaluates only the predeclared gates.

2025 CFBD and historical-market artifacts remain ignored beneath `.ncaaf-data/holdout-2025/` and `.ncaaf-data/holdout-2025-market/`. Git contains only deterministic code and aggregate reports. The FastAPI package does not import the holdout path; production endpoints, database schema, Render dependencies, and Phase 4 pricing behavior remain unchanged.

### Phase 5B-10 registry and prospective-shadow layer (implemented)

`app.domain.model_registry` defines immutable registration, fair-value, prediction, and outcome contracts. `app.research.ncaaf.model_registry` deterministically registers the exact Phase 5B-8/9 hashes and dispositions. `SqlAlchemyModelRegistryRepository` persists registry/artifact metadata and append-only shadow history; `FairValueService` fails closed unless the requested row is the retained market-consensus benchmark.

The boundary is deliberately split:

```text
registered retained benchmark + exact consensus state -> fair-value quote
Phase 4 market observation/pricing path              -> executable offer
Phase 6                                               -> edge / EV / risk / approval
```

`ShadowPredictionService` plans the UTC slate cutoff at first kickoff minus three hours, appends immutable pregame states, and attaches outcomes in a separate table. It does not schedule itself, call providers implicitly, update the bankroll, or create recommendations. New market state creates a new hash/row; registry updates do not alter the version stored on an older prediction.

The migration is additive and PostgreSQL-compatible. FastAPI routes and `uvicorn main:app` remain unchanged. Registry/shadow CLIs explicitly use `DATABASE_URL`; provider access is a separate explicit operation.
