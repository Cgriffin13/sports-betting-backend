# Decision Log

This file is the durable Architecture Decision Record (ADR) index for product and engineering choices. Add a dated entry when a decision changes architecture, model semantics, risk policy, data contracts, or product boundaries. Do not rewrite prior decisions to hide history; mark them superseded and link the replacement.

Statuses used here:

- **Accepted**: current intended direction, whether or not fully implemented.
- **Current prototype**: describes an implementation choice that exists but is not necessarily the target.
- **Proposed**: a likely direction requiring an explicit future decision.
- **Superseded**: replaced by a later decision.

## ADR-001 — Paper trading before meaningful real-money use

- Date: 2026-08-28
- Status: Accepted

The platform is experimental and should validate its methodology through extensive paper trading. Reliable data, auditability, calibration, and risk measurement take priority over real-money operation.

Consequences:

- Roadmap success is measured first by reproducible evidence and operational correctness.
- Paper results must not be presented as proof of future profitability.
- Meaningful real-money use requires a later explicit decision and evidence gate.

## ADR-002 — Human approval for every official bet

- Date: 2026-08-28
- Status: Accepted

Automated analysis and recommendations are allowed, but an official bet requires explicit human approval. Autonomous real-money sportsbook execution is outside the current roadmap.

Consequences:

- Recommendation and approval are separate persisted states.
- Analysis must not directly mutate the official bet ledger.
- Approval identity, timestamp, and accepted stake/price should be auditable.

## ADR-003 — Code and documentation have different truth domains

- Date: 2026-08-28
- Status: Accepted

The repository code is the source of truth for currently implemented behavior. These documents are the source of truth for intended product behavior and architectural direction.

Consequences:

- Planned features must be labeled as planned.
- A conflict must be surfaced and resolved, not silently rationalized.
- Behavior and architecture changes should update documentation in the same change.

## ADR-004 — Initial market data provider

- Date: Historical; recorded 2026-08-28
- Status: Current prototype

The prototype uses The Odds API and is hosted through Render. At the time of this decision, provider calls lived directly in `main.py`.

Implementation note (2026-08-28): ADR-023 completed the planned isolation. The Odds API remains the provider, but its URL, credentials, transport, timeout, sanitized failures, and payload parsing now live in a concrete adapter behind a provider-neutral protocol.

Consequences:

- Existing behavior depends on provider sport keys, book titles, quotas, and payloads.
- V2 should preserve The Odds API as an initial adapter while removing it from domain logic.
- Multi-provider support is a design requirement, not an implemented capability.

## ADR-005 — Market consensus is the initial V2 pricing baseline

- Date: 2026-08-28
- Status: Accepted

An initial V2 fair-price engine may use implied probabilities, vig removal, and normalized multi-book consensus. Sophisticated machine learning is not required for the first legitimate pricing engine. Consensus remains the baseline and benchmark against which proprietary models are evaluated, but it is not assumed to be the final long-term fair probability.

Consequences:

- Consensus methodology and inputs must be transparent and versioned.
- A market-derived estimate must not be called a proprietary predictive model.
- Proprietary models should be evaluated against this reproducible baseline, beginning with NCAAF after the baseline engine exists.
- Consensus, proprietary-model, and final fair probabilities must remain separately observable.

## ADR-006 — Recommendations are not ranked by edge alone

- Date: Historical; recorded 2026-08-28
- Status: Accepted

Probability edge alone is insufficient for ranking. EV, estimated probability, uncertainty, confidence, price quality, bankroll risk, exposure, and correlation all matter.

Consequences:

- Ranking logic must expose its components.
- Large uncertain edges may be rejected or ranked below smaller reliable opportunities.
- “No bet” is a valid output.

## ADR-007 — Never blindly use full Kelly

- Date: Historical; recorded 2026-08-28
- Status: Accepted

Full Kelly staking is too aggressive for the intended experimental system and estimation uncertainty. V2 should investigate fractional Kelly combined with conservative caps and portfolio controls.

Historical 1–3% normal and 5–10% exceptional stake ranges are context only, not fixed policy.

Consequences:

- Full Kelly must not be the automatic stake.
- Confidence, daily risk, aggregate exposure, correlation, and drawdown controls are required.
- Exact multipliers and caps remain an open, testable policy decision.

## ADR-008 — Production persistence must be transactional and auditable

- Date: 2026-08-28
- Status: Accepted

Shared mutable JSON state is inadequate for V2. Production persistence must support transactions, constraints, concurrency, idempotency, migrations, and reconstruction of bankroll changes.

Consequences:

- The current JSON file remains prototype debt.
- A ledger-style representation is preferred for bankroll movements and bet states.
- PostgreSQL is a likely candidate on Render, but the database and data-access tooling are not yet selected.

Implementation note (2026-08-28): ADR-024 through ADR-030 resolve the database, ORM, migrations, ledger, money, idempotency, and authentication choices anticipated here.

