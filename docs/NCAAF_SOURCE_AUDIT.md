# NCAAF Source, Coverage, and Identity Audit

Status: **Phase 5B-0 research audit completed on 2026-08-29; conditional go for Phase 5B-1. No model was trained and no production behavior changed.**

## Decision

Proceed with the smallest Phase 5B-1 facts pipeline, using CollegeFootballData (CFBD) as the primary MVP statistical source and public cfbfastR/SportsDataverse data as a coverage cross-check. The decision is conditional because this workspace had no CFBD or historical The Odds API credential. The authenticated provider audit and the bounded odds sample below remain acquisition gates; their results must not be invented or inferred from public metadata.

This audit supports building ingestion, identities, targets, manifests, and immutable research storage. It does **not** support training a model, claiming strict historical availability for reconstructed fields, purchasing a full odds corpus, or promoting any probability.

Approved operating constraints:

- the first practical workflow is one game-day-morning run before the first NCAAF kickoff;
- the exact fixed-time versus first-kickoff-relative convention remains gated on the odds sample;
- 60-minute and 24-hour cutoffs remain separate research horizons and their results must never be combined;
- 2025 is the locked test season and 2026 is prospective shadow evidence;
- CFBD starts on the free tier with immutable caching and bulk/year requests;
- injuries and weather are later feature/ablation tracks, not MVP blockers; and
- training remains offline, with PostgreSQL for identities/manifests/registry metadata and immutable Parquet/model-native artifacts for bulky data.

## Audit method and limitations

The audit used CFBD's official OpenAPI document and documentation, official GitHub release metadata and Parquet files from SportsDataverse, the published cfbfastR schema, and the current repository schema. Two reproducible research scripts live in `scripts/`:

- `audit_sportsdataverse_parquet.py` reads release metadata and Parquet footers and can scan selected columns from temporary downloads;
- `audit_cfbfastR_game_coverage.py` temporarily joins schedule and PBP game IDs and emits aggregate coverage without printing scores.

Temporary files are deleted. PyArrow is deliberately not an application dependency. The scripts do not read credentials or persist datasets in the repository.

The local environment contained neither `CFBD_API_KEY` nor `ODDS_API_KEY`. One unauthenticated CFBD request correctly returned HTTP 401. Therefore:

- no CFBD quota was consumed;
- endpoint response completeness, live headers, correction behavior, and actual rate-limit headers remain to be measured;
- no historical odds credits were spent; and
- no claim below presents a proposed odds sample as an executed sample.

## CFBD endpoint audit

The official OpenAPI specification was version `5.24.2` when inspected. It exposes the following relevant source families.

| Domain | Relevant operations | Identity and timing observations | Phase 5B disposition |
| --- | --- | --- | --- |
| Games/schedules | `/games`, `/calendar` | Game has integer ID, season/week/type, start date, `startTimeTBD`, completion, neutral/conference flags, venue and team IDs/names/classifications/scores. Most objects have no record-level publication/update timestamp. | Required first. Treat responses as reconstructed unless captured contemporaneously. |
| Teams/conferences | `/teams`, `/teams/fbs`, `/conferences/affiliations`, `/conferences/changes` | Stable integer team IDs are useful provider keys. Names, classification and membership can change by season. | Required first with effective-dated aliases/memberships. |
| Venues | `/venues` | Integer venue ID, timezone, coordinates, elevation, surface and dome fields. History of venue attributes is not proven by the current endpoint. | Required first; retain source vintage. |
| Plays | `/plays` | `year` and `week` are required. Play has string play/drive IDs, integer game ID, team display strings, period/clock, down/distance/yards, play type/text, PPA and wall-clock fields. Team IDs are absent on the play object. | Required first, joined through game/team mappings; weekly calls. |
| Drives | `/drives` | Year required; drive/game identifiers, team names, result, score, field position and clock fields. | Required first; year-level request if complete, otherwise documented weekly fallback. |
| Team/player game stats | `/games/teams`, `/games/players`, advanced game/team stats | Team stats contain team ID; player stats contain player IDs but the outer team object may be name-only. | Team game stats required; player stats useful later after identity audit. |
| Rosters | `/roster` | Player string ID, team name, year, position, and recruit IDs. | Later personnel release; not required for the first efficiency baseline. |
| Coaches | `/coaches`, profile/seasons/tenures | Integer coach/team IDs and tenure fields; appointment publication times are not proven. | Later preseason/personnel release, cross-checked against official announcements. |
| Recruiting/talent | `/recruiting/players`, `/recruiting/teams`, `/recruiting/groups`, `/talent` | Recruit has string ID and athlete ID. Ratings may be corrected retrospectively. | Later preseason prior, only with vintage/effective semantics. |
| Transfers | `/player/portal` | Transfer date exists, but the response lacks a stable player ID. | Later, with probabilistic name/team/date matching and review state. |
| Returning production | `/player/returning` | Team/season aggregates and percentages/PPA/usage have no demonstrated publication timestamp. | Later; ineligible for strict as-of use until vintage behavior is established. |

