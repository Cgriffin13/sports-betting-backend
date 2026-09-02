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
- Status: Accepted; CFBD credentialed coverage completed, historical-odds gate pending

CollegeFootballData is the recommended first source for schedules/results, PBP, teams/venues, coaches, recruiting, returning production and transfers. SportsDataverse/cfbfastR is a bootstrap and cross-check subject to upstream-use review. Existing Odds API snapshots support forward evaluation; a bounded paid historical-odds audit is required before market-relative backtest claims.

Consequences:

- Phase 5B is not blocked on a large commercial statistics bundle, historical injuries or complete weather.
- The first paid-data priority is exact fixed-horizon historical odds, after a small coverage audit.
- Precomputed retrospective metrics must be audited and may not substitute for own as-of rolling features.
- Injuries, archived forecasts and premium participation feeds enter later only if coverage and ablation evidence justify cost.
- Phase 5B-0 measured 1,819,153 public PBP rows and 98.35% FBS-participant game coverage for 2014–2025, but found material 2021–2022 gaps and 2017 wall-clock missingness. Missingness must remain explicit.
- CFBD started on the free tier with immutable caching and bulk/year requests. Phase 5B-1 completed the credentialed endpoint audit and 2014–2024 corpus within 416 billable calls; the separate historical-odds audit remains an acquisition gate.

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
- Implementation note (2026-08-30): ADR-081 resolves the morning convention as first scheduled kickoff minus three hours after the predeclared coverage audit tied on aggregate coverage.
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

## ADR-055 — CFBD source versions use credential-free request identity and immutable content hashes

- Date: 2026-08-29
- Status: Accepted and implemented

Canonical request identity includes provider, endpoint, and sorted non-secret parameters. Credentials exist only in the bearer header. `provider + request hash + content hash` identifies one immutable source version; changed content appends a manifest linked to the prior version, while identical content reuses the prior manifest and facts.

Consequences:

- Historical responses retrieved now are labeled `reconstructed` with their actual retrieval time.
- Cache hits may re-run idempotent normalization without another provider call, allowing interrupted runs to resume safely.
- Content-addressed orphan files after a rolled-back relational transaction are harmless and reusable; a future garbage collector may remove unreferenced artifacts.

## ADR-056 — Canonical football identity extends existing event identity through exact provider IDs

- Date: 2026-08-29
- Status: Accepted and implemented

Programs and venues receive stable UUIDs and provider mapping rows. Program aliases and conference/classification membership are effective-season records. CFBD game IDs use the existing `ProviderEventMapping` boundary and add nullable program, venue, season, week, season-type, neutral-site, and schedule-provenance fields to `CanonicalEvent`.

Consequences:

- Display strings never merge programs or events.
- Renames and conference/classification changes do not create a new program.
- Ambiguous or unresolved cross-provider mappings remain reviewable and model-ineligible.
- Existing live odds events are not destructively rewritten.

## ADR-057 — Raw CFBD artifacts use lossless canonical JSON gzip; PostgreSQL stores indexes and targets

- Date: 2026-08-29
- Status: Accepted and implemented for source ingestion

The raw research cache uses content-addressed `raw-json-gzip-v1` files containing the provider's exact response bytes and partitioned by provider/league/season/week/product. PostgreSQL stores manifests, artifact indexes, canonical identities, game targets, exclusions, and existing-event links. This satisfies the approved “Parquet or equivalently lean immutable format” direction without adding a large columnar dependency to the Render web service.

Consequences:

- The measured 1.22 GB response corpus occupies about 92.6 MB losslessly.
- Later feature matrices may use Parquet without changing raw-source provenance.
- Multi-million-row PBP is not stored as ORM records.
- Spark, Databricks, and a separate inference service remain unjustified.

## ADR-058 — Development source commands fail closed at the locked 2025 holdout

- Date: 2026-08-29
- Status: Accepted and implemented

Research ingestion and corpus validation default to 2014–2024 and reject 2025+ unless an explicit `--allow-holdout-access` flag is provided. Phase 5B-1 did not request, inspect, or report 2025 score magnitudes.

Consequences:

- Ordinary builders cannot silently include locked outcomes.
- The flag is authorization for a future frozen holdout evaluation, not permission for iterative development.
- 2026 remains prospective shadow evidence; no model was trained in Phase 5B-1.

## ADR-059 — Phase 5B-2 uses immutable normalized Parquet and offline feature matrices

- Date: 2026-08-29
- Status: Accepted and implemented

Phase 5B-1 raw JSON gzip remains the lossless source record. Phase 5B-2 derives content-addressed, season-partitioned normalized Parquet facts and horizon-specific feature matrices outside PostgreSQL and Git. PostgreSQL remains authoritative for canonical identities, source manifests, and indexes; no Phase 5B-2 relational schema was necessary.

Consequences:

- Every artifact records source manifests/hashes, transformation/schema version, row count, schema hash, content hash, and immutable path.
- Column projection and season-bounded transforms avoid materializing the 1.7-million-play corpus as ORM objects or one giant Python record list.
- Research-only PyArrow/psutil dependencies are isolated from the Render web requirements.
- Identical source versions and configuration must reproduce row order, schema, values, and dataset hash.

## ADR-060 — Reconstructed CFBD postgame facts become available at kickoff plus 24 hours in v1

- Date: 2026-08-29
- Status: Accepted and implemented

Under `cfbd-reconstructed-kickoff-plus-24h-v1`, reconstructed game, PBP, drive, and team-stat facts are ineligible until at least 24 hours after scheduled kickoff. Occurrence/effective time, reconstructed availability, and actual local ingestion time remain separate; ingestion is never backdated.

Consequences:

- A target game cannot enter its own pregame features, and later corrections cannot masquerade as contemporaneously known.
- The rule is deliberately conservative and source-specific, not a claim about CFBD's historical publication timestamp.
- A stricter future rule requires a new version and dataset; it may not silently mutate v1.

## ADR-061 — Initial opponent adjustment and early-season priors are transparent research features

- Date: 2026-08-29
- Status: Accepted and implemented as candidate inputs