## ADR-009 — Preserve immutable decision-time context

- Date: 2026-08-28
- Status: Accepted

Official bets and recommendations must preserve the information available at decision time, including exact event/market identity, line, offered price, probability sources, EV, stake logic, bankroll, versions, approval, and timestamps.

Consequences:

- Later model outputs must not overwrite historical predictions.
- Entry and closing observations should be stored as reproducible snapshots.
- Analytics must trace back to immutable source records.

## ADR-010 — Learning is offline, versioned, and evidence-based

- Date: 2026-08-28
- Status: Accepted

The current system does not learn. V2 learning should use calibration, Brier score, log loss, CLV, ROI, drawdown, segmentation, sample size, and out-of-sample evaluation. Recent wins or small samples must not automatically increase confidence, weights, or stakes.

Consequences:

- Model and policy changes require versioning and reproducible evaluation.
- Silent online mutation of production logic is not allowed.
- Promotion and rollback criteria must be defined before automated model updates.
- Historical prediction snapshots, closing prices, outcomes, calibration, CLV, drawdown, and segmented results form the evidence base.
- Versioned portfolio-risk policy may respond to equity, exposure, drawdown, uncertainty, and validated model performance; short streaks alone may not trigger changes.

## ADR-011 — Initial bankroll is configuration, not a product invariant

- Date: Historical; recorded 2026-08-28
- Status: Accepted

The original test bankroll was approximately $200, and the current code defaults to `$200.00`. This value is historical test context and runtime configuration, not a universal staking assumption.

Consequences:

- Calculations should operate on explicit portfolio state.
- Tests may use fixed bankroll fixtures but should not embed `$200` as a domain rule.

## ADR-012 — League development priority is NCAAF, NFL, then NBA

- Date: 2026-08-28
- Status: Accepted

Immediate development priority is NCAAF/College Football, followed by NFL and NBA. MLB, NHL, and WNBA are secondary. The prototype's NCAAB support is college basketball and must not be confused with NCAAF.

Consequences:

- NCAAF becomes the first new first-class league and predictive-model track.
- League identifiers, provider mappings, datasets, features, and evaluation remain explicit.
- Shared platform components should not erase sport-specific modeling requirements.

## ADR-013 — The product combines market, model, research, and portfolio evidence

- Date: 2026-08-28
- Status: Accepted

The ultimate product is a quantitative sports-wagering portfolio manager, not merely a market-consensus line scanner. It combines market pricing, sport-specific predictive models, structured sports/statistical data, traceable injury/news/research signals, and portfolio-risk controls.

Consequences:

- Market consensus is a baseline and benchmark, not necessarily the final estimate.
- Final fair probability must expose its component probabilities and versioned policy.
- Sport/statistical and research-data ingestion are architectural components, not informal prompt context.

## ADR-014 — Top N is a maximum, never a quota

- Date: 2026-08-28
- Status: Accepted

The recommendation interface returns up to a configurable Top N qualified opportunities per selected league, with 10 as the normal display maximum. Qualification standards do not change to fill the display.

Consequences:

- Ranking and Top N truncation occur only after data, EV, uncertainty, and portfolio-risk qualification.
- Fewer than Top N, including zero, is correct behavior.
- Duplicate or marginal opportunities must not be manufactured to meet a count.

## ADR-015 — Recommendations expose the complete decision basis

- Date: 2026-08-28
- Status: Accepted

Every recommendation preserves and exposes the best executable sportsbook price, implied probability, consensus probability, proprietary model probability when available, final fair probability, edge, EV, uncertainty/confidence, recommended stake, portfolio-equity percentage, and a human-readable research explanation.

Consequences:

- Probability sources and pricing/model/risk versions remain separately identifiable.
- Explanations link to traceable structured research signals.
- A missing proprietary model is represented explicitly, not fabricated or relabeled from consensus.

## ADR-016 — Stakes scale with equity under versioned conservative risk policy

- Date: 2026-08-28
- Status: Accepted

The bankroll objective is long-term risk-adjusted growth rather than a fixed target. Position sizes scale with current portfolio equity under a conservative fractional-Kelly/risk-budget framework rather than static dollar bets. A unit is a display abstraction tied to current bankroll/equity.

Consequences:

- Store stake dollars, equity percentage, displayed units, equity basis, and policy version at recommendation time.
- Full Kelly remains prohibited.
- Exact unit fraction, equity definition, Kelly multiplier, and exposure budgets require empirical validation.

## ADR-017 — Research signals are traceable; LLM adjustments are not arbitrary

- Date: 2026-08-28
- Status: Accepted

News, injuries, and research are ingested as sourced, timestamped, structured signals. An LLM may discover, extract, summarize, and explain them but may not apply undocumented arbitrary probability adjustments.

Consequences:

- Every probability-affecting signal has provenance and enters through a versioned feature or policy.
- Conflicts, freshness, and extraction confidence remain visible.
- Human-readable explanations do not substitute for reproducible model inputs.

## ADR-018 — Sport-specific modeling starts after the baseline engine

- Date: 2026-08-28
- Status: Accepted

Sport-specific modeling is not deferred until the final experimentation phase. After the market-pricing baseline is reproducible, an NCAAF predictive-model track begins, followed by NFL and NBA.

Consequences:

- NCAAF models are evaluated against consensus with chronological out-of-sample tests.
- Historical variables earn weight only through reproducible evidence.
- A model that does not beat or complement the baseline is not forced into final fair probability.

## ADR-019 — Game markets precede expanded markets and player props

- Date: 2026-08-28
- Status: Accepted

NCAAF and NFL initially prioritize full-game moneyline, spreads, and totals. Alternate spreads/totals and half/quarter markets follow core-pipeline validation. Player props are later because they require player-level projections and more extensive data/modeling. NBA ultimately supports game markets and player props.

Consequences:

- Market expansion requires explicit identity, settlement, data, and test support.
- NBA player availability, minutes, usage, pace, rest, lineup, and matchup inputs are important model requirements.
- No prop recommendation is produced without a reproducible player projection.

## ADR-020 — Opening-weekend NCAAF baseline is an explicit milestone

- Date: 2026-08-28
- Status: Accepted

The project should capture an opening-weekend NCAAF paper-trading baseline with odds, consensus calculations, qualified recommendations, paper stakes, closing prices, and outcomes even if the first proprietary model is not production-ready.

Consequences:

- Consensus may serve as the explicitly labeled final fair source for this milestone.
- Missing proprietary probability remains null/not available.
- The milestone exercises the complete observable lifecycle and creates a benchmark dataset for later NCAAF models.

## ADR-021 — `/odds` date semantics use UTC filtering

- Date: 2026-08-28
- Status: Accepted

The current The Odds API integration is a current/upcoming feed, not a historical query. The required `/odds` request date is interpreted as a UTC calendar date, and the backend retains only provider games whose timezone-aware `commence_time` falls on that UTC date.

Consequences:

- Responses expose `date_timezone: "UTC"`.
- Naive, missing, or invalid provider timestamps are excluded because their calendar date is ambiguous.
- Past dates normally produce no games and must not be described as historical-odds retrieval.
- A future user-local or event-local date convention requires a superseding decision and an explicit timezone contract.

## ADR-022 — Python 3.12 and pinned direct dependencies form the development baseline

- Date: 2026-08-28
- Status: Accepted

Python 3.12.x is the supported local and CI runtime. Runtime and development requirements use exact direct dependency pins, and CI runs Ruff, mypy, and pytest without live provider credentials.

Consequences:

- Runtime changes should remain compatible with Python 3.12 until a superseding decision.
- Dependency updates are explicit reviewed changes rather than implicit floating upgrades.
- Deterministic tests and mocked provider boundaries are required for critical behavior.

## ADR-023 — Modular boundaries precede V2 behavior

- Date: 2026-08-28
- Status: Accepted

Phase 1 separates the existing prototype into API, schema, domain, provider, service, persistence, configuration, UTC-time, and logging boundaries without introducing pricing, recommendation, predictive-model, or database behavior. The root `main.py` remains a compatibility export for the deployed `uvicorn main:app` command.

Consequences:

- FastAPI routes validate requests, delegate to services, map known service errors, and do not perform provider HTTP or JSON-file operations.
- The Odds API is one adapter behind a provider-neutral protocol and emits transitional `MarketGame`/`MarketOffer` records. These are not the final normalized V2 market model.
- Portfolio services depend on a repository protocol; JSON remains the configured compatibility implementation until Phase 2 selects and migrates to transactional storage.
- Application construction accepts deterministic settings, fake providers, in-memory persistence, and a clock for isolated tests.
- UTC timestamp creation is centralized, and responses carry a validated or generated `X-Request-ID` that is included in lightweight structured logs.
- Provider exception details, credential-bearing URLs, and API keys are never logged or returned.
- Phase 1 intentionally preserves caller-supplied model metadata and payout semantics; modularization does not make those values calculated or trustworthy.

## Open decisions

Create separate ADR entries when these are resolved:

- future vig-removal alternatives and evidence-backed consensus weighting beyond the accepted Phase 4 baseline;
- final fair-probability selection/blending and proprietary-model promotion gates;
- NCAAF structured-data providers, feature set, model family, and evaluation windows;
- NFL/NBA data providers and league-specific model scope;
- injury/news/research sources, provenance schema, conflict handling, and signal freshness;
- uncertainty representation, qualification thresholds, ranking, Top N tie-breaking, and per-league behavior;
- portfolio-equity definition, unit display policy, fractional-Kelly multiplier, and exposure caps;
- primary CLV definition and closing benchmark;
- cross-provider fuzzy matching, conflict review workflow, and mapping-resolution authority;
- scheduler/background-job technology;
- API versioning and migration policy;
- exact calendar/scope and operational readiness criteria for the NCAAF opening-weekend milestone;
- player-prop expansion gates and required projection quality;
- parlay day/league scope and eligible leg counts;
- parlay minimum EV, executable-price freshness, independence tests, and correlation policy;
- validated same-game joint-probability method and production-readiness gate;
- parlay Kelly multiplier, stake cap, sleeve exposure budget, and disablement criteria; and
- parlay-specific CLV/calibration definitions and evidence thresholds.

## ADR-024 — PostgreSQL is the production relational database

- Date: 2026-08-28
- Status: Accepted

Production portfolio state uses PostgreSQL through `DATABASE_URL`. SQLite is permitted only for deterministic tests and disposable local migration validation. The application contains no managed-vendor-specific database logic.

Consequences: deployment requires a migrated PostgreSQL database; Render remains a supported host but its database product is not required. PostgreSQL row locks, constraints, and transactions are the production concurrency model.

## ADR-025 — SQLAlchemy 2.x is the data-access layer

- Date: 2026-08-28
- Status: Accepted

Modern SQLAlchemy sessions and typed declarative models implement relational persistence behind the existing repository boundary. Routes do not manipulate ORM entities or SQL.

Consequences: `SqlAlchemyPortfolioRepository` owns aggregate transaction boundaries. Tests may inject a SQL repository backed by ephemeral SQLite.

## ADR-026 — Alembic owns schema evolution

- Date: 2026-08-28
- Status: Accepted

Alembic revisions are the only production schema-creation/evolution mechanism. Application startup does not call `Base.metadata.create_all()`.

Consequences: deploys run `alembic upgrade head`; downgrades and generated revisions must be reviewed and tested. Test fixtures may use metadata creation for isolated schemas.

## ADR-027 — Bankroll accounting is ledger-based

- Date: 2026-08-28
- Status: Accepted

Every bankroll mutation appends an auditable signed ledger entry. Cash is derived by summing ledger amounts; historical entries are immutable under normal ORM operations. Open stake is reserved exposure and not a realized loss.

Consequences: initial funding, stake reservation, settlement, adjustment, and future void/refund entries have explicit types and references. Equity is currently cash plus open reserved stake. Corrections use adjustments rather than historical edits.

## ADR-028 — Money uses Decimal and NUMERIC with cents rounding

- Date: 2026-08-28
- Status: Accepted

Python `Decimal` and SQL `NUMERIC(18,2)` are authoritative for money. Inputs quantize to cents using `ROUND_HALF_UP`; JSON numbers are a compatibility serialization only.

Consequences: a value of `10.005` becomes `10.01`. Financial tests assert exact Decimal arithmetic and ledger reconciliation. Multi-currency conversion remains out of scope even though portfolios preserve an ISO currency code.

## ADR-029 — Mutation idempotency is persistent and transactional

- Date: 2026-08-28
- Status: Accepted

`POST /bets` and `POST /bet-result` accept `Idempotency-Key`. Records are scoped to owner and endpoint and commit in the same transaction as the mutation.

Consequences: the same key/payload returns the original successful response; different payload returns 409. Missing keys remain allowed for compatibility and provide no replay protection. Failed operations leave no committed idempotency record.

## ADR-030 — Authentication uses a replaceable API-key principal boundary

- Date: 2026-08-28
- Status: Accepted

The private paper-trading API resolves `X-API-Key` to an application `Principal`; portfolios reference owners and reject cross-owner access. Health remains public.

Consequences: `APP_API_KEY`, `APP_OWNER_ID`, and `APP_OWNER_NAME` configure the current single owner. This is intentionally small and replaceable by a proper identity provider; it is not a broad multi-user authorization system.

## ADR-031 — Preserve Render backend hosting

- Date: 2026-08-28
- Status: Accepted

The FastAPI backend remains on Render and retains `uvicorn main:app`. Phase 2 changes persistence, not hosting.

Consequences: configure `DATABASE_URL`, API authentication, and provider credentials in Render; apply Alembic migrations before starting the service. A persistent disk is not required for primary relational state. No Render-specific database URL, hostname, username, or password is committed or embedded in application code.

## ADR-032 — Parlay of the Day is an optional later research sleeve

- Date: 2026-08-28
- Status: Accepted

After the core straight-bet pricing, predictive-model, portfolio-risk, and evaluation pipeline is proven, the platform may return at most one featured Parlay of the Day per day/league scope. Zero is valid. The feature is subordinate to the core ranked straight-bet portfolio and must not alter its qualification standards or long-term risk-adjusted bankroll-growth objective.

Consequences:

- Every component leg must independently qualify; combinations are never manufactured to satisfy a display feature.
- Recommendation requires an executable sportsbook parlay payout and a versioned modeled joint fair probability.
- Marginal probabilities are multiplied only when independence is defensible and documented.
- Same-game or otherwise correlated combinations require validated correlation modeling, simulation, or another reproducible joint-probability method before production-quality use.
- Early research prefers cross-event combinations with more defensible independence assumptions.
- Parlays use a separate conservative risk sleeve, generally lower stake caps, and the portfolio's aggregate exposure/correlation controls.
- Performance is segmented from straight bets and includes entry EV, stake, outcome, realized P&L, ROI/yield, hit rate, sample size, and later CLV/calibration where meaningful.
- The sleeve must be reducible or disableable when reproducible out-of-sample evidence shows that it damages risk-adjusted performance.
- Exact leg counts, EV thresholds, joint-probability methods, Kelly multipliers, caps, and correlation/evidence policies remain unresolved pending empirical validation.

## ADR-033 — Persist raw and normalized market snapshots together

- Date: 2026-08-28
- Status: Accepted

Each successful market fetch persists the exact raw provider JSON and normalized events/books/observations in one repository transaction. Sanitized request parameters, provider/request times, response/quota metadata, warnings, status, and raw array indexes preserve provenance. PostgreSQL stores JSON documents as JSONB; SQLite remains the deterministic test substitute.

Consequences:

- Every normalized price has a required snapshot foreign key and raw source path.
- Raw and normalized rows commit or roll back together.
- API credentials and credential-bearing URLs are excluded from persisted request/source metadata.
- Raw snapshots are retained even when some provider rows are malformed; ingestion status and structured warnings expose partial normalization.

## ADR-034 — Canonical market identity includes period, side, and exact point

- Date: 2026-08-28
- Status: Accepted

An equivalent observation is identified by canonical event, canonical sportsbook, market type, period, selection side, and exact point key. Initial markets are full-game moneyline, spread, and total only. Moneyline has no point; spread/total point uses `NUMERIC(10,3)`.

Consequences:

- Over 52.5 cannot be combined with Over 53.5, and home -3.5 cannot be combined with home -4.0.
- Future half/quarter markets use the existing period dimension rather than overloading full-game identity.
- Phase 4 must group only complete, truly equivalent identities.

## ADR-035 — Provider event IDs are deterministic matches; ambiguity is never silently merged

- Date: 2026-08-28
- Status: Accepted

Within a provider sport, an exact provider event ID plus consistent league, home/away teams, and UTC start reuses a canonical event. Conflicting identity produces a separate candidate and marks candidates as conflicts. Missing provider IDs produce review-required events rather than display-string matching.

Consequences:

- Canonical event UUID—not a display string—is the long-term event identity.
- Mappings preserve confidence, review status, method, and provenance.
- Observations copy match-review status so automated pricing/recommendation code can exclude uncertainty.
- Cross-provider fuzzy matching and human conflict resolution remain unresolved future work.

## ADR-036 — Freshness is explicit, versioned, and configurable

- Date: 2026-08-28
- Status: Accepted

Freshness policy `market-freshness-v1` records provider update time when available, effective observation time, ingestion time, age seconds, configured stale threshold, and stale result. The initial threshold is 120 seconds and is configurable through `MARKET_FRESHNESS_SECONDS`.

Consequences:

- The initial threshold is an operational starting point, not a permanent claim about market quality.
- Historical stale determinations remain reproducible because policy version and threshold are stored per observation.
- Phase 4 must exclude or explicitly handle stale prices.

## ADR-037 — Provider retry and cache behavior is bounded

- Date: 2026-08-28
- Status: Accepted

The Odds API adapter uses configurable timeout, bounded retry count, exponential backoff, and a short process-local successful-response cache. Only connection/timeouts, HTTP 408/425/429, and 5xx retry; authentication and other client errors do not. Usage headers and low-quota warnings are captured structurally.

Consequences:

- There is no uncontrolled retry loop and provider failures remain visible to callers.
- Cached payloads retain original provider retrieval time while each ingestion records its own request/ingestion time.
- Cache is an API-safety optimization, not a durable distributed cache or scheduler.
- Credentials remain confined to transport parameters and never enter stored request metadata or logs.

## ADR-038 — Phase 3 stores closing-price-ready history but does not define CLV

- Date: 2026-08-28
- Status: Accepted

Multiple immutable observations retain exact market identity, source, provider/observation/ingestion times, and scheduled event start. This supports later selection of first observed, latest pre-start, entry-time, and closing observations.

Consequences:

- Phase 3 does not label an official close, select benchmark books, or calculate CLV.
- A later decision must define closing cutoff, source/book set, stale/ambiguous handling, and CLV formula.
- Line movement remains observable without overwriting earlier prices.

## ADR-039 — Initial vig removal uses proportional normalization

- Date: 2026-08-28
- Status: Accepted