No pagination/cursor/limit parameters were present for these operations in the inspected OpenAPI. That is not proof that every live response is complete. The credentialed audit must record status, response size, row count, headers, source timestamp fields, request hash, warnings, and `/info` usage before and after each call.

### Earliest-season and correction conclusions

Public cfbfastR evidence establishes practical play-level coverage from 2014, but it does not prove CFBD's earliest complete season per endpoint. Phase 5B-1 must audit each selected CFBD operation across 2014–2025 and record the earliest season that passes field and identity checks.

Most inspected CFBD schemas lack `published_at` or `updated_at`. A historical API response retrieved now is a current reconstruction that may include corrections. Phase 5B must:

- store every raw response immutably with retrieval time and content hash;
- make corrections append/supersede rather than overwrite;
- label backfills `availability_mode=reconstructed`;
- apply conservative source-specific availability rules for exploratory football features; and
- reserve strict replay equivalence for records actually captured by the platform at the time or an archive with a defensible source-snapshot timestamp.

## Public PBP coverage findings

The official `espn_cfb_pbp` release advertised seasons 2004–2025 and was updated on 2026-08-03. The bounded audit scanned 2014–2025 because that is the proposed research window.

Across those 12 seasons:

- 1,819,153 play rows;
- 10,297 distinct PBP games;
- 609,910,942 compressed Parquet bytes (581.66 MiB);
- 1,558 null core EPA rows (0.0856%); and
- 57,144 null wall-clock rows (3.141%), including 50,981 in 2017 alone (32.78% of that season).

The schedule-to-PBP join used played regular/postseason games with at least one FBS participant, non-null scores, and no canceled/postponed status in the public unified schedule. It is a coverage proxy, not the canonical outcome rule because many union rows lack authoritative status.

| Season | Eligible FBS-participant games | With PBP | Coverage | Missing | FBS-vs-FBS missing |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 2014 | 868 | 851 | 98.04% | 17 | 14 |
| 2015 | 870 | 863 | 99.20% | 7 | 7 |
| 2016 | 873 | 856 | 98.05% | 17 | 14 |
| 2017 | 874 | 869 | 99.43% | 5 | 4 |
| 2018 | 884 | 881 | 99.66% | 3 | 2 |
| 2019 | 888 | 887 | 99.89% | 1 | 1 |
| 2020 | 570 | 564 | 98.95% | 6 | 5 |
| 2021 | 887 | 839 | 94.59% | 48 | 28 |
| 2022 | 896 | 857 | 95.65% | 39 | 29 |
| 2023 | 910 | 902 | 99.12% | 8 | 5 |
| 2024 | 919 | 901 | 98.04% | 18 | 15 |
| 2025 | 934 | 932 | 99.79% | 2 | 1 |
| **Total** | **10,373** | **10,202** | **98.35%** | **171** | **125 of 9,085 (1.38%)** |

Missing games are spread across many teams but cluster more heavily in 2021–2022. Model datasets must carry a missing-PBP reason and report coverage by season/team/classification; they must not silently treat missing games as average performance.

### Feature feasibility

The public schema and scans support deriving the following, subject to reconciliation against primary CFBD raw rows:

- EPA per play and pass/rush splits;
- success and explosive-play rates;
- havoc proxies;
- finishing-drives measures from scoring/opponent territory and drive fields;
- pace from plays, drives, game state, and game-clock fields;
- yards/play and yards/drive; and
- opponent-adjusted rolling features built strictly from prior games.

Important limitations:

- pass/rush EPA nulls are structurally expected on other play types;
- 2014–2016 core EPA gaps coincide largely with missing possession-team identity;
- 2017 wall-clock missingness makes wall-clock-dependent pace unsuitable as a universal feature; use a versioned plays/game or game-clock alternative and retain a quality flag;
- 2020 is a distinct COVID schedule/regime and must be segmented;
- PBP-derived end-season aggregates are retrospective and may not be used as historical as-of inputs; and
- every rolling transform must exclude the target game and future opponent results.

cfbfastR/SportsDataverse is a useful QA bootstrap and provides a rich derived schema, but its release date is not the historical availability time of each play. Its repository license does not by itself resolve rights to upstream ESPN data. Until an explicit use/redistribution review is complete, it should not be the durable production source or be redistributed.

## Canonical identity design

Phase 3 already has stable UUID `CanonicalEvent` rows and provider event mappings. Phase 5B-1 should extend rather than replace them.

### Team and conference identity

- Add a canonical program UUID independent of display name, conference, and classification.
- Store provider team mappings (`provider`, provider team ID, effective range, provenance, review state).
- Store effective-dated aliases/name history and season conference/classification membership.
- Renames and FCS/FBS reclassification do not create a new program solely because the label changed.
- Never merge teams by display string alone.

### Event identity

- Add nullable canonical home/away team foreign keys to existing events while retaining immutable decision-time display strings.
- Map CFBD game ID through the existing provider-event mapping boundary.
- Resolve by exact provider mapping first. A cross-provider candidate requires mapped team IDs, orientation, league/season, and a compatible kickoff revision.
- A schedule-time change updates/revises the event fact; it does not create a new game merely because kickoff moved.
- Conflicting teams, orientation, or duplicate candidates require review. No ambiguous event is model-eligible.
- Preserve neutral-site, season type, week, venue, schedule revision, matching method/confidence, and provenance.

### Venue, coach, and player identity

- Canonical venues receive provider mappings and effective-dated attributes/source vintage.
- Coaches retain provider IDs and effective tenures; interim and co-coach cases need explicit roles.
- Player identities are optional for the first baseline. CFBD roster/player IDs and recruit athlete IDs can seed mappings later.
- Portal rows lack a stable player ID and therefore require name, prior team, destination, position, date, and confidence/review—not deterministic name-only merging.

## Target and game eligibility contract

Primary labels are:

```text
margin = final_home_points - final_away_points
total  = final_home_points + final_away_points
```

Create labels only for official completed/final games with resolved canonical teams, a timezone-aware scheduled start, and valid nonnegative integer scores. Include regulation plus official overtime in the final score.

- Canceled games are excluded.
- Postponed games become eligible only when an eventual final record is reconciled; retain schedule revisions.
- Neutral-site games are included with the provider home/away orientation and an explicit neutral flag.
- Retain played scores for vacated results with a `vacated`/dispute flag; quarantine them from promotion until a policy review rather than rewriting history.
- Exclude exhibitions/all-star games, unresolved duplicates/teams, unresolved completion/status, and manual/forfeit anomalies unless a versioned rule admits them.
- Store games with at least one FBS participant and the opponent needed for strength calculations. The first primary model/promotion cohort is FBS-vs-FBS; report FBS-vs-FCS separately.
- Include postseason/bowls with season type in the row contract.
- Retain 2020 but report it as a separate regime.
- A kickoff-TBD record may later receive an outcome, but it cannot join a fixed horizon until a resolved historical kickoff exists.

## Point-in-time source classification

