# NCAAF Feature Catalog

Status: **Phase 5B-2 feature contract implemented; predictive value untested.** A materialized feature is a reproducible research input, not an approved predictor. Phase 5B-3 and later must measure stability, incremental forward value, calibration, and missingness before any promotion.

## Implemented Phase 5B-2 release

`ncaaf-efficiency-point-in-time-v1` transforms the immutable Phase 5B-1 source corpus into content-addressed normalized Parquet facts and one feature row per eligible game and declared horizon. Its registry hash is `0d4d5b3e9996c5682bc6e5366f70c4a82fd80fce8a3ebaa8db7a6ee22bc446ad`. The dataset hash is recorded in the dataset manifest and QA report rather than embedded as a permanent feature definition.

Implemented source metrics are offensive and defensive PPA/EPA proxy per play, pass and rush PPA, success rate, explosive-play rate, yards/play, yards/drive, points/drive, plays/game, drives/game, and a conservative havoc proxy. Success is at least 50% of yards-to-go on first down, 70% on second, and 100% on third/fourth. Explosives are passes of at least 20 yards or rushes of at least 10. Havoc counts sacks, interceptions, and opponent fumble recoveries over defensive scrimmage plays. These definitions are versioned research conventions, not claims that a provider field is a production-grade proprietary metric.

Each team metric exposes prior-three, prior-five, season-to-date, prior-season/program, and blended values. The blend uses current-season weight `n / (n + 3)` and prior weight `3 / (n + 3)`; missing prior program history falls back to the prior-only population mean and remains visible through depth/coverage fields. Phase 5B-3 may compare these columns, but must not silently replace their definition.

Opponent adjustment `prior-only-opponent-residual-v1` is:

```text
team last-five raw metric
- mean(prior-only opponent opposite-unit strength at each prior matchup)
+ prior-only population mean
```

The opponent state is computed at the target row's historical `as_of`. It never uses results after that cutoff or an end-of-season rating. Adjustment availability and contributing depth remain explicit.

The three independent horizons are `game_day_morning`, `24_hours_before_kickoff`, and `60_minutes_before_kickoff`. Morning supports the still-candidate `fixed_0900_et_candidate_v1` and `first_kickoff_minus_3h_candidate_v1` policies; no final operational convention was selected. Reconstructed CFBD postgame facts become eligible only at scheduled kickoff plus 24 hours under `cfbd-reconstructed-kickoff-plus-24h-v1`; occurrence, effective/available, and actual local ingestion times remain distinct.

Missing is never converted to zero. Rows separately report prior-game depth, PBP/drive/stat coverage, wall-clock coverage, reconstructed-source status, opponent-adjustment availability, and context. The 2020 season is retained with a regime indicator so later ablations can include, flag, or exclude it without rewriting facts.

## Feature contract

Every materialized feature requires:

```text
feature_name, feature_version, entity/event key, value,
effective_at, observed_at, ingested_at, as_of,
lookback/window, source IDs, transformation version,
coverage flag, missing reason, quality/provenance status
```

Rolling features include only games/plays completed before `as_of`; the target game is excluded. Opponent adjustments may use only opponent information available by the same cutoff. Imputation is fitted inside the chronological training fold, and missingness indicators remain available to the model.

Abbreviations below: `N` naive baseline, `E` Elo/rating, `R` Ridge/Elastic Net, `T` boosted trees, `B` Bayesian/hierarchical, `C` component-score. Raw/adjusted fields should not share a feature name.

## Team efficiency

