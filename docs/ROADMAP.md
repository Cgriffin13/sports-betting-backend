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

Status: **Completed in the Phase 3 market-data sprint on 2026-08-28.** Phase 3 stores source and normalized prices; it does not calculate probability, consensus, EV, recommendations, or CLV.

- [x] Persist exact raw provider responses, credential-free request context, source/quota metadata, warnings/errors, and normalized observations transactionally.
- [x] Normalize stable events, provider-event mappings, canonical/provider books, UTC starts, full-game periods, selection sides, exact spread/total points, and American prices.
- [x] Match exact provider IDs deterministically and preserve confidence, provenance, and reviewable candidates instead of silently merging conflicts or missing IDs.
- [x] Add versioned/configurable freshness fields and bounded configurable retry, exponential backoff, cache, quota metadata, and low-quota warning policies.
- [x] Preserve multiple timestamped snapshots and exact market identity so first, latest pre-start, entry-time, and future closing observations can be selected reproducibly.
- [x] Keep ingestion callable outside FastAPI through an application service and CLI for manual, cron, or future worker invocation; no scheduler is introduced.
- [x] Keep The Odds API behind the provider interface and retain NCAAF as distinct from NCAAB.
- [x] Validate NCAAF full-game moneyline, spread, and total observations across DraftKings, FanDuel, and BetMGM, including repeated snapshots and line movement.

Exit criteria:

- Every normalized price traces back to a raw observation.
- Only truly equivalent markets are compared.
- Stale or ambiguous data is identifiable and excluded from automated recommendations.

Exit criteria status: **Satisfied.** Every observation has a raw snapshot/source path; canonical identity includes event, book, market, period, side, and exact point; repeat provider events reuse only consistent mappings; ambiguous/stale records are explicit; and retry/cache/quota behavior is bounded and tested. There is no automated recommendation path yet, so Phase 4 must enforce the stored stale and match-review flags when qualification is introduced.

## Phase 4 — Baseline pricing and EV engine

Goal: generate transparent market-consensus opportunities as a baseline and benchmark without claiming a proprietary model.

Status: **Completed in Sprint 5 on 2026-08-28.** Calculations are transient, versioned projections from immutable Phase 3 observations; no recommendation/stake persistence or proprietary probability is claimed.

- [x] Implement and test Decimal American/decimal odds conversion, implied probability, edge, and binary/push-form EV primitives.
- [x] Implement `proportional-v1` two-outcome vig removal with explicit 12-decimal half-even probability precision.
- [x] Implement `unweighted-median-v1` multi-book consensus without unevidenced weights, with configurable book minimums, outlier flags, and maximum dispersion.
- [x] Exclude stale, inactive, ambiguous, malformed, incomplete, unsupported, and superseded book/market states.
- [x] Separate the best executable observation/price from the market-consensus fair-probability source.
- [x] Calculate implied probability, consensus/final fair probability, probability edge, and EV with full observation/snapshot and policy provenance.
- [x] Add `baseline-qualification-v1` and deterministic EV/data-quality ranking with configurable thresholds.
- [x] Produce up to configurable Top N per selected league, default 10, without relaxing thresholds; zero-result behavior is tested.
- [x] Add an authenticated paper/research `/opportunities` endpoint that preserves all existing APIs and returns no stake.
- [x] Add deterministic offline pricing replay through the shared service and CLI with observation-time and ingestion-time cutoff enforcement.
- [x] Preserve integer spread/total observations while conservatively excluding them from EV qualification until push probability is modeled.

Exit criteria:

- Every recommendation can reproduce its fair price and EV from stored observations.
- Market consensus is labeled accurately.
- Numerical and market-identity edge cases are covered by tests.
- Returning fewer than Top N, including zero, is tested as correct behavior.

Exit criteria status: **Satisfied.** Every baseline opportunity reproduces from exact stored observations; market consensus is explicitly labeled and proprietary probability remains null; exact line/period/side pairing, vig, outlier, dispersion, best-price, edge, EV, Top N, zero-result, repeat-snapshot, and no-future-leakage behavior are deterministic and tested. Pricing replay is implemented; outcome backtesting and portfolio simulation remain correctly deferred.

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