| Source/domain | Historical classification | Strict as-of eligibility |
| --- | --- | --- |
| Platform's Phase 3 contemporaneous Odds snapshots | Contemporaneously captured with observation and ingestion boundaries | Yes, under existing dual-boundary replay rules |
| The Odds API historical archive | Source-snapshot capable, but locally backfilled later | Yes for a separate `provider_archive` research policy using source snapshot time; not equivalent to contemporaneous local ingestion |
| CFBD games/PBP/drives/stats retrieved now | Reconstructed facts, potentially corrected | Exploratory with conservative postgame availability; not strict publication-time proof |
| CFBD teams/conference season facts | Reconstructable effective-season facts | Eligible when effective range is explicit; source vintage retained |
| CFBD venues | Current/static-looking reconstruction | Static attributes only unless historical validity is independently established |
| CFBD roster/coaches/recruiting/returning/portal | Retrospective or publication time unknown | Not strict until a field-specific vintage/effective audit passes |
| Public cfbfastR historical releases | Retrospective QA/bootstrap, reprocessed in 2026 | Not strict; occurrence timestamps are not release timestamps |
| Future injury/weather tracks | Not audited in this phase | Ineligible until coverage, publication-time, and ablation audits pass |

Never falsify `ingested_at` to make a backfill appear contemporaneous. Research replay must preserve source snapshot/effective time, actual local ingestion time, and availability mode as separate fields.

## Bounded historical-odds audit

Do not purchase or ingest the full corpus yet. The approved sample is designed to answer coverage questions at known cost while avoiding the locked 2025 season.

### Request design

- Sport: `americanfootball_ncaaf`
- Region: `us`
- Markets: `h2h,spreads,totals`
- Odds/date formats: `american`, `iso`
- Seasons: representative slates in 2020, 2022, and 2024 only
- Slates: early regular season, late regular season, and postseason in each season (nine slate dates)
- Morning candidates per slate: fixed 09:00 America/New_York and first scheduled kickoff minus three hours
- Anchor games per slate: two, selected before retrieval to cover major/non-major and FBS/FCS where available
- Anchor horizons: 24 hours, 60 minutes, and five minutes before kickoff as a closing proxy
- Boundary probes: four adjacent timestamp requests to confirm closest-prior behavior

This is 72 normal requests plus four probes: **76 requests**. Historical featured-market cost is `10 × regions × markets`, so one region and three markets costs 30 credits. Exact audit budget: **2,280 credits**.

Each response is a sport-wide slate, so the two morning requests assess every returned event; anchor horizons focus detailed continuity. Record request time, provider snapshot time, event/book/market counts, DraftKings/FanDuel/BetMGM presence, paired-market completeness, exact points, provider-event mapping, snapshot-at-or-before compliance, missingness, and errors. Never record the credential-bearing URL.

### Pass/fail rule

Before execution, freeze quantitative tolerances for:

- morning, 24-hour, 60-minute, and close-proxy event coverage;
- supported-book count and continuity;
- paired ML/spread/total completeness;
- exact-line and provider-event stability;
- source snapshot not after requested cutoff; and
- ambiguous/missing mapping rate.

Do not choose tolerances after seeing results. Keep horizons separate; do not fill a missing 60-minute observation with morning, 24-hour, or close data. The audit is an acquisition gate for market-aware experiments, not a gate for independent football baselines.

At current published pricing, the audit costs $0 incrementally if an existing plan has at least 2,280 credits; otherwise the smallest displayed historical-capable plan is approximately $30 for 20,000 credits. Confirm current account eligibility and prices before purchase. No purchase was made in this audit.

## CFBD call and storage budget

An immutable first import can fit the free 1,000-call monthly tier if calls are cached and bulked.

- 13 year-level source families × 12 seasons: approximately 156 calls;
- plays at approximately 16 calendar weeks × 12 seasons: approximately 192 calls, using `/calendar` for exact weeks;
- four global/range calls: approximately four calls;
- expected total: approximately 352; operational ceiling: 400;
- if drives require weekly fallback, approximately 180 additional calls, still below 1,000.

Every request uses a credential-free canonical request hash. A successful immutable response is never fetched again merely because a downstream transform is rerun. Start free; a small 5,000-call tier is justified only if measured retries, corrections, or endpoint granularity make the free tier materially less efficient.

Measured public PBP storage is 581.66 MiB compressed. Planning estimates—not measured commitments—are:

- CFBD compressed immutable raw JSON: 0.5–1.5 GiB;
- normalized core Parquet: 0.15–0.5 GiB;
- schedules/teams/manifests: under 50 MiB;
- feature matrices, OOF predictions, and model artifacts initially: 0.5–2 GiB; and
- practical initial local/object reserve: 3–5 GiB.