| Feature family | Definition / variants | Source and availability | Expected signal | Leakage / missing-data policy | Candidate models |
| --- | --- | --- | --- | --- | --- |
| EPA per play | Offense and defense; all/pass/rush; rolling season and exponentially weighted | Derive from CFBD/cfbfastR PBP after each completed game | Down/value-aware efficiency and style | Do not use provider end-season aggregate for earlier weeks. Flag seasons/plays with incomplete fields. Opponent-adjust separately. | R,T,B,C |
| Success rate | Share of plays meeting a versioned success rule; offense/defense/pass/rush | Derived PBP, pregame rolling | Consistency distinct from explosives | Freeze rule/version; exclude garbage-time only under a documented rule; missing PBP remains missing | R,T,B,C |
| Yards per play | Offense/defense/pass/rush, raw and adjusted | PBP/box, known postgame | Transparent efficiency floor | Sensitive to game state/opponents; never substitute season-final value | N,R,T,C |
| Explosive-play rate | Share above versioned pass/rush yard thresholds | PBP, known postgame | Tail scoring potential | Threshold is a research parameter, frozen pre-holdout; sparse early-season uncertainty | R,T,C |
| Finishing drives / points per opportunity | Points per trip crossing a versioned opponent-yard threshold | Drives/PBP | Converts field position into scores | Provider drive gaps and end-game kneels; denominator and threshold versioned | R,T,C |
| Third/fourth down | Conversion and defensive prevention, attempt counts | PBP/box | Situational efficiency | High variance/small denominators; use shrinkage and counts | R,T,B,C |
| Red zone efficiency | TD/points per red-zone trip | PBP/box | Scoring conversion | Small sample, provider definition differences; heavily shrink or defer | T,B,C |
| Sack/pressure/havoc | Sack rate allowed/created, tackles for loss, passes defended, turnovers forced where reliably observed | PBP/team stats | Disruption and protection mismatch | Pressure fields may lack coverage; turnover outcomes regress strongly; include opportunity denominators | R,T,C |
| Tempo | Neutral/game-state adjusted seconds per play or plays per game | PBP/box | Total possessions, total scoring | Raw plays conflate pace and opponent/game script. Public audit found 50,981 missing wall clocks in 2017, so wall-clock pace cannot be universal; use a versioned plays/game or game-clock fallback plus quality flag. | R,T,C |
| Drive efficiency | Points, success, starting field position per drive | Drives/PBP | Possession-level scoring | Missing drive boundaries/corrections; exclude target game | R,T,C |

Use differences (`home - away`) as primary margin inputs and sums/interactions as primary total inputs. Keep raw offense/defense components for trees and component-score models. Compare rolling windows, exponentially weighted history and hierarchical shrinkage under the same folds; do not search dozens of windows on the locked holdout.

## Strength and schedule adjustment

| Feature | Definition/source | Availability and leakage control | Missing/adjustment | Models |
| --- | --- | --- | --- | --- |
| Pregame Elo / power rating | Sequential rating updated after games | State is snapshotted before kickoff; MOV update is versioned | New teams receive regressed conference/FBS prior with uncertainty | N,E,R,T,B |
| Opponent-adjusted efficiency | Iterative/ridge adjustment of team efficiency for opponents faced | Refit using only games completed by `as_of`; no future opponent results | Early disconnected schedules use hierarchical shrinkage and connectivity flag | R,T,B,C |
| Strength of schedule | Aggregate pregame opponent strength, not final opponent record | Same cutoff as row | Preserve opponent count/dispersion | N,E,R,T |
| Conference latent effect | Partial pooling, learned within each training fold | No full-season retrospective conference rank | Unknown/reclassified teams shrink to FBS mean | E,R,T,B |
| Recency-weighted strength | Fixed/learned decay over prior games/seasons | Decay selected on inner forward folds | Pair value with effective sample size | N,E,R,T,B |

Raw win/loss record is not team quality: schedules differ, one-score outcomes are noisy, and it discards play/point information. It can be retained only as a naive diagnostic and may not receive privileged treatment.

## Personnel and offseason state