Opponent-adjusted v1 metrics residualize a team's prior-five raw performance against each prior opponent's opposite-unit strength using only facts available at the target row's historical `as_of`, then restore the prior-only population mean. Early-season blend v1 weights current evidence by `n / (n + 3)` and prior evidence by `3 / (n + 3)`, using up to three prior seasons and a prior-only population fallback.

Consequences:

- End-of-season opponent ratings and future opponent games cannot leak backward.
- Raw, prior, blended, and adjusted values remain separate with sample/coverage indicators; missing is never silently zero.
- These formulas are frozen inputs for Phase 5B-3 comparisons, not selected model coefficients or evidence of predictive value.
- Recruiting, transfers, returning production, quarterback, coaching, injuries, and weather remain Phase 5B-6/later inputs.

## ADR-062 — Feature horizons and 2020 regime remain explicit research dimensions

- Date: 2026-08-29
- Status: Accepted and implemented

Game-day morning, 24-hours-before-kickoff, and 60-minutes-before-kickoff are emitted as distinct dataset horizons even when independent-football features coincide. Morning retains two candidate policies—09:00 America/New_York and first kickoff minus three hours—until the historical-odds audit resolves the operational convention. The 2020 season remains included with a regime indicator.

Consequences:

- Horizons cannot be pooled or used to fill each other's missing state.
- Later weather, injury, roster, and market features may legitimately differ by horizon without a schema redesign.
- Later experiments may include, flag, or exclude 2020 as a predeclared ablation; Phase 5B-2 makes no performance-based choice.

## ADR-063 — cfbfastR remains QA-only after universe-corrected PBP reconciliation

- Date: 2026-08-29
- Status: Accepted

The prior 123,444-play headline difference compared CFBD 2014–2024 with a public cfbfastR 2014–2025 total. On the common 2014–2024 universe, CFBD contains 42,406 more rows. Differences remain concentrated enough in 2021–2022 and within matched-game play counts to require explicit feature coverage and future common-row ablations, but do not block the baseline feature dataset.

Consequences:

- SportsDataverse/cfbfastR does not replace CFBD as the durable fact source.
- Exact play-level equality is not required across differing taxonomies and processing pipelines.
- PBP-dependent features carry coverage flags; season/source sensitivity remains a Phase 5B-3 validation concern.

## ADR-064 — Phase 5B-3 uses chronological fold-local falsification baselines

- Date: 2026-08-29
- Status: Accepted and implemented offline

The first proprietary NCAAF point-model tournament uses reusable expanding folds: 2014–2018 is the earliest training history, 2019–2023 are development evaluations, and 2024 is validation/model selection. Naive baselines, a sequential margin power rating, and Ridge margin/total models run separately for each horizon. Imputation, missing indicators, constant removal, scaling, and fitting are fold-local. OOF predictions and transparent JSON parameter artifacts remain outside Git under `.ncaaf-data/models/`.

Consequences:

- The 2025 holdout remains sealed and is rejected by ordinary model commands.
- Football point predictions are experimental proprietary candidates, not calibrated fair probabilities, recommendations, or evidence of betting edge.
- No model runtime or dependency enters FastAPI/Render; scikit-learn and NumPy remain research-only dependencies.
- Hyperparameters use only development OOF evidence; 2024 is not used to tune the alpha grid.

## ADR-065 — Unstable Elastic Net is deferred and Ridge retains the simplicity preference

- Date: 2026-08-29
- Status: Accepted for Phase 5B-3

The small predeclared Elastic Net grid was attempted under the same fold-local pipeline, but low-regularization configurations did not converge reliably on the wide v1 matrix. Phase 5B-3 therefore records the attempted grid and defers Elastic Net instead of publishing unstable metrics or expanding the search after seeing results. Ridge uses a modest four-value alpha grid and remains the regularized linear candidate.

Consequences:

- Nonconvergence is negative operational evidence, not a reason for an unplanned tuning campaign.
- A future Elastic Net retry requires a new predeclared experiment/version and a convergence criterion.
- Complexity must still demonstrate a practical, stable improvement before advancement.

## ADR-066 — Phase 5B-3 keeps horizons separate and model artifacts transient

- Date: 2026-08-29
- Status: Accepted and implemented

Exact input comparison found that the three horizon matrices are not fully identical under point-in-time availability, even though most independent-football features coincide. Each horizon is therefore fitted and evaluated independently. OOF/model files remain content-hashed local Parquet/JSON artifacts; only aggregate non-holdout reports are committed. No relational schema is added.

Consequences:

- Results cannot be pooled or copied across horizons.
- Future weather, availability, and market features can extend the same horizon boundary without redesign.
- Model persistence remains reproducible and lean; a production registry/inference path is deferred until promotion evidence exists.

## ADR-067 — Phase 5B-4 fits distributions only from earlier OOF residuals

- Date: 2026-08-30
- Status: Accepted and implemented offline

Phase 5B-4 begins calibration evaluation in 2020, using 2019 OOF residuals as the first seed. For each evaluation season, target, horizon, and point model, a distribution may use only OOF residuals from strictly earlier seasons. The minimum v1 pool is 400 rows. Normal, bounded Student-t, kernel-smoothed empirical, transparent grouped-scale, and total-only skew-normal candidates were frozen before results.

Consequences:

- Future residuals, the current evaluation outcome, and 2025 cannot affect an earlier probability.
- Distribution/calibration version is separate from point-model, dataset, and feature versions.
- No post-hoc binary transform is promoted in v1; a future transform requires a separately nested chronological fit.
- Research artifacts remain ignored and do not enter FastAPI or Render dependencies.

## ADR-068 — Integer lattice mass defines experimental push-aware settlement probabilities

- Date: 2026-08-30
- Status: Accepted and implemented offline

For a continuous outcome CDF `F`, integer result `k` receives `F(k + 0.5) - F(k - 0.5)`. Spread and total win/push/loss use exact integer settlement against the requested line. Half-point lines have zero push mass. For modern completed NCAAF moneylines, zero-margin mass is retained for audit and home/away probabilities condition on the non-tie outcomes.

Consequences:

- Integer-line probabilities are explicit, finite, normalized, deterministic, and testable.
- No arbitrary fixed push rate is invented.
- Phase 4's production integer-line EV exclusion remains unchanged until the offline candidate passes locked, shadow, and market-relative promotion gates and receives separate integration review.
- Synthetic grids measure probability behavior only; they do not establish market edge.

## ADR-069 — Advance quality-aware margin scale and empirical total residuals only to offline comparison

- Date: 2026-08-30
- Status: Accepted as experimental candidates

On 2020–2024 chronological OOF evidence, the margin power rating with early/late × high/low-quality grouped Normal scale improved NLL and CRPS slightly but consistently over homoskedastic Normal. Total Ridge without opponent adjustment with chronological empirical residuals improved both scores more clearly. These pairings advance to later offline market comparison, while Normal remains the mandatory falsification benchmark.

Consequences:

- “Advance” is not production promotion and does not change final fair probability, recommendations, EV, or staking.
- Student-t was operationally indistinguishable from Normal; total skew-normal improved CRPS but did not beat Normal decisively on paired NLL.
- Low-quality and early-season rows receive measured uncertainty rather than exclusion or arbitrary confidence penalties.
- Market consensus remains the implemented fair-probability source.

## ADR-070 — Do not advance a joint margin-total simulator in Phase 5B-4

- Date: 2026-08-30
- Status: Accepted for the v1 distribution tournament

Matched OOF margin/total residual correlation was approximately 0.041 across all three horizons, below the predeclared 0.10 materiality threshold. Phase 5B-4 therefore retains separate marginal distributions and does not add a joint score simulator merely for architectural symmetry.

Consequences:

- Separate marginal probabilities must not be described as a coherent joint score distribution.
- Expected component scores remain a diagnostic, including checks for impossible negative expectations.
- Reconsider joint simulation if richer football inputs, market conditioning, or later empirical evidence produces material dependence.

## ADR-071 — Phase 5B-5 uses an equal-budget controlled tree tournament

- Date: 2026-08-30
- Status: Accepted and implemented offline

XGBoost, LightGBM, and CatBoost receive the same three bounded configurations, folds, targets, horizons, features, and advancement gates. Configuration choice uses 2019–2023 development evidence at 24 hours; 2024 remains validation. No margin tree advances. CatBoost total clears the frozen point gates and advances only as an offline challenger.

Consequences:

- Tree complexity earns no automatic production role.
- Research dependencies remain outside Render production requirements.
- The chronological power rating remains the margin benchmark.
- CatBoost total cannot affect fair probability, recommendations, or stakes without later probability, market-relative, locked, shadow, and integration evidence.

## ADR-072 — Chronological empirical-discrete mass advances for offline key-number research

- Date: 2026-08-30
- Status: Accepted as an experimental probability candidate

A versioned empirical residual-ratio correction is learned from strictly earlier OOF seasons and applied to the quality-aware Normal integer lattice. It improves paired NLL/CRPS and represents observed mass near football key margins much better without hand-editing those margins. It also widens the 90% interval and overcovers, which remains an explicit limitation.

Consequences:

- Integer push mass is learned and normalized, never inserted as an arbitrary key-number bonus.
- Phase 4's production integer-line exclusion remains unchanged.
- The method proceeds to offline market-relative evaluation only; it is not a production fair probability.

## ADR-073 — Retain Ridge empirical total probability despite CatBoost point improvement

- Date: 2026-08-30
- Status: Accepted for the current offline benchmark

CatBoost total improves point MAE and remains an offline challenger. Its empirical-residual pairing has slightly better NLL and CRPS than Ridge empirical, but both paired 95% intervals cross zero. Under the frozen simplicity rule, Ridge empirical remains the probability benchmark.

Consequences:

- Point accuracy and distribution quality remain separate promotion questions.
- Small uncertain proper-score gains do not justify replacing a simpler benchmark.
- Later fixed-horizon market comparison should include both only if acquisition and compute budgets permit.

## ADR-074 — Future portfolio evaluation separates strategy and executed books

- Date: 2026-08-30
- Status: Accepted for Phase 6 design

Future paper operation must persist a frozen strategy/model book containing every qualified recommendation, including recommendations a human declines, separately from the actual/executed paper book. Human approval remains required. Performance attribution must distinguish model/qualification quality, human selection, price/execution, and portfolio sizing.

Consequences:

- Declined recommendations are immutable research observations, not deleted opportunities.
- Selection bias can be measured instead of silently contaminating model evaluation.
- This decision does not authorize automated wager execution or implement Phase 6 behavior now.

## ADR-075 — Phase 5B-6 uses bounded CFBD preseason/personnel products with immutable caching

- Date: 2026-08-30
- Status: Accepted and implemented offline

The initial preseason/personnel corpus uses bounded CFBD returning-production, portal, recruiting-team, talent, roster, player-season passing-stat, and coach products for 2014–2024. Requests reuse the Phase 5B-1 credential-free canonical request/cache contract. Source responses and manifests remain immutable; normalized program-season and model-ready artifacts remain content-addressed Parquet outside Git.

Consequences:

- The audit consumed 68 billable calls and does not require another historical download for repeat modeling.
- CFBD remains the durable structured source; no display-string-only program merge is permitted.
- Coordinator history is deferred because no verified structured CFBD product exists in the selected contract.
- Research dependencies/artifacts stay outside the FastAPI and Render production path.

## ADR-076 — Reconstructed preseason state uses an explicit season-start availability boundary

- Date: 2026-08-30
- Status: Accepted for offline reconstructed research

Under `preseason-reconstructed-season-start-v1`, retrospectively retrieved returning production, recruiting/talent, roster, and coach state become eligible at the target season's first scheduled FBS kickoff. Portal records additionally require a provider transfer date no later than that boundary. Actual local ingestion remains the 2026 retrieval time, and every row carries `strict_live_fidelity=false`.

Consequences:

- This dataset can test reconstructed predictive usefulness but cannot claim strict Week 0 historical replay.
- A genuine publication-vintage source requires a new policy and dataset version; it cannot silently replace v1.
- 2025 remains rejected by ordinary source, build, validation, and modeling commands.

## ADR-077 — Missing personnel-source coverage is not a zero-valued football fact

- Date: 2026-08-30
- Status: Accepted and implemented

