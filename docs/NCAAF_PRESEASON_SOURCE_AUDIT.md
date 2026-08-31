# NCAAF Preseason and Personnel Source Audit

Status: **Phase 5B-6 source audit completed on 2026-08-30.** The plan below was frozen before collection. Results come from credential-free manifests and immutable cached responses. This work is offline research and cannot alter production pricing or recommendations.

## Research question and fixed universe

Determine whether point-in-time preseason/personnel context adds stable chronological out-of-sample signal beyond the Phase 5B-3/5 baselines, with Weeks 0–3 primary and 2014–2024 as the development universe. The 2025 locked season remains inaccessible and 2026 remains prospective shadow evidence.

The existing efficiency dataset, folds, point models, and conclusions remain frozen comparison baselines. No historical football corpus is re-downloaded.

## Predeclared source plan

CFBD is the durable structured source. All requested historical products are reconstructed extracts retrieved in 2026. Provider retrieval time is retained honestly; no local timestamp is backdated. A fact may enter a historical feature only under the field-specific conservative reconstruction policy below.

| Family | CFBD product | Planned seasons/calls | Historical semantics | Earliest experiment season | Primary use | Pre-collection disposition |
| --- | --- | ---: | --- | ---: | --- | --- |
| Returning production | `/player/returning?year=` | 2014–2024, 11 | Team-season aggregate; provider exposes no publication timestamp and methodology vintage may be retrospective | coverage-audit result | offense/total/passing/rushing/receiving retained production and usage | Audit and admit only with explicit reconstructed flag |
| QB continuity | `/stats/player/season?year=&category=passing` plus `/roster?year=&classification=fbs` | 22 | Prior-season production is known after the prior season; roster membership is a reconstructed season roster, not a Week 1 depth chart | coverage-audit result | prior leading passer retained, attempt/yards share, known/unknown continuity | Conservative proxy; never infer actual Week 1 starter from later starts |
| Transfers | `/player/portal?year=` | 2014–2024, 11 | `transferDate` is the only dated field; destination may be null and player IDs are absent | coverage-audit result | in/out/net counts, rating/stars, position groups, QB movements | Count only records whose transfer date is at/before the game cutoff; unresolved names do not create player identities |
| Recruiting | `/recruiting/teams?year=` | 2014–2024, 11 | Class ranking is reconstructed and may reflect provider corrections; exact historical publication vintage is unavailable | coverage-audit result | class rank/points and prior-only multiyear aggregates | Use as reconstructed preseason-static context with quality flag |
| Talent | `/talent?year=` | 2014–2024, 11 | 247Sports team talent composite returned retrospectively; exact historical publication timestamp/vintage unavailable | coverage-audit result | roster talent level | Use only where coverage is adequate and mark reconstructed |
| Head coach continuity | `/coaches?minYear=2014&maxYear=2024` | 1 bounded query | Provider supplies coach IDs and nested team-season records; announcement/publication time and coordinator history are not proven | 2014 | change and consecutive-season tenure | Admit season-effective continuity with reconstruction flag; do not score coach quality |
| Coordinator continuity | no verified CFBD historical coordinator product | 0 | Not available from the selected structured source | n/a | OC/DC changes | Defer; no name scraping or display-string inference |
| Roster continuity | `/roster?year=&classification=fbs` | included above | Stable provider player IDs where present; historical roster vintage is reconstructed | coverage-audit result | year-over-year ID overlap by position and roster count | Transparent overlap only; not snap/returning-start precision |
| Prior production concentration | prior `/stats/player/season` rows | included above | Prior-season player totals are postgame facts and become available under the existing kickoff-plus-24h policy | coverage-audit result | leading passer share and player concentration proxies | Limited to source-supported passing fields |

The maximum credentialed budget is 69 calls: 66 season-product requests, one bounded coach request, and `/info` before and after. Identical cached requests cost zero provider calls on rerun. The execution command must print this plan and require `--execute`; it rejects 2025+ without explicit holdout authorization.

## Frozen point-in-time policies

Every normalized row carries program ID, season, source, effective time, available time, actual ingestion time, source manifest/hash, policy version, reconstruction state, and quality/missingness.

- `preseason-reconstructed-season-start-v1`: reconstructed returning production, recruiting, talent, and roster facts become available at the target season's first scheduled FBS game kickoff. This is conservative for within-season use but **does not prove** the value was published before an operational Week 0 run; strict-live-fidelity is false.
- `portal-transfer-date-v1`: a portal row becomes available no earlier than its provider transfer date. Missing dates remain unavailable, not season-start imputed.
- `coach-effective-season-v1`: CFBD supplies nested team-season records in the audited product; v1 uses the season-start boundary and remains reconstructed rather than inventing an announcement date.
- Prior-season player production is associated only with the following season's continuity fact and becomes eligible at that following season's start boundary. The source season is therefore complete well before use, but historical ingestion remains the real 2026 time.

These policies permit a reconstructed offline ablation, not a claim of contemporaneous historical replay. Any later source with genuine publication snapshots receives a new availability-policy version.

## Frozen feature families