Status: **Completed through Phase 5B-10 on 2026-08-31.** The locked 2025 holdout rejected the total blend, market consensus was registered as the retained NCAAF v1 benchmark for every initial market, and immutable prospective-shadow records are ready for 2026. No recommendation, EV, staking, or production-betting behavior changed.

- [x] Research structured NCAAF schedules, results, play-by-play, team/personnel, injury/availability, weather, research, and historical-odds sources, costs, terms, and coverage risks.
- [x] Specify bitemporal source/feature contracts and strict chronological train/validation/test methodology.
- [x] Define a model tournament across naive, Elo, regularized regression, boosted-tree, component-score, hierarchical, and evidence-learned ensemble candidates.
- [x] Define margin and total predictive distributions as primary targets, with direct win and component-score challengers.
- [x] Define calibration, uncertainty, integer push-probability, registry, explanation, promotion, and falsification requirements.
- [x] Complete the Phase 5B-0 public source/identity audit, target contract, cost model, and bounded provider-audit designs.
- [x] Execute the credentialed CFBD audit and ingest the 2014–2024 development corpus with credential-free request hashes, immutable source versions, correction links, and safe resume.
- [x] Add canonical program/venue identity, effective-dated aliases/conferences, existing-event linkage, explicit game eligibility/targets, and a tested 2025 holdout guard.
- [x] Add reproducible audit/ingestion/manifest/corpus-report CLIs and reconcile measured CFBD coverage against the Phase 5B-0 cfbfastR QA baseline.
- [x] Phase 5B-2: freeze a versioned fact normalization/dataset contract, retain the known non-final game with its exclusion, and build leakage-tested pregame feature tables from 2014–2024 without normalizing unrelated lower-division identities.
- [x] Build reproducible, time-aware feature pipelines with provenance and leakage/time-travel tests.
- [x] Phase 5B-3: run naive, chronological power-rating, and fold-local Ridge falsification baselines for margin/total across each horizon; persist deterministic OOF predictions and residual diagnostics. Elastic Net is explicitly deferred after bounded convergence failures.
- [x] Phase 5B-4: fit predeclared Normal, Student-t, empirical, quality-aware, and total skew-normal distributions chronologically; emit deterministic moneyline/spread/total probabilities with explicit integer push mass; report proper scores, interval/PIT, key-number, segment, and paired-bootstrap diagnostics.
- [x] Phase 5B-6: audit/cache bounded CFBD preseason/personnel sources; materialize reconstructed point-in-time program-season features; run targeted power/Ridge/CatBoost comparisons, family ablations, uncertainty segments, and limited probability checks without opening 2025.
- [x] Run naive, power-rating, Ridge, distribution, and equal-budget XGBoost/LightGBM/CatBoost experiments under frozen chronological folds; defer unstable Elastic Net with evidence.
- [x] Evaluate chronological empirical-discrete margin mass without manually boosting key numbers; retain its wider interval coverage as an explicit limitation.
- [x] Audit a frozen 2020/2022/2024 historical-odds sample under predeclared timestamp, coverage, book-depth, pairing, and identity gates; preserve raw payloads outside Git and publish aggregate evidence.
- [x] Phase 5B-7B: acquire, reconcile, normalize, and validate the full 2020–2024 morning corpus plus the deterministic bounded 60-minute/near-close robustness cohort under immutable source manifests and strict cutoff rules.
- [x] Phase 5B-7C: construct versioned exact-line no-vig consensus, join selected same-horizon OOF football predictions, preserve push-aware labels, and emit deterministic common-cohort/residual/model-feature artifacts without fitting a market-aware model.
- [x] Full Phase 5B-7: fit and evaluate market-only, frozen football finalists, residual, market-as-feature, and bounded OOF blend candidates on identical 7C common cohorts; keep later horizons diagnostic and 2025 sealed. See `NCAAF_MARKET_AWARE_MODEL_REPORT.md`.
- [x] Phase 5B-8: freeze the exact finalist allowlist, artifact hashes, fixed total-blend weight, practical-effect/calibration/segment gates, deterministic fallbacks, and one-time 2025 protocol. See `NCAAF_FINALIST_FREEZE.md`.
- [x] Phase 5B-9: explicitly unlock and evaluate 2025 exactly once against the Phase 5B-8 manifest without refitting; the total challenger failed and market consensus was retained.
- [x] Phase 5B-10: register the retained/rejected/diagnostic results, expose a market-consensus-only fair-value contract, and add immutable prospective 2026 shadow prediction/outcome records.
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

