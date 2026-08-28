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
- `requirements.txt` and `requirements-dev.txt`: pinned direct runtime and validation dependencies.
- `tests/`: deterministic FastAPI and domain characterization tests with mocked provider requests.
- `pyproject.toml`: pytest, Ruff, and mypy configuration.
- `.github/workflows/ci.yml`: Python 3.12 lint, type-check, and test workflow.
- `data/.gitkeep`: placeholder for runtime data.
- `.gitignore`: ignores local secrets, virtual environments, and bytecode.

### Current API surface

| Endpoint | Current behavior |
| --- | --- |
| `GET /health` | Reports service status, whether an odds key exists, storage paths, and UTC time. |
| `POST /odds` | Fetches current/upcoming odds and filters timezone-aware provider events to the requested UTC calendar date. It does not query historical odds. |
| `GET /portfolio/{portfolio_id}` | Auto-creates missing portfolios and returns bankroll plus recent bets. |
| `POST /bets` | Records a caller-provided bet and deducts its stake. |
| `POST /bet-result` | Records a caller-provided result and net payout, then updates bankroll. |
| `GET /portfolio/{portfolio_id}/stats` | Computes settled-bet totals and sport/market buckets. |

### Current data flow

Odds retrieval:

1. Normalize requested sport and market labels.
2. Query The Odds API sequentially for each supported sport.
3. Filter provider events to the requested UTC calendar date.
4. Keep US-region American odds from allowed books.
5. Flatten provider events into games and offers.
6. Return results without persisting a market snapshot.

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

The Odds API is directly embedded in route logic. The integration uses synchronous `requests`, a 12-second timeout, one sequential request per sport, American odds, US region, exact sportsbook-title filtering, sanitized client-facing errors, and UTC date filtering. There is no provider interface, cache, retry policy, quota guard, or stored snapshot.

The code maps NCAAF to `americanfootball_ncaaf` and keeps it distinct from NCAAB (`basketball_ncaab`). It also maps NFL, NBA, NHL, MLB, and WNBA. Initial market scope remains full-game `h2h`, `spreads`, and `totals`.

### Current security and operational boundaries

There is deterministic test coverage and lightweight CI, but no authentication, authorization, rate limiting, idempotency, structured logging, metrics, or tracing. Portfolio IDs function as unprotected lookup keys. The `main` branch is currently unprotected.

## Proposed V2 architecture

The target is a modular paper-trading platform with explicit boundaries and auditable domain records.

```text
Odds Providers -----> Market Normalization -----> Market Consensus -----+
                                                                         |
Sports/Stats Data --> Sport Feature Pipelines --> Predictive Models -----+--> Final Fair Probability
                                                                         |             |
News/Research ------> Traceable Structured Signals ----------------------+             v
                                                                               EV & Qualification
                                                                                      |
                                                                                      v
Portfolio Equity --> Risk Budget / Correlation Controls --> Stake & Rank --> Top N Interface
                                                                                      |
                                                                                      v
                                                                       Explicit Human Approval
                                                                                      |
                                                                                      v
Bet Ledger --> Closing Price Capture --> Settlement --> Performance & Calibration
```

Market consensus is both an initial pricing baseline and the benchmark for evaluating proprietary models. The long-term product is expected to combine market and model evidence; it is not limited to consensus scanning.

### Proposed component responsibilities

#### API layer

Own request/response contracts, authentication, authorization, idempotency keys, and error mapping. It should orchestrate application services without containing pricing formulas or provider parsing.

#### Market-data adapters

Implement a provider-neutral interface for The Odds API and future providers. Preserve raw snapshots for reproducibility, sanitize failures, track quotas, and convert provider payloads into normalized records.

NCAAF is the first new league requirement, followed by deeper NFL and NBA support. Initial NCAAF and NFL adapters should support full-game moneyline, spreads, and totals before alternate, half, quarter, or player-prop markets.

#### Structured sports-data adapters

Ingest provider-neutral schedules, results, team statistics, and sport-specific features. NCAAF and NFL require team/game context; NBA eventually requires player availability, projected minutes, usage, pace, rest, lineup, and matchup data. Raw source records and transformation versions must remain traceable.

#### Research and signal ingestion

Capture injuries, availability, news, and research as sourced, timestamped, structured signals. LLMs may assist discovery, extraction, summarization, and explanation, but probability changes must occur only through documented, versioned model or policy inputs.

#### Normalization

Resolve stable internal IDs for events, participants, markets, selections, and exact line points. Ensure prices are compared only when event, market, period, selection, and line are equivalent.

#### Pricing and probability engine

Provide pure, versioned calculations for odds conversion, vig removal, consensus construction, final fair-probability policy, uncertainty, edge, and EV. Every output must identify its source and calculation version.

#### Sport-specific model pipelines

Train, evaluate, and serve versioned league-specific models against the market-consensus benchmark. NCAAF is first, then NFL and NBA. Historical variables and research signals enter only when their out-of-sample value is reproducible. Market-consensus and proprietary probabilities must remain separately observable even when a final fair-probability policy blends them.

#### Portfolio and risk engine

Recommend stakes from current portfolio equity, EV, uncertainty, open exposure, daily risk, and correlation constraints. Stakes scale with equity under a versioned conservative fractional-Kelly/risk-budget policy. Full Kelly is prohibited; final policy remains to be validated through paper trading. Units are a bankroll-relative display abstraction, not fixed dollars.

#### Recommendation and approval workflow

Create immutable recommendation snapshots and record explicit human approval or rejection. The interface returns up to a configurable Top N qualified opportunities per selected league, normally no more than 10. It must never relax qualification rules to fill Top N.

Each recommendation exposes the best executable book/price, implied probability, consensus probability, proprietary-model probability when available, final fair probability, edge, EV, uncertainty/confidence, stake, equity percentage, and a traceable research explanation. Approval creates an official paper bet; analysis alone must not mutate the ledger.

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
- structured sport/statistical observations and traceable news/research signals;
- pricing/model versions and probability estimates;
- recommendations, qualification decisions, research explanations, and approval records;
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
- Separate persisted consensus, proprietary-model, and final fair probabilities.
- Qualification and Top N truncation applied after deterministic eligibility rules.

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
- Structured sports/statistical data providers and licensing/retention constraints.
- Injury/news/research providers, provenance schema, and signal freshness policy.
- Event identity and cross-provider matching strategy.
- Final fair-probability selection or blending policy.
- League-specific feature stores, model families, and model-serving topology.
- Top N qualification thresholds, tie-breaking, and per-league allocation behavior.
- Equity definition, unit display convention, fractional-Kelly multiplier, and risk budgets.
- API versioning and compatibility policy.