The new registry version is `ncaaf-preseason-personnel-v1`; the combined contract is the immutable Phase 5B-2 efficiency set plus this registry. Candidate families are:

1. returning production and returning usage;
2. QB continuity and prior passing-production share;
3. transfer in/out/net counts and source-supported rating/position aggregates;
4. recruiting class rank/points and prior-only multiyear aggregates;
5. team talent composite;
6. head-coach change/tenure/interim/continuity;
7. roster player-ID overlap, position-group overlap, and coverage;
8. prior passing-production concentration; and
9. explicit missingness, reconstruction, identity, and coverage indicators.

OC/DC changes, returning starts/snaps, defensive player production, subjective coach ratings, and hindsight starter labels are excluded unless a later source audit establishes reliable structured history.

## Frozen experiment and advancement plan

Use the existing expanding chronological folds and evaluate each horizon independently. Primary evidence is Weeks 0–3, reported separately for Weeks 0–1 and 2–3; Weeks 4–6 and 7+ measure decay. Models are limited to:

- frozen chronological power rating versus one bounded learned preseason-prior variant;
- frozen Ridge full-v1 and total no-opponent-adjustment versus preseason-augmented Ridge; and
- frozen CatBoost total challenger versus one preseason-augmented configuration.

Predeclared ablations are returning production, QB, transfers, recruiting/talent, coaching, roster continuity, all preseason families, and all-minus-family. Missingness and source quality remain model inputs/segments, never silent zeros.

A candidate advances only when all applicable conditions hold:

1. paired Weeks 0–3 MAE improves by at least 0.20 points and RMSE does not worsen;
2. the season-block 95% interval for paired MAE improvement is directionally favorable, or the point gain is at least 0.35 with no material season instability;
3. neither Weeks 0–1 nor 2–3 worsens by more than 0.15 MAE;
4. 2024 validation improvement is directionally consistent with development evidence;
5. no material regression appears in 2020, 2021–2022, or low-quality/reconstructed segments;
6. the result is deterministic and survives the frozen family ablations; and
7. complexity and operational latency are proportionate to the gain.

Probability re-evaluation is limited to a point candidate that clears these gates. It uses the existing empirical-discrete margin or empirical-residual total method and cannot trigger market, EV, staking, or recommendation integration.

## Credentialed audit result

The bounded run consumed exactly **68 billable calls**: CFBD `/info` usage increased from 416 to 484. The planned logical request set was 69, but the initial and resumable `/info` reads reused cached manifests; a final explicit `/info` refresh established the post-run count. One request timed out locally and was retried safely; the provider accounting proves it did not add a call beyond the 68 total. The account remained on the Free tier (`1,000` monthly shared calls) with `516` calls remaining. No credential, authorization header, or credential-bearing URL entered a request hash, filename, manifest, report, or log.

| Product | Rows | Response bytes | Coverage finding |
| --- | ---: | ---: | --- |
| Returning production | 1,421 | 460,767 | 125–133 mapped FBS teams per season, 2014–2024 |
| Transfer portal | 9,923 | 2,094,030 | zero rows for 2014–2020; useful only for 2021–2024 |
| Recruiting team rankings | 2,337 | 140,711 | 177–238 provider teams per season; broader than the FBS model cohort |
| Team talent | 2,141 | 106,855 | no 2014 rows; 2017 and 2024 have visibly lower coverage and remain flagged |
| Historical rosters | 168,165 | 50,247,975 | 128–134 mapped FBS teams per season, sufficient for ID-overlap proxies |
| Player passing statistics | 58,597 | 10,150,735 | 3,269–7,399 stat rows per season; player IDs support prior-leading-passer matching |
| Coaches | 357 coach records | 402,963 | nested seasons map 128–134 FBS programs per season |

The immutable raw source response footprint for these products is 63,604,036 bytes before gzip. The normalized preseason/personnel layer contains 2,837 program-season rows and 30,373,248 bytes of content-addressed Parquet artifacts. The feature artifact contains 8,277 games per horizon. Team-side availability is 99.65% at 24 hours, 99.94% at 60 minutes, and 99.70% at game-day morning under the reconstructed season-start rule.

## Coverage decisions and limitations

- Returning production is admitted as a reconstructed team-season aggregate. Its provider methodology/publication vintage is not proven, so `strict_live_fidelity=false` is mandatory.
- Roster and player-stat identifiers overlap sufficiently for a transparent prior-leading-passer continuity proxy. This does **not** identify the announced Week 1 starter.
- Portal features are structurally unavailable before 2021 and are never zero-imputed into earlier seasons. Only provider-dated moves on or before the target season's first kickoff are admitted in v1.
- Recruiting and talent remain reconstructed static context. The missing 2014 talent product and low-coverage 2017/2024 vintages remain explicit missingness, not filled values.
- Coach continuity uses exact provider team mappings and consecutive season records. It does not reconstruct announcement dates, interim timing, coordinator changes, or subjective coach quality.
- CFBD has no verified structured historical coordinator product in the selected contract. Coordinator features are deferred rather than scraped or inferred.
- The resulting experiment can test reconstructed historical usefulness, but cannot claim strict contemporaneous historical availability. A later true-vintage archive requires a new source and availability-policy version.