| Feature | Definition | Candidate source / timestamp | Expected signal | Leakage and missingness | Models |
| --- | --- | --- | --- | --- | --- |
| QB continuity | Returning projected starter; prior attempts/snaps; starts and passing efficiency | Rosters/PBP/official designation known by `as_of` | Most influential continuity proxy | Starter labels are mutable; store report timestamp and alternatives. Never backfill Week 1 with later starter knowledge. | R,T,B,C |
| Returning production | Returning share of offense/defense production, versioned formula | CFBD or own roster/PBP join, publication/effective date | Preseason prior quality | Audit whether historical endpoint is retrospective; keep data-vintage flag | E,R,T,B,C |
| OL / starter continuity | Returning starts/snaps by unit | Commercial/participation source if reliable | Protection/rush cohesion | Likely incomplete; Tier B, missing ≠ zero | T,B,C |
| Skill-player availability | Expected WR/RB participation/role | Official/news structured signals | Passing/rushing capacity | Historical coverage bias; use only after timestamped pipeline and ablation | T,B,C |
| Defensive availability | Expected starter/position-group participation | Official/news/commercial | Matchup and depth | Same; position uncertainty and corroboration required | T,B,C |
| Transfer gains/losses | Count/value/experience by position, joined to roster before season | CFBD portal plus roster effective dates | Rapid roster turnover | Portal entry is not destination or role; identity resolution and missingness explicit | R,T,B |
| NFL/graduation departures | Prior contribution leaving roster | Rosters, draft, eligibility known pregame | Lost production | Eligibility/UDFA data incomplete; avoid double counting returning production | R,T,B |
| Recruiting/talent | Multi-year roster/class composite and incoming class | CFBD recruiting, known signing/publication date | Prior for unobserved player quality | Service ratings change retrospectively; retain vintage when possible | E,R,T,B |
| Injury/availability signal | Structured player/team status, reliability/corroboration, position and expected role | Official reports/news observed by cutoff | Late roster information | Do not translate into hand-set points. Missing means unknown; model only after adequate history | T,B,C |

## Coaching and system

| Feature | Definition | Source/time | Risk / treatment | Models |
| --- | --- | --- | --- | --- |
| Head coach change/tenure | Effective appointment and games/seasons in role | CFBD + official announcements | Interim/co-coach roles; possible selection bias | E,R,T,B |
| OC/DC change/tenure | Effective coordinator role and continuity | Official/team data, Tier B | Historical coverage gaps; missing indicator | R,T,B,C |
| Scheme continuity | Stable, reproducible scheme taxonomy if a licensed/reliable source exists | Not MVP | Subjective labels can leak narrative; defer until validated | T,B,C |

Coaching changes may alter preseason priors or uncertainty, but there is no automatic positive/negative point adjustment.

## Situational, venue and schedule

| Feature | Definition/source | Timing / leakage | Treatment | Models |
| --- | --- | --- | --- | --- |
| Home / neutral field | Canonical venue and neutral flag | Schedule state as of cutoff | Learn HFA globally and possible partial pooling; do not assume fixed three points | N,E,R,T,B,C |
| Travel distance | Geodesic campus/venue distance | Stable venue coordinates plus schedule | Log/bucket transforms; neutral sites handled separately | R,T,C |
| Time-zone shift / body-clock | Origin and local kickoff zones | Schedule/kickoff as of cutoff | Interaction with kickoff time; hypothesis only | R,T |
| Altitude | Venue elevation | Static venue metadata | Interaction with travel/conditioning; sparse extremes | R,T |
| Rest / short week / bye | Days since prior game | Point-in-time schedule | Cancellations and prior postseason boundary handled | R,T |
| Consecutive road games | Pregame schedule sequence | Point-in-time schedule | Candidate only; avoid narrative overfit | T |
| Rivalry | Versioned pair list, not text label | Static metadata | Included only if forward evidence survives multiplicity control | T |
| Indoor / surface | Venue roof and field surface | Effective-dated venue | Missing/roof status flag | R,T,C |

## Weather

Use the latest forecast run actually available at the prediction cutoff, joined by venue coordinates and kickoff time:

- sustained wind and gust distribution;
- precipitation probability/type/amount;
- temperature, humidity and heat-index/wind-chill transforms;
- extreme heat/cold flags learned from data;
- indoor/roof status; and
- forecast age, model/run ID and uncertainty/ensemble spread.

