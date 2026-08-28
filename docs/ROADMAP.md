# Roadmap

The roadmap prioritizes a trustworthy paper-trading platform before predictive sophistication or real-money operation. Phases are ordered by dependency, but small vertical slices are preferred over a long-lived rewrite.

## Phase 0 — Repository and safety baseline

Goal: make the prototype safe to change and honest about its behavior.

Status: **Completed in Sprint 1 on 2026-08-28.** At that point JSON persistence, authentication, and idempotency were deferred; Phase 2 has since completed those items, while analytical/modeling gaps remain later work.

- [x] Add durable project documentation and a concise root README.
- [x] Remove the tracked virtual environment and bytecode from version control while retaining appropriate ignore rules.
- [x] Pin direct dependencies and document Python 3.12 as the supported version.
- [x] Add Ruff, mypy, and pytest configuration.
- [x] Add CI for deterministic checks without live credentials.
- [x] Add characterization tests for current endpoints, odds filtering, validation, bankroll, settlement, and statistics.
- [x] Sanitize provider failures so secrets and credential-bearing URLs cannot escape.
- [x] Validate finite numeric inputs, odds domains, probabilities, stake, and result/payout consistency where current contracts permit.
- [x] Define `/odds` date semantics as UTC filtering over current/upcoming provider results.
- [x] Add minimal first-class NCAAF aliases and The Odds API mapping without confusing NCAAF with NCAAB.

Exit criteria:

- A clean checkout contains only source-controlled project assets.
- Tests reproduce current critical behavior without live provider calls.
- Provider errors cannot reveal credentials.
- Known behavior changes are explicit and documented.

## Phase 1 — Modularize without changing product semantics

Goal: establish boundaries that can support V2.

Status: **Completed in the Phase 1 modularization sprint on 2026-08-28.** The transitional provider records and existing bet IDs establish conventions, but full versioned V2 event/market/selection identifiers remain Phase 3 work.

- [x] Introduce immutable application configuration with explicit bankroll and timeout validation.
- [x] Separate API routes, Pydantic contracts, provider adapters, domain normalization/validation, persistence interfaces, and application services.
- [x] Wrap The Odds API behind a provider-neutral interface and transitional `MarketGame`/`MarketOffer` records.
- [x] Add lightweight JSON application logging and request correlation without logging secrets or credential-bearing URLs.
- [x] Centralize timezone-aware UTC timestamps and preserve generated bet-ID behavior.
- [x] Preserve the Sprint 1 HTTP, validation, odds, bankroll, settlement, JSON, and environment behavior through deterministic tests.
- [x] Retain the root `main:app` deployment entry point.

Exit criteria:

- Routes contain orchestration, not provider parsing or financial formulas.
- Provider responses are normalized through tested adapters.
- Core logic can be tested without FastAPI, disk, or network access.

Exit criteria status: **Satisfied.** Routes validate/map HTTP concerns and delegate to services; adapter parsing has isolated tests; odds and portfolio services run against fakes/in-memory persistence without FastAPI, disk, or network.

## Phase 2 — Durable portfolio and bet ledger

Goal: replace mutable JSON state with auditable transactional persistence.

Status: **Completed in Sprint 3 on 2026-08-28.** PostgreSQL is the production database; SQLAlchemy 2.x and Alembic provide the vendor-neutral relational layer and migrations.

- [x] Select PostgreSQL, SQLAlchemy 2.x, psycopg, and Alembic.
- [x] Define owners, portfolios, future-compatible recommendations, approvals, reconstructable bets, state transitions, settlements, ledger entries, and idempotency records.
- [x] Capture available event, market, selection, point, provider, book, entry price, timestamp, probability, closing, and version metadata without inventing missing values.
- [x] Add an initial reversible migration, constraints, repository-managed transactions, and documented deployment/migration procedures.
- [x] Make the immutable ledger the source of cash and preserve reserved stake, equity, exposure, and realized P&L separately.
- [x] Add lightweight API-key principals, portfolio ownership, and cross-owner rejection.
- [x] Add transactional `Idempotency-Key` support to `/bets` and `/bet-result`.
- [x] Add an explicit rerunnable JSON importer with current-cash reconciliation adjustments; it never runs automatically.
- [x] Preserve Render and `uvicorn main:app` while requiring `DATABASE_URL` and `APP_API_KEY`.

Exit criteria:

- Concurrent requests cannot lose bankroll or settlement updates.
- Every balance can be reconstructed from ledger entries.
- Duplicate requests do not create duplicate bets or settlements.
- Unauthorized portfolio access is rejected.

Exit criteria status: **Satisfied for the current private paper-trading service.** PostgreSQL row locks serialize an owner's mutations and target bet settlement; SQLite tests validate atomic rollback and constraints but do not emulate PostgreSQL lock scheduling. Backup/restore operations remain an infrastructure responsibility of the selected PostgreSQL provider and must be tested operationally before production-scale paper trading.

## Phase 3 — Market-data ingestion and normalization

Goal: create reproducible, provider-neutral market snapshots.

- Persist raw provider responses and normalized observations.
- Normalize events, participants, start times, market periods, selections, exact spread/total points, books, and prices.
- Implement event matching with confidence and review paths for ambiguity.
- Add freshness, quota, cache, retry, and rate-limit policies.
- Support scheduled snapshots and closing-price capture.
- Design for additional providers without requiring a second provider immediately.
- Add NCAAF/College Football as a first-class league identifier and provider mapping; never alias it to NCAAB.
- Prioritize NCAAF full-game moneyline, spreads, and totals, followed by equivalent NFL and NBA game-market coverage.

Exit criteria:

- Every normalized price traces back to a raw observation.
- Only truly equivalent markets are compared.
- Stale or ambiguous data is identifiable and excluded from automated recommendations.