Phase 5B implementation order:

1. credentialed source acquisition and identity implementation, following the completed 5B-0 audit;
2. raw historical facts ingestion and immutable manifests (**complete in 5B-1**);
3. as-of feature/dataset builder (**complete in 5B-2**);
4. naive, Elo, and Ridge falsification baselines (**complete in 5B-3; Elastic Net deferred with evidence**);
5. distributions, calibration, and integer push probabilities offline (**complete in 5B-4; quality-aware margin and empirical total candidates advanced for later offline comparison**);
6. bounded tree and key-number challengers (**complete in 5B-5; CatBoost total advances only as a point challenger, empirical-discrete margin advances offline**);
7. reconstructed preseason/personnel research (**complete in 5B-6; recruiting/talent and a bounded power-prior adjustment advance offline; transfer-era coverage is not accepted for the common cohort**);
8. bounded historical-odds audit (**complete in 5B-7A; conditional GO for morning and 60-minute ML/spread/total plus near-close spread/total**);
9. canonical same-horizon market dataset (**complete in 5B-7B; full morning primary cohort and bounded later-horizon robustness cohort**);
10. fixed-horizon market residual/comparison experiments using only approved combinations;
11. learned blend and once-only locked evaluation;
12. registry plus prospective shadow operation; and
13. separately reviewed production-inference decision only if gates pass.

Phase 5 exit criteria are **satisfied**. The research produced reproducible predictions, direct same-horizon market comparison, a locked holdout, an honest no-promotion result, immutable registry evidence, and a prospective shadow boundary. The result is a retained market benchmark, not proprietary edge or production betting approval.

## Phase 6 — Portfolio risk, staking, and approval

Goal: turn positive-EV observations into conservative, reviewable portfolio recommendations.

Status: **Implemented for NCAAF v1 paper trading on 2026-09-01.** The retained Phase 5 market-consensus benchmark is compared separately with exact executable prices; versioned qualification, push-aware EV, fractional Kelly, CORE/OPPORTUNISTIC allocation, exposure/drawdown states, immutable recommendations, approval-time risk revalidation, ledger integration, attribution, and an offline simulator are implemented. The cross-event parlay optimizer is implemented but correctly returns PASS until a trusted executable combined-price adapter supplies a verified quote; same-game parlays remain excluded.

Production methodology follow-up (2026-09-02): qualified straights now use robust expected log growth at the projected adjusted-Kelly fraction instead of the former EV-dominated heuristic. Consensus-outlier warnings remain visible but no longer reject a current, supported, validly paired executable quote solely for differing from the median; hard integrity and dispersion gates remain. Ranked order and its Kelly/growth provenance persist through API reads. `ncaaf-qualification-v3` adds only the explicit no-longshot-sleeve safety guardrail: a price above `+500` remains calculable but cannot enter the main board, staking, approval, or parlays. There is no additional `-300/+300` hard band, and fair value, EV, sizing multipliers, and exposure limits did not change.

- [x] Define a fractional-Kelly candidate policy; never use full Kelly.
- [x] Scale stake recommendations from current portfolio equity rather than fixed dollars.
- [x] Define a versioned unit display policy tied to current equity.
- [x] Add per-bet, daily, aggregate, sport/market, event, and correlation exposure limits.
- [x] Add confidence/data-quality adjustments and drawdown-aware reductions.
- [x] Define ranking rules that consider EV, uncertainty, liquidity/freshness, and portfolio impact—not edge alone.
- [x] Make “no bet” a first-class decision.
- [x] Implement immutable recommendation snapshots and explicit human approve/reject actions.
- [x] Preserve both a frozen strategy/model book (every qualified recommendation, including declines) and the actual/executed paper book. Attribution separates model/selection quality from approval and execution effects.
- [x] Keep official bets as paper bets; no autonomous sportsbook execution.