Candidate interactions include wind × pass rate/depth, precipitation × surface, temperature × tempo, and weather × kicking reliance. `rain = under` and other hand rules are prohibited. Realized postgame weather and reanalysis are not historical forecast features. Older seasons without point-in-time forecasts remain missing or form a separate sensitivity cohort.

## Matchup and style interactions

Predeclare a compact set before tree-model search:

- offense pass rate × opponent pass EPA/success/explosive prevention;
- rush rate × rush defense;
- explosive offense × explosive prevention;
- offense sack/pressure allowed × defensive havoc/sack creation;
- offense pace × opponent pace and defensive play volume;
- finishing-drives offense × finishing-drives defense;
- run/pass split mismatch; and
- turnover-worthy/havoc opportunity rates, not raw turnover margin.

Linear models receive explicit symmetric interactions. Trees may learn nonlinear versions, but interaction importance must be stable across chronological folds.

## Market and data-quality features

These appear only in market-as-feature or residual experiments:

- fixed-horizon consensus spread, total and moneyline probability;
- consensus book count, dispersion and outlier warnings;
- time to kickoff and snapshot age;
- opening-to-current movement separated from best executable price;
- missing-book/provider-composition indicators; and
- football feature completeness and freshness.

The exact offered price being evaluated cannot also be mislabeled as independent fair probability. Closing prices are outcomes/benchmarks only for earlier horizons, never inputs.

## Features not trusted by default

| Candidate | Why it is dangerous | Permitted treatment |
| --- | --- | --- |
| Raw W/L record | Schedule and one-score noise; loses margin/play information | Naive diagnostic only |
| ATS record | Market-relative noisy outcome; selection and multiple-testing risk | Predeclared research experiment only, never an automatic feature |
| Day-of-week/trend queries | Huge researcher degrees of freedom and tiny conditional samples | Exclude from initial catalog |
| Head-to-head history | Usually different players/coaches and few games | Exclude unless roster-continuity hypothesis is predeclared |
| Winning/losing streak | Mostly duplicates recent results and encourages recency narratives | Let versioned recency features compete instead |
| Historical betting trend | Nonstationary books/markets and data-mined rules | Requires independent forward replication |
| Raw turnover margin | High outcome variance and fumble/interception luck | Use opportunity/pressure variables and shrink turnover rates |
| Rankings/polls | Human/market information with circularity and brand bias | Market-aware challenger only, with publication timestamp |

Feature importance is descriptive, not causal proof. A feature remains only if ablation and forward evidence show stable incremental value without creating unacceptable availability or explanation risk.

## Early-season feature policy

Before Week 0, rely on regressed prior strength, multi-year program information, recruiting/talent, returning production, QB and coach continuity, transfers/departures, plus explicit coverage flags. As current-season plays accumulate, update features by effective sample size rather than a hard Week 4 switch. Store both preseason-prior and current-season components so the model can learn their weights.

Weeks 0–3 require wider reported epistemic uncertainty and segmented evaluation. Missing roster/QB data must widen uncertainty or trigger abstention; it must never silently become league average without a missingness flag.

## Feature-set releases

- `ncaaf_basic_v1`: pregame Elo, regressed scoring/efficiency, home/neutral, rest, effective sample and missingness.
- `ncaaf-efficiency-point-in-time-v1`: **implemented in Phase 5B-2** with the bounded corpus-supported efficiency, rolling, prior, context, quality, and opponent-adjustment definitions above.
- `ncaaf_efficiency_v2`: proposed extensions such as finishing-opportunity and more robust game-state metrics after source-specific coverage studies.
- `ncaaf_preseason_v1`: recruiting/talent, returning production, QB and coaching continuity, transfers/departures with provenance.
- `ncaaf_market_v1`: fixed-horizon consensus state and quality, for residual/market-aware candidates only.
- `ncaaf_weather_v1` and `ncaaf_availability_v1`: deferred until historical timestamp coverage clears an explicit audit.

Each release has a schema, data manifest, column semantics, allowed horizons and leakage tests. Later releases do not overwrite earlier matrices.