Unavailable source families remain null and carry explicit availability/missing-family indicators. In particular, absent pre-2021 portal coverage is not represented as zero transfers. Reconstructed roster/player IDs support overlap and prior-leading-passer continuity proxies only; they do not establish the Week 1 starter. Coach IDs identify continuity but are excluded as model categories.

Consequences:

- Fold-local model preprocessing may impute numeric values while retaining missing indicators; normalization never silently fabricates zero.
- Source-era and low-coverage effects remain measurable in ablations and quality segments.
- QB, transfer, and coaching explanations must use the precise proxy name rather than stronger labels unsupported by the source.

## ADR-078 — Advance the bounded preseason margin prior, not the probability benchmark

- Date: 2026-08-30
- Status: Accepted as offline research evidence

The regularized preseason adjustment to the chronological margin power rating improved 24-hour OOF MAE by 0.174 points and Weeks 0–3 by more than the frozen practical threshold. Recruiting/talent supplied the clearest standalone and leave-one-out family evidence. Preseason CatBoost total improved point MAE modestly. Full preseason Ridge total and the common-era transfer family were unfavorable.

Limited probability comparisons reused the existing empirical-discrete margin and empirical-residual total methods. Both candidates improved point estimates of NLL/CRPS, but paired season-block intervals crossed zero. The existing probability benchmarks therefore remain.

Consequences:

- The preseason-adjusted power model and recruiting/talent family advance only to later offline and market-relative evaluation.
- CatBoost preseason total remains an offline point challenger; it does not displace Ridge empirical probability.
- Returning production, QB, coaching, and roster continuity remain explicit exploratory ablations rather than independently promoted families.
- Portal features require a separately frozen 2021+ common-coverage experiment before reconsideration.
- No production fair probability, endpoint, EV, stake, or recommendation changes.

## ADR-079 — Historical odds use immutable provider-archive snapshots with exact cutoff evidence

- Date: 2026-08-30
- Status: Accepted and implemented for Phase 5B-7A research

The bounded audit stores lossless historical The Odds API responses outside Git under credential-free canonical request hashes. Every audit row retains the requested cutoff, actual closest-prior provider snapshot timestamp, real retrieval time, and `the-odds-api-provider-archive-snapshot-v1`. It never backdates local ingestion or treats archive reconstruction as contemporaneous Phase 3 capture.

Consequences:

- The credential exists only in the transport request and is absent from filenames, hashes, manifests, reports, and logs.
- The provider snapshot must be at or before the cutoff and within the frozen cadence tolerance.
- Repeated logical timestamps reuse one immutable cached response; the 76-logical plan required 67 unique requests and 2,010 credits.
- Raw payloads remain auditable but are not committed or loaded into production services.

## ADR-080 — Phase 5B-7A conditionally approves only measured FBS-vs-FBS combinations

- Date: 2026-08-30
- Status: Accepted as an acquisition gate

The predeclared audit gates use the primary FBS-vs-FBS model cohort while retaining FBS/FCS context evidence separately. Require at least two complete supported books, coherent paired sides/lines, closest-prior timestamp fidelity, reliable event mapping, at least 80% overall usable coverage, and at least 70% in every audited season.

The audit conditionally approves morning and 60-minute h2h/spreads/totals plus near-close spreads/totals. It rejects 24 hours and near-close h2h for the first market-aware corpus. This is a data-coverage decision, not evidence of model edge.

Consequences:

- Phase 5B-7 may acquire and compare only approved combinations unless a new predeclared audit changes the evidence.
- 2020 remains usable where its per-season gate passed; its weaker 24-hour coverage cannot be hidden by stronger 2022/2024 results.
- Missing or ambiguous event mappings remain excluded rather than fuzzy-merged.
- Minimum sportsbook depth is two complete books from the supported DraftKings/FanDuel/BetMGM set.

## ADR-081 — Game-day morning means first scheduled kickoff minus three hours

- Date: 2026-08-30
- Status: Accepted for the initial NCAAF workflow

Fixed 09:00 America/New_York and first-kickoff-minus-three-hours tied on aggregate coverage and were identical on eight of nine audited slates. The relative convention is selected because it guarantees a pre-first-kickoff run and remains coherent for non-noon slate starts.

Consequences:

- Historical and prospective morning results use one explicit versioned relative cutoff.
- The 60-minute horizon remains separate and must not be pooled with morning.
- This operational convention may be replaced only by a new version backed by better coverage evidence; it is not retroactively rewritten.

## ADR-082 — Full morning is primary; later horizons use a bounded robustness cohort

- Date: 2026-08-31
- Status: Accepted and implemented for Phase 5B-7B research

The canonical market-aware development corpus uses every eligible 2020–2024 FBS-vs-FBS game at first scheduled kickoff minus three hours for h2h, spreads, and totals. Full-cohort 60-minute and near-close acquisition was rejected on cost. Instead, a stable-hash sample selected two games per season and early/middle/late regular-season or postseason stratum while preferring distinct kickoff windows; eligible 7A anchors were added through cache reuse. Selection used schedule identity and timing only, never outcomes or model performance.

Consequences:

- Morning is the primary 5B-7C cohort.
- The 60-minute h2h/spread/total and near-close spread/total sample is secondary robustness evidence only.
- The later sample cannot support full-cohort claims or be pooled with morning.
- The executed plans consumed 10,290 morning credits and 1,900 later-horizon credits, leaving the required 5,800-credit reserve.

## ADR-083 — Historical market normalization preserves books and rejects incomplete groups

- Date: 2026-08-31
- Status: Accepted and implemented for offline research

Phase 5B-7B stores deterministic Parquet observations at canonical event, horizon, sportsbook, market, side, and exact-point granularity. Every row traces to an immutable credential-free raw manifest and retains requested versus returned snapshot time. A research-comparable group requires a reliable event match, a closest-prior snapshot within the frozen cadence tolerance, coherent opposing sides and exact lines, valid prices, and at least two complete supported books.

Consequences:

- Missing or ambiguous events and incomplete book/market groups remain explicitly unusable; prices are never interpolated.
- Individual books remain available for later no-vig and consensus construction; 7B does not collapse them.
- Provider-archive availability is not rewritten as contemporaneous ingestion.
- Consensus, model comparison, residual targets, edge, EV, and CLV remain 5B-7C or later work.