Phase 4 uses `proportional-v1` for a complete coherent two-outcome market at one book. Each raw implied probability is divided by their sum. Normalized probabilities use Decimal arithmetic, 12 decimal places with `ROUND_HALF_EVEN`, and a residual final outcome so the pair sums exactly to one.

Consequences:

- Each calculation exposes both raw implied probabilities, their sum, overround, normalized probabilities, source observation IDs, and version.
- Incomplete, malformed, or inconsistent pairs do not contribute to consensus.
- This transparent baseline may be compared with power, additive, Shin, or other methods later, but historical outputs retain their original version.
- No claim is made that proportional removal is universally optimal.

## ADR-040 — Initial multi-book consensus is the unweighted median

- Date: 2026-08-28
- Status: Accepted

`unweighted-median-v1` takes the median of eligible sportsbook no-vig probabilities for one exact selection. Eligibility requires the same canonical event, league, market, period, selection side, and exact line; supported active books; a complete pair; current matched event identity; and freshness at the calculation cutoff. The minimum book count is configurable and defaults to two.

Consequences:

- Median aggregation is transparent and resistant to one extreme contributor.
- No unsupported “sharp book” or liquidity weights are invented.
- Every contributing book and both source observations remain visible.
- Book-quality weights may be added only through a new version supported by reproducible evidence.
- Consensus is the market baseline and fair-probability source for Phase 4, never a proprietary model probability.

## ADR-041 — Outliers are surfaced and excessive dispersion rejects the market

- Date: 2026-08-28
- Status: Accepted

Phase 4 reports consensus dispersion as the range of contributing no-vig probabilities. A book is a material outlier when its absolute probability deviation from the median exceeds a configurable threshold, initially 0.03. The opportunity carries a warning; if total dispersion exceeds the configurable initial maximum of 0.08, the exact market is rejected.

Consequences:

- An outlier is not silently averaged away or automatically treated as informationally superior.
- The median can remain usable when a flagged contributor exists below the rejection limit.
- Thresholds are conservative operational starting points, not empirical permanence; changes require a new qualification/policy version and replay evaluation.
- Best executable price remains a separate observation and may differ from the books closest to consensus.

## ADR-042 — Phase 4 qualification is sparse, transient, and push-conservative

- Date: 2026-08-28
- Status: Accepted

`baseline-qualification-v1` uses configurable minimum EV, probability edge, book count, freshness, event-review status, exact pairing, supported-book, and maximum-dispersion gates. Qualified opportunities rank deterministically by EV and data quality, then apply Top N independently per league; 10 is the default and zero is valid. Outputs remain transient and reproducible from Phase 3 observations until a later official recommendation/approval boundary is implemented.

Integer spread and total observations remain stored and replayable but are excluded from Phase 4 EV qualification because push probability is not modeled. Half-point spreads/totals may use the binary EV formula. This exclusion is a conservative Phase 4 limitation, not a permanent product decision.

Consequences:

- Thresholds never relax to fill Top N.
- Every output contains the best executable observation, consensus inputs, edge, EV, uncertainty/data-quality indicators, all versions, and observation/snapshot provenance.
- Proprietary probability is explicitly null and fair-probability source is `market_consensus`.
- No stake, Kelly calculation, risk budget, official recommendation mutation, or autonomous execution occurs.
- A later push-aware policy must explicitly model `p_win`, `p_loss`, and `p_push` before qualifying integer lines.

## ADR-043 — Historical pricing replay uses dual time boundaries and latest market state

- Date: 2026-08-28
- Status: Accepted

Pricing replay includes an observation only when both its provider/effective observation time and its database ingestion time are at or before the timezone-aware cutoff. It then selects the latest snapshot state per canonical event, sportsbook, market type, and period before applying the same freshness, ambiguity, pairing, consensus, EV, and qualification rules as current analysis.

Consequences:

- An observation carrying an old provider timestamp but ingested after the cutoff cannot leak backward.
- A later line move cannot appear in an earlier replay, and the superseded line is not treated as still executable after the move.
- The replay cutoff is the deterministic calculation timestamp.
- Pricing calculations are transient rather than stored redundantly; source observations plus policy versions reproduce them.
- Pricing replay is not an outcome backtest or portfolio simulation. Results, closing prices, and stakes are not fabricated when unavailable.

## ADR-044 — Pricing reads use scalar projections and SQL-ranked latest states

- Date: 2026-08-28
- Status: Accepted

The opportunity/replay repository selects only the scalar event, sportsbook, observation, and snapshot-timestamp fields consumed by Phase 4. It must not select or materialize `MarketSnapshot` JSON documents. SQL window functions deterministically choose one representative row per snapshot and then the latest eligible snapshot state per canonical event, sportsbook, market type, and period before returning its complete selection rows.

Consequences:

- Phase 3 raw snapshots and metadata remain immutable and available for audit, re-normalization, and provenance, but their size cannot multiply across Phase 4 observation rows.
- League, market, UTC event-date, observation-time, and ingestion-time predicates bound candidates before ranking; event-start eligibility remains in the shared pricing domain to preserve rejection semantics.
- The ordering preserves replay semantics: observation time, snapshot request time, ingestion time, and stable UUID tie-breakers prevent future leakage and make repeated runs deterministic.
- Result cardinality scales with the latest event/book/market state, not the number or raw-payload size of historical snapshots.
- Provider-neutral pricing DTOs are constructed from mappings; no ORM snapshot, event, book, or observation entity is materialized on this read path.
- Safe request diagnostics report only counts and elapsed times. Raw provider payloads, credentials, and URLs are never logged.
- Pricing math, policies, response contracts, persistence schema, and historical source observations are unchanged.

## ADR-045 — Phase 5 uses a chronological model tournament

- Date: 2026-08-28
- Status: Accepted

No algorithm is designated “the NCAAF model” before empirical comparison. Phase 5B must test a simple opponent-adjusted baseline, Elo/power ratings, Ridge/Elastic Net, a bounded and equal-budget screen of XGBoost/LightGBM/CatBoost, and justified component-score, hierarchical, distributional, or ensemble challengers. Primary evidence uses chronological walk-forward evaluation; random splitting is not acceptable as the primary protocol.

Consequences:

- Complexity must beat naive, interpretable, and same-horizon market benchmarks on untouched forward data.
- Hyperparameters, transforms, calibrators and ensembles are fitted without the locked test season.
- Failed candidates remain recorded; a negative result does not force a proprietary model into production.
- Exact tree family, hierarchical specification, final algorithm and numeric promotion thresholds remain unresolved research outcomes.

## ADR-046 — Primary NCAAF targets are margin and total predictive distributions

- Date: 2026-08-28
- Status: Accepted

Phase 5B initially models `home_points - away_points` and `home_points + away_points` as predictive distributions. These distributions must support coherent moneyline, spread, total and integer-line push probabilities. Direct home/away component scores and direct binary win probability are challengers/diagnostics, not mandatory production components.

Consequences:

- Point estimates alone cannot qualify a model for probability use.
- Normal residuals are only a benchmark; Student-t, chronological empirical residual, heteroskedastic, quantile/distributional and joint-score methods remain experiments.
- Integer score-lattice discretization is the initial method to investigate for nonzero push mass.
- Phase 4's integer-line exclusion remains unchanged until a push-capable distribution is implemented, calibrated and promoted.

## ADR-047 — Model facts and features require point-in-time provenance

- Date: 2026-08-28
- Status: Accepted

Every time-sensitive sports/model input must preserve effective, observed and ingested time where applicable, source, provenance, schema/transformation version and reconstructed-versus-contemporaneous status. A historical feature row may include only data available at its declared prediction cutoff. Corrections supersede rather than overwrite source history.

Consequences:

- Closing lines, final injuries, realized weather, postgame corrections, target-game statistics and future opponent results cannot leak into an earlier row.
- Retrospectively recomputed provider metrics are not assumed point-in-time merely because they are returned for an old season.
- PostgreSQL is proposed for canonical identities, source indexes and manifests; immutable partitioned files are proposed for bulky PBP, feature matrices and OOF artifacts.
- Reconstructed data is separately labeled and cannot prove strict replay fidelity without a documented availability rule.

## ADR-048 — Independent and market-residual models precede arbitrary blending

- Date: 2026-08-28
- Status: Accepted

Phase 5B must preserve an independent football model and test a fixed-horizon market-residual model; a direct market-as-feature model is a challenger. Market consensus remains the baseline and may remain the final fair probability. Any blend must be fitted from chronological out-of-fold predictions with all components/versioning visible.

Consequences:

- No fixed 50/50 or hand-authored market/model weight is allowed.
- Exact historical market snapshots at the prediction horizon are required for residual, market-feature and blending claims.
- Market, proprietary and final probabilities remain separate fields with an explicit final-source/blend policy.
- The best executable price is not an independent model feature or the sole fair-probability source.

## ADR-049 — Model training is offline with immutable artifacts and explicit promotion

- Date: 2026-08-28
- Status: Accepted

Initial model training, tuning, calibration and bulk evaluation run outside synchronous FastAPI requests. Model, feature, calibration, dataset and run metadata are registered; artifacts are immutable and content-hashed. Lifecycle is `experimental -> candidate -> shadow -> production -> retired`, with recorded transitions.

Consequences:

- A future FastAPI inference path may load one approved small artifact after schema/hash and golden-fixture checks; heavier scheduled work may later justify a worker.
- No artifact silently replaces another, and historical predictions retain their producing versions.
- Untrusted arbitrary pickle loading is prohibited; transparent or model-native safe formats are preferred.
- Initial storage is now resolved as PostgreSQL identity/manifest/registry metadata plus immutable Parquet and model-native artifacts; exact registry schema and any evidence-driven future worker choice remain Phase 5B implementation decisions.