Exit criteria:

- Risk invariants hold under deterministic scenario tests.
- An analysis cannot become an official bet without recorded human approval.
- Stake recommendations are explainable and reproducible.
- Dollar stake, equity percentage, displayed units, and policy version reconcile.

Exit criteria status: **Satisfied for the NCAAF v1 paper baseline.** Trusted parlay quote acquisition and same-game correlation are explicit later hardening, not silently simulated capabilities.

## Phase 6.5 — Paper-trading dashboard

Goal: present the implemented portfolio workflow without moving decision logic into the client.

Status: **Implemented on 2026-09-01 and production-readiness hardened.** The POLARIS React/TypeScript dashboard renders the backend-authoritative paper workflow across Today, Watchlist, Portfolio, Bets, Parlay, History, and read-only Settings. Watchlist is explicitly research-only and preserves the existing qualification discipline. Research/model transparency lives under System / Methodology; stored movement lives in decision detail. A same-origin Cloudflare Pages Function keeps `APP_API_KEY` out of the static browser bundle. Only the prominent authenticated Refresh Markets action invokes provider ingestion; ordinary browser refetches read stored state.

Production correctness follow-up: the candidate funnel now retains structurally calculable below-threshold sides for deterministic Watchlist/PASS classification before Phase 4 Top-N truncation. Persisted aggregate and per-UTC-slate funnel/rejection diagnostics appear under Settings → System / Methodology. Qualification, fair value, risk, staking, and parlay policies are unchanged.

NCAAF market-scoring follow-up: `ncaaf-empirical-cross-line-v1` now keeps exact pairing inside each book but derives one robust market center across differing supported-book spread/total main lines. It evaluates each executable line with empirical discrete win/push/loss mass, preserves fair-line and line-advantage provenance, and segments funnel diagnostics by market and fixed odds bands. The chronological 2020–2024 audit retained the existing 0.75pp edge and 1.5% EV gates for every initial market; no quota or current-slate optimization was introduced.

- Render fair value and executable price as separate fields.
- Show proposed recommendations separately from approved official paper bets.
- Make PASS, risk adjustments, portfolio state, and approval status visible.
- Show cash, reserved exposure, equity, open bets, history, and segmented performance.
- Keep all qualification, sizing, and risk enforcement in the backend.

Exit criteria:

- The dashboard can review and approve/reject recommendations and inspect open/settled history through authenticated backend contracts. Analysis and settlement remain available through existing backend APIs but do not yet have dashboard mutation forms.
- Displayed dollars, equity percentages, units, and exposure reconcile with backend responses.
- No client action can bypass approval-time risk revalidation.

Exit criteria status: **Satisfied for the requested Phase 6.5 presentation scope.** Direct dashboard settlement/analysis controls, scheduled-refresh publication, full ledger time-series/CLV, and Cloudflare Access/deployment are launch follow-ups rather than client-side calculations.

### POLARIS production-readiness completion

- [x] Replace user-facing prototype branding and reduce primary navigation to six operational destinations.
- [x] Add explicit secure all-upcoming-NCAAF manual market refresh with concurrency protection and structured results.
- [x] Preserve the primary `first kickoff - 3 hours` horizon and label early/official/post-horizon decisions distinctly.
- [x] Separate market freshness/provider failure from application health and portfolio risk.
- [x] Bootstrap the frozen Phase 5 model registry idempotently at startup.
- [x] Embed exact stored market history in recommendation detail without provider calls or raw JSON reads.
- [ ] Configure Cloudflare Access and production Pages/Render environment secrets, then perform the operator-owned deployment and smoke test.

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
- Permit portfolio-risk policy changes to respond to equity, exposure, drawdown, uncertainty, and validated model performance only through bounded, versioned, reproducibly evaluated rules.