## ADR-084 — Market comparison uses exact-line median consensus and exact OOF horizon joins

- Date: 2026-08-31
- Status: Accepted and implemented for Phase 5B-7C research plumbing

Each complete supported book pair is de-vigged with `proportional-v1`. Moneyline consensus is the unweighted median of book no-vig probabilities. Spread and total consensus first select the exact point supported by the most complete books, with deterministic median-distance/numeric tie-breaking, then take the unweighted median only at that point. Different lines are never averaged. Minimum depth remains two books; book weights are not learned in this phase.

The comparison layer joins only canonical-event-exact, chronological OOF predictions at an explicit equivalent horizon. Morning maps from `morning_first_kickoff_minus_3h` to `game_day_morning`; 60 minutes maps to itself. Near-close is not substituted with 60-minute football predictions and therefore remains consensus-only. Margin common cohorts require both moneyline and spread; total cohorts require total. Pushes are retained as distinct outcomes.

Consequences:

- Full 5B-7 must evaluate football-only, market baseline, residual, and market-as-feature candidates on the same frozen cohort.
- Sixty-minute evidence is diagnostic only; near-close cannot enter a football-model comparison until a genuine same-horizon OOF prediction exists.
- Consensus, joins, residual targets, and model-ready inputs are reproducible transient research artifacts, not production fair-probability changes.
- No claim of edge, profitability, model promotion, EV, or staking follows from the plumbing diagnostics.

## ADR-085 — Morning consensus remains the margin/ML benchmark; one tiny total blend advances to the locked gate

- Date: 2026-08-31
- Status: Accepted for Phase 5B-8 candidate narrowing

Full Phase 5B-7 compared market-only, frozen football finalists, market-residual, market-as-feature, and constrained OOF blend candidates on the 7C common cohorts. Morning spread consensus beat every standalone margin architecture. Moneyline no-vig consensus also beat the proprietary probability candidates. Residual/direct models did not identify stable systematic market errors. A constrained market plus Ridge-no-opponent-adjustment total blend improved paired MAE by about 0.026 points and three-way Brier by about 0.001, with season-block intervals excluding zero, but the practical effect is very small.

Consequences:

- Phase 5B-8 keeps market consensus as the clear margin, moneyline, spread, and total benchmark.
- No proprietary margin replacement or margin blend advances; football power remains an independent diagnostic only.
- The constrained total Ridge blend is the only proprietary market-aware challenger advanced to the locked gate. The preseason CatBoost blend is a sensitivity comparator, not another finalist.
- Practical-effect, calibration, segment-degradation, artifact, and one-time-access rules must be frozen before 2025 is opened. A failure retains market consensus; there is no forced proprietary model.
- The 60-minute and near-close samples remain diagnostic and cannot affect selection.
- This research decision does not change Phase 4 fair probability, production APIs, EV, staking, recommendations, or model lifecycle status.

## ADR-086 — Freeze market-first finalists and an all-or-fallback total-blend gate

- Date: 2026-08-31
- Status: Accepted and implemented offline for Phase 5B-8

Phase 5B-8 freezes market consensus as the only margin/spread/moneyline holdout finalist and retains football power as diagnostic only. The sole proprietary challenger is the fixed total formula `market + 0.17854145992095644 * (Ridge-no-opponent-adjustment - market)`, using the existing 2024-evaluation artifact trained through 2023. Rejected residual, direct, broader blend, and CatBoost candidates cannot enter the holdout.

The total blend advances only if it clears every frozen integrity, minimum-sample, 0.10-point MAE practical effect, RMSE, Brier/log-loss, paired-interval, calibration, push, complexity, and broad-segment gate. Any failure falls back to market consensus. A data/code integrity defect stops evaluation; weak performance does not authorize refitting or tuning.

Consequences:

- 2025 remains sealed until a separate explicit one-time Phase 5B-9 unlock verifies the freeze manifest and artifacts.
- Passing Phase 5B-9 permits only prospective shadow-candidate status, not production pricing or recommendation influence.
- Market-first margin/ML/spread does not prohibit later bets; Phase 6 must still compare fair probability with executable price under EV, uncertainty, and portfolio-risk rules.
- Push mass remains explicit, later horizons remain diagnostic, provider calls remain zero, and Phase 4 behavior is unchanged.


## ADR-087 — The locked 2025 holdout rejects the total blend and retains market consensus

- Date: 2026-08-31
- Status: Accepted and implemented offline for Phase 5B-9

After every Phase 5B-8 hash passed, 2025 was unlocked once under an immutable access record. The fixed `0.17854145992095644` football-weight total blend was applied without refitting to an identical 758-game market cohort. It failed the frozen MAE, multiclass Brier, and multiclass log-loss improvement gates. The other aggregate, interval, calibration, push-semantics, and broad-segment gates passed.

Consequences:

- Market consensus remains the NCAAF total estimator; the blend is not eligible for shadow-candidate registration.
- Market consensus also remains the already-frozen margin, spread, and moneyline estimator. Football power remains diagnostic only.
- The one-time result is immutable and must not trigger 2025-based retuning, feature changes, calibration changes, or a replacement candidate search.
- Phase 5B-10 may register the retained market benchmarks for prospective shadow operations, but this result does not authorize production betting, EV qualification, staking, or recommendations.
- Ordinary development commands continue to reject 2025; reproduction requires the audited unlock record and exact immutable inputs.

## ADR-088 — Register market consensus as NCAAF v1 and keep shadow history append-only

- Date: 2026-08-31
- Status: Accepted and implemented for Phase 5B-10

The Phase 5B-9 holdout result is final for NCAAF v1. Market consensus is registered as `retained_benchmark` for margin, moneyline, spread, and total. Football power and Ridge artifacts remain diagnostic; the constrained market/Ridge total blend remains rejected. No proprietary model may enter the fair-value interface by substitution or relabeling.

Model and artifact registry identities are immutable by `ID + version`; changed content or lifecycle requires a new version. Prospective shadow predictions preserve the exact producing registry version and decision-time fair-value payload. Market movement appends another prediction rather than overwriting the first. Final outcomes are separate immutable records and do not mutate pregame history.