## Phase 4 — Baseline pricing and EV engine

Goal: generate transparent market-consensus opportunities as a baseline and benchmark without claiming a proprietary model.

- Implement and test American/decimal odds conversion.
- Implement a versioned initial vig-removal method.
- Build a transparent multi-book consensus policy with outlier and staleness handling.
- Calculate offered implied probability, consensus probability, initial fair probability, probability edge, and EV.
- Attach source, version, inputs, and uncertainty/data-quality indicators to every calculation.
- Create deterministic fixtures and offline replay/backtest tooling.
- Produce up to a configurable Top N qualified opportunities per selected league, normally capped at 10, without relaxing thresholds to fill the list.
- Preserve the best executable price and every required recommendation field even before a proprietary model is available.

Exit criteria:

- Every recommendation can reproduce its fair price and EV from stored observations.
- Market consensus is labeled accurately.
- Numerical and market-identity edge cases are covered by tests.
- Returning fewer than Top N, including zero, is tested as correct behavior.

### Short-term milestone — Opening-weekend NCAAF paper-trading baseline

As soon as Phases 2–4 provide the minimum reliable path, run an opening-weekend NCAAF paper-trading baseline that captures:

- timestamped odds and normalized full-game markets;
- no-vig and multi-book consensus calculations;
- qualification decisions and up to the requested Top N recommendations;
- best executable prices, initial fair probabilities, edge, EV, and uncertainty flags;
- versioned paper stakes and portfolio-equity percentages;
- explicit human approvals;
- closing prices; and
- outcomes, settlement, and basic ROI/CLV reconciliation.

This milestone must proceed even if the first proprietary NCAAF model is not production-ready. In that case, label consensus as the final fair-probability source for that baseline and preserve an explicit null/not-available proprietary probability.

## Phase 5 — NCAAF predictive-model track

Goal: begin sport-specific modeling immediately after the market baseline exists and evaluate it against consensus.

- Select structured NCAAF schedules, results, team statistics, injury/availability, weather, and other research-data sources.
- Build reproducible, time-aware feature pipelines with provenance and leakage controls.
- Define baseline model families and strict chronological train/validation/test splits.
- Record consensus probability, proprietary model probability, and candidate final fair probability separately.
- Evaluate calibration, Brier score, log loss, performance versus closing markets, and incremental value over consensus.
- Create a model registry/versioning and promotion process.
- Keep model outputs experimental until predefined out-of-sample gates are met.
- Ensure LLM-discovered research enters only through traceable structured signals; prohibit undocumented probability adjustments.

Exit criteria:

- Every prediction is reproducible from versioned data, features, and code.
- Leakage and time-boundary tests exist.
- The NCAAF model is compared directly with the consensus baseline.
- Failure to beat or complement consensus results in no promotion, not forced blending.

## Phase 6 — Portfolio risk, staking, and approval

Goal: turn positive-EV observations into conservative, reviewable portfolio recommendations.

- Define a fractional-Kelly candidate policy; never use full Kelly.
- Scale stake recommendations from current portfolio equity rather than fixed dollars.
- Define a versioned unit display policy tied to current equity.
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
- Dollar stake, equity percentage, displayed units, and policy version reconcile.

## Phase 7 — NFL and NBA model expansion

Goal: reuse validated platform primitives while preserving league-specific modeling.

- Extend the full-game market and predictive-model pipeline to NFL after NCAAF foundations stabilize.
- Extend NBA game-market models using availability, projected minutes, usage, pace, rest, lineup, and matchup features.
- Add alternate spread/total and half/quarter markets only after equivalent full-game pipelines are validated.
- Design player-level data and projection architecture before implementing player props.
- Treat NBA player props as the first likely prop expansion; NFL props follow only with adequate player-level projections and validation.
- Keep league-specific model evaluation and calibration separate while sharing common pricing, risk, ledger, and approval infrastructure.

Exit criteria:

- NFL and NBA models are independently versioned and benchmarked against consensus.
- Expanded markets have explicit identity, settlement, and test fixtures.
- No player prop is recommended without a reproducible player-level projection path.

## Phase 8 — Closing, settlement, and analytics

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

## Phase 9 — Calibration and model improvement

Goal: improve estimates through statistically defensible evidence.

- Add Brier score, log loss, reliability plots/tables, uncertainty intervals, and sample-size reporting.
- Establish time-based out-of-sample evaluation and model registries/versioning.
- Compare each proprietary sport-specific model against the market-consensus baseline and against its prior production version.
- Define conservative promotion, rollback, and weight-change criteria.
- Prevent small samples or recent streaks from automatically increasing confidence or stakes.

Exit criteria:

- Model changes are supported by reproducible out-of-sample evidence.
- Historical predictions remain tied to the version that produced them.
- No online “learning” silently mutates production policy.

## Phase 10 — Paper-trading production hardening

Goal: operate the research platform reliably over long observation periods.

- Add monitoring, alerts, audit logs, restore drills, provider health, quota dashboards, and runbooks.
- Add performance and load testing, security review, and data-retention policy.
- Run extended paper-trading evaluations across seasons and market conditions.
- Define explicit evidence gates before any discussion of meaningful real-money use.

Autonomous real-money execution remains out of scope. Any change to that boundary requires a new explicit product decision and a separate security, legal, operational, and risk review.

## Immediate recommended sequence

1. Provision PostgreSQL, apply the Phase 2 migration, and explicitly import/reconcile any retained prototype JSON data.
2. Build the normalized, persisted NCAAF market snapshot path.
3. Implement the transparent consensus/EV baseline.
4. Run the opening-weekend NCAAF paper-trading milestone while beginning the NCAAF model track.
5. Add the conservative equity-scaled risk and approval engine before expanding scope.