Simple Elo/Ridge artifacts should be well below 10 MiB; tree artifacts may be roughly 5–100 MiB. Record actual runtime, peak memory, rows, bytes, calls, and artifact sizes rather than treating these estimates as budgets to consume. No Spark, Databricks, distributed compute, or separate inference service is justified.

## Smallest legitimate Phase 5B-1 scope

Required now:

1. source manifests, credential-free request hashing, immutable raw cache, correction/supersession links;
2. CFBD calendar, games/results, teams/FBS classifications, conference affiliations, and venues;
3. CFBD plays, drives, and team game stats for 2014–2024 development data;
4. canonical programs, effective aliases/memberships, provider mappings, and additive links to Phase 3 events;
5. target reconciliation and explicit exclusion/missing-reason records;
6. PostgreSQL identity/manifest/index metadata plus partitioned immutable Parquet for bulky facts; and
7. a sealed 2025 holdout policy and prospective 2026 shadow capture.

Useful later, after the core facts pass reconciliation:

- rosters and QB/player participation proxies;
- coaches;
- recruiting/talent;
- transfers and returning production; and
- injury/availability and archived forecast weather, each with coverage tests and ablations.

Defer:

- cfbfastR season summaries as model inputs;
- full historical odds acquisition before the bounded audit passes;
- enterprise injury/statistics feeds without measured value;
- player-level/prop models;
- coordinators without a reliable source; and
- distributed ML infrastructure.

Phase 5B-1 should ingest 2014–2024 for development. The 2025 corpus may be physically sealed with restricted outcome access or its outcomes may be deferred; in either case, no 2025 score magnitude, feature, model, or hyperparameter decision may be consulted before the candidate and promotion rule are frozen. This audit used only score-field non-nullness to define the coverage denominator and inspected coverage/null metadata; it never printed, compared, or used 2025 score magnitudes or model performance. That is not material model development, so the intended holdout remains clean.

## Go/no-go gates

**Go now:** build the versioned source cache, identities, targets, and 2014–2024 facts pipeline; verify it against the public audit.

**Must pass before claiming Phase 5B-1 source completion:** credentialed CFBD response audit, recorded terms snapshot, field/season coverage report, corrections test, row-count reconciliation, and exact free-tier call log.

**Must pass before Phase 5B-7 market-aware work:** the frozen 2,280-credit historical-odds sample and a distinct provider-archive replay policy.

**Must pass before model promotion:** frozen folds/thresholds, untouched 2025 evaluation, prospective 2026 shadow evidence, leakage checks, calibration, and same-horizon market comparisons where applicable.

## Genuinely unresolved decisions

- Exact morning convention: fixed 09:00 ET or a rule relative to the day's first kickoff. Resolve only from the frozen coverage audit.
- Quantitative odds-audit pass/fail tolerances, frozen before retrieval.
- Whether SportsDataverse's upstream ESPN-derived data is acceptable for internal commercial training or remains QA-only.
- Source-specific conservative publication delays for reconstructed CFBD fields after the credentialed audit.
- How to enforce the 2025 outcome access seal operationally.
- Numeric proper-score/calibration/sample/segment promotion thresholds, frozen before opening 2025.
- Whether one locked season plus one prospective shadow season is enough for paper influence or a longer shadow is required.
- Future injury-source, weather-source, and production redistribution rights decisions; none blocks the first baseline.

## Primary references

- [CFBD API documentation](https://collegefootballdata.com/api/docs)
- [CFBD API tiers](https://collegefootballdata.com/api-tiers)
- [CFBD terms](https://collegefootballdata.com/terms)
- [SportsDataverse PBP release](https://github.com/sportsdataverse/sportsdataverse-data/releases/tag/espn_cfb_pbp)
- [cfbfastR dataset schema](https://github.com/sportsdataverse/cfbfastR-cfb-data/blob/main/DATASETS.md)
- [The Odds API historical data](https://the-odds-api.com/historical-odds-data/)
- [The Odds API historical guide](https://the-odds-api.com/liveapi/guides/v4/)