## ADR-050 — CFBD is the MVP sports-data candidate; historical odds are a separate gate

- Date: 2026-08-28
- Status: Accepted for MVP planning; credentialed terms/coverage execution pending

CollegeFootballData is the recommended first source for schedules/results, PBP, teams/venues, coaches, recruiting, returning production and transfers. SportsDataverse/cfbfastR is a bootstrap and cross-check subject to upstream-use review. Existing Odds API snapshots support forward evaluation; a bounded paid historical-odds audit is required before market-relative backtest claims.

Consequences:

- Phase 5B is not blocked on a large commercial statistics bundle, historical injuries or complete weather.
- The first paid-data priority is exact fixed-horizon historical odds, after a small coverage audit.
- Precomputed retrospective metrics must be audited and may not substitute for own as-of rolling features.
- Injuries, archived forecasts and premium participation feeds enter later only if coverage and ablation evidence justify cost.
- Phase 5B-0 measured 1,819,153 public PBP rows and 98.35% FBS-participant game coverage for 2014–2025, but found material 2021–2022 gaps and 2017 wall-clock missingness. Missingness must remain explicit.
- Start CFBD on the free tier with immutable caching and bulk/year requests. The credentialed endpoint audit remains an acquisition gate because no key was available during Phase 5B-0.

## ADR-051 — Promotion requires locked chronological and shadow evidence

- Date: 2026-08-28
- Status: Accepted; numeric tolerances unresolved

A proprietary candidate cannot affect paper recommendations based on in-sample fit, a random split, ROI, hit rate or a short streak. Proposed evidence includes reproducible manifests, automated leakage checks, calibration, paired proper-score comparison with same-horizon consensus, stability across predeclared segments, a locked forward season and a prospective shadow season. At least two genuinely out-of-sample seasons are the initial requirement.

Consequences:

- Market consensus remains production fair probability while candidates are experimental/candidate/shadow.
- Exact minimum sample, practical Brier/log-loss improvement, calibration tolerance and acceptable segment degradation must be set after development variance is measured and frozen before opening the final holdout.
- A model that fails to beat or complement consensus remains experimental; there is no forced promotion or blend.

## ADR-052 — Operational morning and research horizons remain distinct

- Date: 2026-08-29
- Status: Accepted

The first practical recommendation workflow is one game-day-morning run before the first scheduled NCAAF kickoff of the day. A bounded historical-odds audit compares a fixed 09:00 America/New_York convention with first kickoff minus three hours before freezing the operational rule. The 60-minute and 24-hour cutoffs remain separate historical research horizons.

Consequences:

- Morning, 60-minute, and 24-hour results are never combined, substituted, or imputed across horizons.
- Top-N output remains a ceiling at the single daily operational run; no additional run manufactures opportunities.
- The exact morning convention is unresolved until the predeclared coverage audit reports consistently reconstructable snapshots.
- Opening and close may be evaluation benchmarks but are not substitutes for an unavailable operational horizon.

## ADR-053 — The 2025 season is locked and 2026 is prospective shadow evidence

- Date: 2026-08-29
- Status: Accepted

Use 2014–2024 only for development/model/hyperparameter decisions. Evaluate 2025 exactly once after the candidate, calibration, exclusions, and practical-effect rule are frozen. Use 2026 as prospective shadow evidence.

Consequences:

- Phase 5B-0 used only score-field non-nullness for coverage eligibility and inspected 2025 coverage/null metadata; it never printed, compared, or used score magnitudes or model performance. The holdout remains uncontaminated.
- If any future work materially consults 2025 outcomes before freezing, it must disclose the contamination and replace the holdout structure rather than rationalize reuse.
- The operational access-seal mechanism and whether more than one prospective shadow season is required remain unresolved.

## ADR-054 — Phase 5B uses lean offline storage and staged source acquisition

- Date: 2026-08-29
- Status: Accepted

Initial training and bulk transforms run offline. PostgreSQL stores canonical identities, time-sensitive indexes, manifests, registry metadata, and prediction provenance. Immutable Parquet or equivalent files store bulky research facts/matrices/OOF predictions, and safe model-native formats store trained artifacts. CFBD is free-tier-first and cached immutably. Only the frozen 76-request/2,280-credit historical-odds audit is authorized before a larger corpus decision.

Consequences:

- Do not add Spark, Databricks, distributed ML infrastructure, or a separate inference service without measured evidence.
- Injuries and weather remain required future audits/ablations but do not block the first statistical baseline.
- Backfilled archive source time and actual local ingestion time remain distinct; do not falsify ingestion time to simulate contemporaneous capture.
- Full historical odds acquisition is conditional on predeclared sample tolerances, not enthusiasm after inspecting results.