Consequences:

- Phase 6 receives retained fair probability/line, model status/version, uncertainty/quality, and provenance through `ncaaf-fair-value-v1`; it obtains executable sportsbook price separately.
- Registry metadata and shadow history live in PostgreSQL; large research/model artifacts remain content-addressed files referenced by hash and URI.
- The first prospective workflow uses `morning_first_kickoff_minus_3h`, requires at least two complete supported books, and records source as-of/book/dispersion evidence.
- Diagnostic/rejected models cannot provide retained fair value. Integer lines cannot silently assume zero push probability.
- Shadow outcome evaluation is separate from bet placement, bankroll ledger, EV, staking, and recommendations.
- Phase 5 is complete with an honest retained market benchmark. This is neither proprietary edge nor production-betting approval.

## ADR-089 — Use a versioned quarter-Kelly risk budget with approval-time revalidation

- Date: 2026-09-01
- Status: Accepted and implemented for NCAAF Phase 6 paper trading

`fractional-kelly-risk-budget-v1` uses the positive push-aware Kelly solution multiplied by 0.25, then applies uncertainty, CORE/OPPORTUNISTIC, drawdown-state, and portfolio-cap adjustments. Full Kelly is prohibited. Initial caps are 2% equity per CORE straight, 1% per OPPORTUNISTIC straight, 8% per slate, 4% per game/correlated group, 5% per team/market, with reduced risk at 10% drawdown and pause at 20% or the 50%-of-start floor. One displayed unit is 4% of decision-time equity and does not drive stake math.

Consequences:

- These are versioned paper defaults requiring prospective validation, not permanent optimal parameters.
- A subminimum calculated stake is rejected rather than increased to satisfy the minimum.
- Approval rechecks cash, drawdown, opposing exposure, and caps transactionally; a stale proposal cannot reserve risk merely because it qualified earlier.
- Strategy-book recommendations remain distinct from explicitly approved official paper bets.

## ADR-090 — Restrict the initial parlay sleeve to verified cross-event disjoint-team quotes

- Date: 2026-09-01
- Status: Accepted and implemented for NCAAF Phase 6 paper research

The optimizer may select at most one two- or three-leg parlay whose legs independently qualify. It requires an executable combined sportsbook quote linked to exact leg observations. Marginal probabilities may be multiplied only for different events with disjoint teams under `cross-event-disjoint-team-independence-v1`; same-game, shared-team, and unknown-correlation combinations are rejected. The sleeve uses 10%-Kelly, a default 0.5% per-parlay cap, and a 1% day cap while consuming shared event/team/day exposure.

Consequences:

- The public API does not accept caller-supplied combined payouts. The current provider lacks parlay quotes, so PASS is the normal live result until a trusted adapter exists.
- The optimizer is opportunistic and deterministic; it need not select ranks one through three and never forces a combination.
- Parlay bets share the official ledger but retain separate leg snapshots and performance attribution.
- Same-game correlation, voided-leg repricing, CLV, and sleeve disablement evidence remain unresolved.

## ADR-091 — Persist a strategy book separately from the executed paper book

- Date: 2026-09-01
- Status: Accepted and implemented for NCAAF Phase 6

Every decision run freezes equity, risk state, policies, PASS/rejection reasons, and deterministic hashes. Proposed straight/parlay recommendations preserve fair value separately from executable price, alternatives, provenance, stake, and risk adjustments. Only explicit approval creates a `bets` row, `bet_approvals` record, state transition, and immutable ledger reservation in one transaction. Rejection creates no bet.

Consequences:

- Human-selection and execution effects can be separated from qualification/model performance.
- Straight and parlay accounting use the existing ledger; no competing bankroll exists.
- Phase 6.5 can render proposals, PASS, exposure, official bets, and attribution without embedding business logic in the frontend.

## ADR-092 — Keep dashboard decisions server-authoritative behind a same-origin secret proxy

- Date: 2026-09-01
- Status: Accepted and implemented for Phase 6.5

The NCAAF dashboard is a separate React/TypeScript/Vite client prepared for Cloudflare Pages. It renders Phase 6 responses but does not recompute fair value, EV, Kelly sizing, qualification, risk, or parlay joint probability. FastAPI remains authoritative for all decisions and revalidates risk when a human approves a paper bet.

Because a static `VITE_*` variable is public, the browser may not contain `APP_API_KEY`. A same-origin Cloudflare Pages Function injects the credential from an encrypted server-side `BACKEND_API_KEY` secret when proxying `/api/*` to Render. The Pages site must be protected by Cloudflare Access before private operational use.

Consequences:

- Browser refreshes read PostgreSQL-backed API state and never call The Odds API or consume provider credits.
- Dashboard policy/model/freshness and market-movement reads use bounded projections; raw market snapshot JSON and credentials are excluded.
- Settings are read-only until the backend owns a versioned mutation contract.
- Development preview data is visibly labeled and disabled in production.
- Cloudflare Pages deployment remains an explicit operator action, not an automatic repository side effect.

## ADR-093 — Make POLARIS refresh explicit, timing-labeled, and registry-self-initializing

- Date: 2026-09-01
- Status: Accepted and implemented for production readiness

The operational dashboard is branded `POLARIS — NCAAF Portfolio` and exposes only Today, Portfolio, Bets, Parlay, History, and Settings as primary destinations. Research/model evidence remains under Settings → System / Methodology; market movement is an exact stored-history detail. Browser reads never call a provider. The only dashboard-triggered provider operation is an authenticated manual refresh that fetches NCAAF h2h/spreads/totals once, persists raw and normalized data, analyzes every upcoming slate, and rejects concurrent execution.

The morning decision convention remains first scheduled kickoff minus three hours. Runs before the cutoff are `EARLY_LOOKAHEAD`, runs within the 15-minute operational tolerance beginning at the cutoff are `OFFICIAL_PRIMARY_HORIZON`, and later runs are `POST_HORIZON`. All retain actual timestamps. Market freshness/provider failure is separate from application registry health and portfolio risk.

