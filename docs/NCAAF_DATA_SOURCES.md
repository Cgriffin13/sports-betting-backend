# NCAAF Data Sources

Status: **Phase 5A source assessment, researched 2026-08-28.** Prices, quotas, coverage, and terms can change; verify them before purchase or production use. This document recommends candidates, not permission to reuse third-party data. Credentials belong only in environment variables or a managed secret store.

## Recommendation

The minimum viable research dataset is CollegeFootballData (CFBD) schedules, results, play-by-play, teams, venues, coaches, recruiting, returning production, and transfers, plus the repository's existing The Odds API observations. Derive rolling efficiency features from timestamped raw games and plays rather than trusting retrospectively recomputed season summaries. Use `cfbfastR`/SportsDataverse as a research bootstrap and cross-check, subject to an upstream-data terms review.

Historical, fixed-horizon sportsbook data is the main paid-data gate. Without it, an independent football model can be developed, but claims that it beats, corrects, or blends with the market are not valid. A targeted The Odds API historical purchase is the first paid dataset to evaluate. Injuries, depth charts, weather forecasts, and player participation should be incremental tracks, not blockers for the first honest baseline.

## Source matrix

| Source | Exact useful data | Depth / update | Access, limits, approximate cost | Terms / reliability | Recommended role |
| --- | --- | --- | --- | --- | --- |
| [CollegeFootballData API](https://api.collegefootballdata.com/getting-started) | Games, teams, plays, drives, box scores, player stats/usage, recruiting, rankings, coaches, transfers, returning production, venues, betting lines, advanced metrics | Core historical coverage varies by endpoint; starter data includes long-run schedules and modern detailed data. Play detail is strongest in recent seasons. Current/live endpoints update during season. | Bearer-token REST API. [2026 tiers](https://collegefootballdata.com/api-tiers): free 1,000 calls/month; paid tiers from $1/month for 5,000 through $30/month for 500,000. | [Terms](https://collegefootballdata.com/terms) permit subscribed use and derived work but restrict raw redistribution/substitute services. Endpoint coverage and correction timing require manifests and audits. | **Tier A primary research source.** Persist raw extracts and derive point-in-time features. Validate endpoint-by-endpoint coverage before freezing the dataset. |
| [CFBD methodology / CORE ratings](https://apinext.collegefootballdata.com/methodology-overview) | Precomputed opponent-adjusted ratings and advanced metrics | CORE retrospective ratings begin in 2016 and use the current methodology | Included by API tier | Historical values may be retrospective, not necessarily values published at the historical prediction time. | Benchmark/validation only unless an as-of publication history is proven. Prefer own rolling transformations for strict replay. |
| [SportsDataverse data repository](https://github.com/sportsdataverse/sportsdataverse-data) and [cfbfastR data](https://github.com/sportsdataverse/cfbfastR-cfb-data) | Bulk schedules, play-by-play, team/player box scores, drives, advanced EPA/success/explosiveness, rosters and related derived tables | `cfbfastR` documents completed-game PBP from 2014; field and participant coverage varies by year | Public bulk files and open-source tooling; no API credential | Code is open source, but its license does not automatically grant commercial redistribution rights to upstream ESPN-derived data. Schema/corrections can change. | **Tier A research bootstrap and independent cross-check.** Complete legal/terms review before production redistribution or reliance. |
| Existing The Odds API integration | Current NCAAF bookmaker events, h2h, spreads, totals; Phase 3 raw snapshots and exact normalized observations | Forward history begins when this service captured it | Existing credential and plan | Already production-integrated; provider terms govern storage/use. | **Tier A forward market source and execution-price source.** Continue scheduled snapshot capture at explicit horizons. |
| [The Odds API historical odds](https://the-odds-api.com/historical-odds-data/) | Timestamped historical bookmaker snapshots; featured markets available from 2020-06-06, generally 10-minute snapshots then 5-minute from 2022-09; wider markets from 2023 | Fixed timestamp query returns closest snapshot at or before request time | Paid plans currently shown at [provider pricing](https://the-odds-api.com/). Historical requests cost 10 × regions × markets; one region and three markets costs 30 credits per timestamp. Rough current entry: $30/month / 20k credits. | Strong fit with existing normalization. Must preserve provider snapshot timestamp and request/ingest times. Coverage/book continuity needs audit. | **Highest-priority paid evaluation.** Pull a bounded horizon grid, not every five-minute snapshot. Four horizons × 15 weeks × six seasons is roughly 360 slate calls or 10,800 credits before bowl/QA calls. |
| [SportsDataIO NCAAF](https://sportsdata.io/developers/workflow-guide/ncaa-football) | Schedules/results, team/player stats, injuries, odds/opening/movement/closing lines and some news context | Product-specific; historical Vault advertises long-run data | [Discovery Lab](https://sportsdata.io/developers) offers delayed/research access around $99/month for fantasy or odds and $149 combined; production/Vault pricing is quote-based | Published workflow notes that college depth charts/lineups are unavailable; injury collection relies on official/media reporting and coverage varies. Discovery licenses are not a substitute for production terms. | **Tier B injury and odds validation**, or production candidate if coverage tests and commercial quote justify it. |
| [Sportradar NCAA Football API](https://developer.sportradar.com/football/docs/ncaafb-ig-overview) | Commercial schedules, play-by-play, statistics, rosters and broader sports content | Product/feed dependent | Trial access; production pricing is quote-based | Enterprise-grade candidate, but cost, redistribution rights, latency and historical availability require vendor confirmation. | **Tier C institutional alternative**, not an MVP dependency. |
| Official schools, conferences, NCAA and team communications | Rosters, transactions, depth charts, injury/availability reports, suspensions, opt-outs, coaching announcements | Current/future; historical archives inconsistent | Web/RSS/document ingestion; generally no uniform API | Highest authority for a specific report, but formats, release cadence and reuse terms vary. | **Tier B current structured-signal source.** Store references, timestamps and extracted facts; do not silently backfill old predictions. |
| Established reporters and major/local media | Availability, role, practice, coaching and contextual news | Current; archive and timestamp quality vary | Licensed feeds, RSS/web discovery, or manual research | Reliability is source-specific; corrections and rumor propagation require corroboration. | Tier 2/3 discovery and corroboration, not direct point adjustments. |
| [Open-Meteo](https://open-meteo.com/en/pricing) | Forecast, historical forecast, previous-run and single-run weather including wind, gust, precipitation, temperature and humidity | [Historical forecast](https://open-meteo.com/en/docs/historical-forecast-api) is strongest around 2021/22 onward; [previous runs](https://open-meteo.com/en/docs/previous-runs-api) and [single runs](https://open-meteo.com/en/docs/single-runs-api) vary by model, mostly recent | Free non-commercial allowance; commercial plans and exact prices vary, with professional historical/single-run access roughly starting near 99/month at research time | Model initialization time is not necessarily public availability time; provider notes multi-hour delays for global models. Attribution/licensing applies. | **Tier B weather.** Use archived forecast runs known at cutoff, never final observed/reanalysis weather as a historical forecast. |
| [NOAA NOMADS](https://nomads.ncep.noaa.gov/) | Raw operational forecast-model archives (for example GFS) | Model/product dependent | Public access, no commercial API subscription; GRIB processing/storage engineering required | Authoritative public model source, but reproducible run availability and operational parsing are nontrivial. | Low-cash/high-engineering alternative for point-in-time weather. |
| Recruiting services / draft and transfer datasets | Talent, recruiting classes, departures, portal movement | Vendor/source dependent | CFBD provides useful proxies; richer proprietary feeds are generally paid/terms-restricted | Player identity matching and retrospective corrections are substantial risks. | Start with CFBD fields; do not make a premium service an MVP blocker. |

## Data domains and minimum viable coverage

| Domain | MVP source | Required Phase 5B acceptance check | Upgrade path |
| --- | --- | --- | --- |
| Schedule, teams, score, venue, neutral site | CFBD games/teams | Stable IDs, FBS scope, kickoff history, cancellations, postseason, neutral-site correctness | SportsDataIO/Sportradar cross-check |
| Plays and team efficiency | CFBD raw PBP, checked against cfbfastR | 2014–2025 coverage by season/team; duplicate/correction policy; target game excluded | Commercial play feed if gaps materially bias evaluation |
| Coaches | CFBD coaches plus official announcements | Effective-date logic, interim roles, coordinator gap explicitly missing | Structured official-news pipeline |
| Recruiting/talent | CFBD recruiting | Team/player mapping, class-year availability known before season | Licensed recruiting provider if incremental signal proven |
| Transfers/returning production | CFBD player portal/returning production | Publication/effective timestamps; historical snapshot audit | Commercial roster feed or own roster-delta derivation |
| QB/player participation | CFBD box/PBP/roster proxies | Starter definition, snap/attempt proxy, identity continuity | SportsDataIO or enterprise participation feed |
| Injuries/availability | None required in first statistical baseline | Explicitly missing, not assumed healthy | Official reports then SportsDataIO/enterprise feed |
| Weather | Venue/indoor flag initially | No use of realized weather in historical decisions | Open-Meteo/NOAA archived forecast runs |
| Historical market | Existing forward snapshots plus purchased audit sample | Exact `as_of`, book/line identity, no future leakage, opening/24h/60m/close coverage | SportsDataIO/Sportradar historical quote |

## Historical-odds purchase decision

This purchase is important because all three questions below require point-in-time market data:

1. Did an independent model beat consensus at the same decision horizon?
2. Did a residual model learn incremental signal beyond the market?
3. Did a predicted edge move toward the close (CLV)?

CFBD betting lines may support exploratory season-level market benchmarks, but they must not be assumed to have exact publication histories. Before buying a large corpus, run a small The Odds API audit across 2020–2025 for NCAAF book availability, missing dates, event matching, snapshot semantics and closing coverage. If the audit passes, acquire only predeclared horizons: opening proxy, 24 hours, game-day morning, 60 minutes, and pre-start close. This bounds cost and matches the experiment design.

## Source ingestion contract

Every source extract or API response must have:

- provider and endpoint/product name;
- retrieval request without credentials;
- source-provided timestamp, when present;
- `effective_at`, `observed_at`, and `ingested_at` semantics;
- raw immutable object/hash and schema version;
- license/terms snapshot reference;
- coverage and parse warnings;
- correction/supersession linkage; and
- a flag distinguishing contemporaneously captured from reconstructed/backfilled data.

Backfilled data may train a football model when it represents facts that genuinely existed, but it cannot automatically prove strict historical availability. Reconstructed injury, roster, rating, or weather fields are ineligible for strict point-in-time replay until their availability rule is documented and tested.

## Research/news/injury signal sources

Use a four-tier evidence hierarchy:

1. official league/team reports, announcements, depth charts and transactions;
2. established national reporters and reliable team beat reporters;
3. major sports/local media;
4. social, rumor and community sources for discovery only.

The future normalized record should include league/team/player/event, signal type/status, source reference/type, reported/effective/observed/ingested times, reliability tier, corroboration state, extraction confidence, source text hash and signal schema version. An LLM may discover, extract, normalize, summarize and explain a cited record. It may not create an undocumented point adjustment or probability.

## Cost map

- **Free/open research:** SportsDataverse/cfbfastR; NOAA; official reports; CFBD's 1,000-call tier; existing already-paid Odds API capacity.
- **Cheap research:** CFBD $1–$30/month depending volume; targeted The Odds API historical work likely starts at $30/month; modest object storage later.
- **Likely paid production:** exact historical/live odds at suitable quota, a weather plan with archived forecast runs, and possibly SportsDataIO injury/odds feeds. Expect roughly $100–$300/month before negotiated products, but obtain current quotes.
- **Institutional:** SportsDataIO historical Vault/production or Sportradar feeds are quote-based and unnecessary until an experiment demonstrates that the cheaper corpus is the binding limitation.

The first money should go to exact historical odds, not a broad premium statistics bundle. Do not purchase injury or enterprise feeds until missingness/ablation results quantify their expected value.

## Unresolved source decisions

- Does a The Odds API sample provide sufficient NCAAF book and fixed-horizon coverage for 2020–2025?
- Are SportsDataverse upstream terms acceptable for internal commercial model training, or should it remain QA-only?
- Which CFBD fields are historically point-in-time versus retrospectively recomputed?
- Is official injury reporting sufficiently consistent to justify a normalized production feature?
- Is NOAA engineering preferable to paid Open-Meteo historical forecast access?
- What production redistribution/display rights are required for the eventual web product?