Exit criteria:

- Model changes are supported by reproducible out-of-sample evidence.
- Historical predictions remain tied to the version that produced them.
- No online “learning” silently mutates production policy.

## Later capability — Controlled Parlay of the Day research sleeve

Goal: evaluate whether a narrowly constrained featured parlay can add value without weakening or displacing the straight-bet portfolio.

Status: **Initial Phase 6 optimizer and risk sleeve implemented.** It searches only verified cross-event disjoint-team quotes and returns PASS without one. The current provider has no executable parlay product, so prospective sleeve evidence and same-game correlation remain future work.

This capability begins only after the core straight-bet market normalization, pricing/EV, sport-model, portfolio-risk, closing-price, settlement, and evaluation pipeline is proven. It is not part of Phase 3 and must not delay the NCAAF straight-bet baseline.

- Return at most one featured parlay per day/league scope; zero is valid and no candidate may be manufactured to fill the feature.
- Require every leg to independently pass the applicable straight-bet qualification standards.
- Capture the sportsbook's executable combined payout and compare it with a versioned modeled joint fair probability.
- Begin research with cross-event combinations whose independence assumptions can be documented and tested.
- Exclude same-game and materially correlated combinations until a joint-probability method using correlation modeling, simulation, or equivalent validation passes out-of-sample evaluation.
- Allocate a separate conservative risk sleeve with lower stake caps and shared portfolio exposure/correlation controls.
- Persist component-leg context, joint-probability method/version, entry EV, stake, closing observations, outcome, and P&L.
- Report parlay stake, realized P&L, ROI/yield, hit rate, entry EV, sample size, and later CLV/calibration where meaningful separately from straight bets.
- Allow the portfolio engine to reduce or disable the sleeve under a versioned policy when out-of-sample evidence shows detrimental risk-adjusted performance.

Exit criteria:

- Straight-bet qualification and allocation remain primary and are unchanged by parlay availability.
- Joint probabilities and executable payouts are reproducible and auditable.
- Correlation assumptions are explicit; unknown material correlation rejects the candidate.
- Parlay risk and performance are isolated, measurable, and disableable.
- Kelly multipliers, caps, leg counts, minimum EV, correlation policy, and evidence gates are empirically accepted before any production-quality recommendation.

## Phase 10 — Paper-trading production hardening

Goal: operate the research platform reliably over long observation periods.

- Add monitoring, alerts, audit logs, restore drills, provider health, quota dashboards, and runbooks.
- Add performance and load testing, security review, and data-retention policy.
- Run extended paper-trading evaluations across seasons and market conditions.
- Define explicit evidence gates before any discussion of meaningful real-money use.

Autonomous real-money execution remains out of scope. Any change to that boundary requires a new explicit product decision and a separate security, legal, operational, and risk review.

## Immediate recommended sequence

1. Apply current migrations in each deployed PostgreSQL environment and collect continuous timestamped NCAAF snapshots.
2. Exercise the Phase 6 recommendation/approval path in paper operation and verify decision, exposure, and ledger reconciliation.
3. Build the Phase 6.5 dashboard against the documented read/approval contract without duplicating portfolio logic in the client.
4. Run the opening-weekend NCAAF paper-trading milestone with entry, closing, outcome, and reconciliation capture.


## Phase 5B-9 — Locked 2025 holdout (complete)

The one-time 2025 holdout was opened only after Phase 5B-8 froze finalists, artifacts, the total blend weight, and every promotion gate. The market/Ridge total blend failed the required MAE, multiclass Brier, and multiclass log-loss improvement thresholds on the 758-game identical cohort. Market consensus remains the NCAAF estimator for margin, moneyline, spread, and total; football power remains diagnostic only.

Phase 5B-10 registered these retained market benchmarks for prospective shadow operation and immutable monitoring. It did not tune a replacement on 2025, promote the rejected blend, or treat holdout results as authorization for production recommendations, EV qualification, or staking.