The committed Phase 5 registry manifest is validated and idempotently registered during application startup. A content conflict fails closed; a normal deployment no longer depends on an undocumented manual sync.

Consequences:

- Navigation, page reload, background query revalidation, and history inspection incur no Odds API calls.
- Production registry bootstrap reads the frozen committed JSON through lightweight domain validation only; offline `app.research` dependencies remain outside Render's web dependency graph.
- Manual refresh is deliberate, visibly in-flight, safely retry-bounded by the adapter, and followed by persisted-state revalidation.
- Upcoming recommendations never masquerade as validated primary-horizon decisions.
- Raw market snapshots remain available for audit but absent from dashboard query projections.
- The POLARIS frontend remains a paper-trading control surface; fair value, EV, staking, risk, approval, and ledger authority stay in FastAPI.

## ADR-094 — Keep early-week watchlist research outside recommendation lifecycle

- Date: 2026-09-01
- Status: Accepted and implemented

POLARIS persists `ncaaf-watchlist-v1` as immutable metadata on each recommendation decision run. A watchlist row must already be a structurally valid Phase 4 pricing opportunity with positive edge and EV, remain pregame, and fail only an explicit research-safe Phase 6 gate. Production qualification thresholds remain unchanged. Ranking uses failed-gate count followed by normalized distance to the existing EV, edge, book-depth, dispersion, and freshness gates.

Consequences:

- Watchlist rows are research only: no stake, recommendation record, approval, official bet, ledger mutation, or parlay eligibility exists.
- Manual refresh creates a new current state; the latest run per upcoming slate can promote, demote, or remove a row without rewriting prior decisions.
- Today uses the persisted analysis count rather than inferring analyzed games from qualified recommendations.
- Browser reads remain stored-data-only and cannot consume provider credits.

## ADR-095 — Separate calculable pricing candidates from qualified opportunities

- Date: 2026-09-01
- Status: Accepted and implemented; refines ADR-094

Phase 4 must retain every structurally calculable candidate side before applying its edge, EV, dispersion, and Top-N opportunity filters. Its external `opportunities` contract remains the qualified Top-N projection, while Phase 6 consumes the untruncated calculable collection and assigns each side to QUALIFIED, WATCHLIST, or PASS under unchanged production gates. `ncaaf-watchlist-v2` admits only future, positive-edge, positive-EV near misses under a bounded deterministic gate-distance rule.

Every decision run persists a safe stage funnel and rejection counts. Latest-upcoming retrieval aggregates these counts and supplies UTC-date/weekday slate summaries to Settings → System / Methodology. This diagnostic path is stored-data-only and never logs raw payloads, credentials, or credential-bearing URLs.

Consequences:

- A side at 1.40% EV and 0.80% edge is visible as research instead of disappearing before Watchlist classification; thresholds remain 1.50% EV and 0.75% edge.
- Clearly negative, materially distant, structurally invalid, stale, ambiguous, singleton-book, or unknown-push candidates remain PASS/non-calculable and cannot be approved or used in parlays.
- Exact spread/total points remain separate. The system diagnoses fragmented line depth rather than interpolating across `-17`, `-17.5`, and `-18`.
- Whole-number spread/total observations remain preserved but fail closed until validated push-aware pricing exists.
- The pricing funnel exposes whether a zero-recommendation slate is an honest result or pipeline attrition without changing fair value, staking, exposure, or approval behavior.

## ADR: Separate live snapshot freshness from provider quote age

- **Status:** Accepted (2026-09-01)
- **Decision:** `MarketSnapshot.requested_at` is the hard live freshness clock. Provider `last_update` remains source/quality metadata with a separate configurable pathological ceiling. Latest-state selection prioritizes the newest time-eligible snapshot. The default supported US sportsbook allowlist is BetMGM, BetRivers, Caesars (`williamhill_us`), DraftKings, Fanatics, and FanDuel.
- **Reason:** The former code compared an unchanged bookmaker-price timestamp to the 120-second snapshot limit. A fresh 12:00 retrieval could reject an executable 11:55 quote and collapse before pairing. The prior DraftKings/FanDuel/BetMGM list was a prototype default rather than a frozen consensus-method rule.
- **Consequences:** EV, edge, two-book depth, dispersion, staking, and fair-value methods do not change. Quote age is visible. Pathological ages fail closed. A pre-candidate collapse is `DEGRADED`, never PASS.

## ADR-096 — Rank qualified positions by robust expected log growth and separate outlier labels from integrity failures

- Date: 2026-09-02
- Status: Accepted and implemented; refines ADR-041, ADR-089, and ADR-090

Phase 6 must first apply the unchanged production EV, edge, book-depth, freshness, dispersion, structural, model-status, and integrity gates. It then ranks qualified NCAAF positions under `expected-log-growth-risk-budget-v2` by the minimum expected log growth across contributing paired no-vig probabilities at the projected standalone adjusted-Kelly fraction. Consensus expected growth, adjusted Kelly, quote integrity, depth, dispersion, moderate break-even probability, raw EV, and edge are deterministic later tie-breakers. Top N follows ranking. Watchlist continues to use gate distance.

The exact score is:

```text
g(p, f) = p_win * ln(1 + f*(decimal_odds - 1)) + p_loss * ln(1 - f)
robust_score = min(g(p_book, f) for each complete contributing book)
```

`f` uses the existing push-aware full-Kelly solution, quarter-Kelly factor, uncertainty/classification/state multipliers, and current standalone portfolio caps. V2 changes selection order, not stake limits. No explicit longshot ban or spread/total quota is introduced; the economics naturally require an extreme price to support meaningful prudent growth and robust book agreement before outranking a strong moderate-odds market.

The `unweighted-median-v1` fair-value method is unchanged. `material_book_outlier` and `best_executable_book_outlier` are now explicit informational audit labels. A supported, active, fresh, correctly paired best quote is not rejected merely because it is better than the median. Unknown integrity warnings and the 6-point Phase 6 dispersion ceiling remain hard failures. Median consensus prevents one extreme book from defining fair value; the robust score and integrity tie-break address corroboration without inventing book weights.

`cross-event-parlay-v2` likewise ranks otherwise eligible verified offers by expected log growth at the capped sleeve stake after duplicate-exposure penalty, with joint, minimum-leg, and aggregate leg probabilities before raw joint EV. It retains the cross-event/disjoint-team requirement and does not force a parlay.

Consequences:

- Raw EV remains visible and required but cannot dominate Today solely through a large longshot payout.
- CORE/OPPORTUNISTIC thresholds, quarter-Kelly sizing, minimum stake, all exposure caps, approval, and ledger behavior are unchanged.
- Recommendation snapshots preserve portfolio rank, full/adjusted Kelly, expected/robust log growth, quote-integrity state, and outlier provenance.
- `ncaaf-qualification-v2`, `expected-log-growth-risk-budget-v2`, `cross-event-parlay-v2`, and `ncaaf-portfolio-recommendation-v2` make the changed semantics auditable.

## ADR-097 — Keep risk-adjusted growth primary and bound the main board at +500

- Date: 2026-09-02
- Status: Accepted and implemented; narrowly supersedes ADR-096's statement that no explicit longshot guardrail exists

POLARIS has no dedicated longshot/high-variance sleeve. `ncaaf-qualification-v3` therefore preserves every structurally calculable candidate and its fair probability, executable probability, edge, EV, books, dispersion, and provenance, but marks a best executable price above `+500` as `outside_main_board_odds_profile`. Such a row is diagnostic/PASS only: it cannot receive a stake, approval, ledger entry, or parlay eligibility. Exact `+500` remains eligible for the ordinary rules.

This boundary is a final safety guardrail, not the primary ranking method. POLARIS does not impose a `-300/+300` hard band, does not reject heavy favorites merely for price, does not add market-type quotas, and does not change fair-value or EV formulas. All otherwise eligible prices through `+500` continue to rank by robust expected log growth at the Kelly-supported risk fraction, consensus expected growth, quote integrity, depth, dispersion, and deterministic tie-breakers. Tests independently establish that representative `+1000` and `+2000` candidates with larger raw EV already trail a strong `-110` spread on expected log growth before the safety guardrail is applied.

The guardrail is necessary because an extreme payout can support high calculated log growth when a small market-consensus probability difference is treated as precise, while the current portfolio has neither a separately validated tail-probability policy nor an isolated exposure budget for that estimation risk. A future longshot sleeve must be explicitly designed, versioned, empirically validated, separately capped, and recorded in a new decision before these rows can become actionable.

Consequences:

- `expected-log-growth-risk-budget-v2` remains unchanged and primary.
- `ncaaf-portfolio-recommendation-v3` records the new qualification semantics; no staking or exposure limit changes.
- Prices above `+500` remain visible in the evaluated-candidate/funnel diagnostics and retain unchanged economics.
- Watchlist does not promote them, because Watchlist is near-production research rather than a substitute longshot sleeve.
- Parlay construction still begins only from actionable straights, so excluded extreme prices cannot enter parlays indirectly.

## ADR-098 — Price explicit refreshes after their ingestion transaction commits

- Date: 2026-09-02
- Status: Accepted and implemented as a production correctness hotfix

Provider `requested_at` is request-start time, not proof that the response has returned or its normalized observations have committed. An explicit live refresh therefore uses the repository's post-commit `ingestion_completed_at` as its recommendation/pricing `as_of`. The refresh response exposes request start, provider retrieval, ingestion completion, and decision cutoff separately. `MarketSnapshot.requested_at`, provider quote timestamps, and observation `ingested_at` remain unchanged audit facts.

Consequences:

- The snapshot fetched by a manual refresh satisfies `observed_at <= as_of`, `requested_at <= as_of`, and `ingested_at <= as_of` for the decision it triggered.
- The SQL and historical replay cutoffs are not weakened; caller-supplied historical cutoffs still exclude later observations and later ingestion.
- Snapshot freshness remains based on request start, so normal HTTP/persistence elapsed time is visible rather than backdated to zero.
- The multi-slate Watchlist diagnostic reports the freshest/latest snapshot-age gauge, while quote-age maximum and p90 remain conservative cross-slate maxima.

## ADR-099 — Price NCAAF spread/total offers against a robust empirical cross-line market curve

- Date: 2026-09-02
- Status: Accepted and implemented; supersedes the NCAAF production portions of ADR-045/046 that required identical lines across books and excluded integer-line EV

Exact opposing sides and points remain mandatory inside each sportsbook. Across supported books, `ncaaf-empirical-cross-line-v1` uses every coherent main line instead of requiring identical points: proportional no-vig probability and line imply a per-book market center, then `overround-weighted-huber-center-v1` combines centers with bounded inverse-overround weights and bounded outlier influence. Moneyline remains `proportional-v1` plus `unweighted-median-v1`.

The committed curve is derived from immutable 2020–2024 NCAAF morning-market/final-score artifacts and contains discrete spread/total residuals. It maps the robust center to integer football outcomes, so half-points have zero push mass and integer lines carry explicit push probability. Every book-side executable line is evaluated separately with push-aware EV; the best executable offer remains distinct from fair value. Outputs preserve fair center, line advantage, curve version/hash, source observations, book centers, dispersion, and warnings.

A chronological audit evaluated existing production gates separately by market. Positive-signal tails were too sparse and season-unstable to justify lowering or splitting them, so Phase 6 retains 0.75 percentage-point edge, 1.5% EV, two complete books, and 6 percentage-point maximum dispersion. Fixed odds-band diagnostics and the practical `-220` through `+220` band are observational only. Robust expected-log-growth ranking and the `+500` main-board guardrail remain unchanged; no market quota or odds-based probability adjustment exists.

Consequences:

- A home `-3.5` can receive value when the robust market center is `-4.5`, and an Over `53.5` can receive value against a robust total near `55.5`, without pretending different lines are identical.
- A single obvious book cannot materially determine the center, although genuine broad cross-book disagreement still surfaces through dispersion and integrity warnings.
- Integer spreads/totals are no longer categorically dropped from the NCAAF candidate path; they qualify only when their explicit push-aware economics and all unchanged portfolio gates pass.
- The production loader is standard-library-only and validates the empirical artifact hash; offline audit code remains outside the FastAPI dependency graph.
