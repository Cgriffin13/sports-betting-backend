# NCAAF Feature Dataset Report

Status: **Phase 5B-2 development feature corpus built and validated; no model was trained.** The machine-readable companion is `reports/NCAAF_FEATURE_DATASET_2014_2024.json`.

## Frozen build

| Item | Value |
| --- | --- |
| Development seasons | 2014–2024 |
| Eligible FBS-vs-FBS target games | 8,277 |
| Explicit horizons | 24 hours, game-day morning candidate, 60 minutes |
| Model-ready rows | 24,831 |
| Normalized fact rows | 1,695,709 plays; 238,898 drives; 579,985 long-form team-stat facts; 24,222 games |
| Team-game metric rows | 47,866 |
| Availability policy | `cfbd-reconstructed-kickoff-plus-24h-v1` |
| Feature set | `ncaaf-efficiency-point-in-time-v1` |
| Feature-set hash | `0d4d5b3e9996c5682bc6e5366f70c4a82fd80fce8a3ebaa8db7a6ee22bc446ad` |
| Normalized dataset hash | `e93437eb82a2063e086befe2568049fe2be04d39c63393f7db2c9d29501be8ed` |
| Feature dataset hash | `b2f7444e2a7451d90c9078fb3b694d1586b1d30dd7f9c3a60b869381532b8bfe` |
| Full build runtime | 70.791 seconds |
| Peak working set | 613,539,840 bytes (about 585 MiB) |
| Historical provider calls | 0 |

The three horizon partitions contain exactly 8,277 rows each. They share one schema and never substitute one horizon for another. The game-day-morning build currently uses the explicitly named `first_kickoff_minus_3h_candidate_v1` policy for research reproducibility; this is not the final operational convention. The fixed 09:00 ET candidate is also supported. The historical-odds audit still decides which convention is operationally supportable.

## Artifact architecture

The ignored local pipeline is:

```text
Phase 5B-1 raw JSON.gz + SQL identity/manifests
  -> normalized/schema=ncaaf-normalized-facts-v1/dataset=.../season=YYYY/*.parquet
  -> features/schema=ncaaf-team-game-metrics-v1/dataset=team_game_metrics/season=YYYY/*.parquet
  -> features/schema=ncaaf-feature-dataset-v1/dataset=model_ready_games/*.parquet
```

Normalized Parquet occupies 43,493,124 bytes. Team-game and model-ready feature artifacts occupy 27,532,914 bytes. Every artifact records exact file SHA-256, schema hash, row count, transformation/schema version, source manifest IDs/content hashes, and byte size. Two consecutive full rebuilds from the same sources/configuration reproduced row order, schemas, feature-set hash, dataset hash, manifest ID, and content-addressed paths. Build time is metadata and is excluded from deterministic identity.

PostgreSQL remains the source of canonical identity/manifests and the application database. Millions of plays and the feature matrix are not added as ORM rows. No migration was required for 5B-2.

## Feature families

Implemented v1 families are:

- CFBD PPA per play for offense, defense allowed, pass, and rush;
- success rate using explicit down/distance thresholds;
- explosive-play rate (20+ pass yards or 10+ rush yards);
- yards/play, yards/drive, and points/drive;
- plays/game and drives/game as robust pace proxies;
- a documented sack/interception/opponent-fumble-recovery havoc proxy;
- previous-3, previous-5, season-to-date, and conservative prior/current blends;
- prior-only opponent residual adjustment for offensive PPA, defensive PPA allowed, success rate, and yards/play;
- neutral site, conference/classification, conference-game, season/week, postseason, rest, venue identity, and explicit 2020 regime context; and
- data-depth, reconstructed-source, PBP/drive/stat/wall-clock coverage, and opponent-adjustment quality fields.

No wall-clock tempo feature is required. Wall-clock coverage remains a quality field because 2017 is known to be incomplete. Current venue attributes are normalized with `current_vintage_not_assumed_historical` and are not injected as historical weather/surface truth.

## Coverage and missingness

Blended EPA, drive, pace, success/explosiveness, and yards families have approximately 99.94% cell coverage. The residual missing cells are concentrated at the beginning of 2014, before the development corpus has prior history. They remain null; they are not converted to zero.

Opponent-adjusted cells have 94.03% coverage; both teams have opponent-adjustment support on 23,235 of 24,831 rows (93.57%). This lower coverage is expected because early rows and unresolved opponent context cannot support a schedule adjustment. The model-ready matrix carries availability flags rather than silently substituting raw strength.

Mean prior-history coverage across rows is roughly:

- PBP: 97.24% home / 97.02% away;
- drives: 97.43% home / 97.20% away; and
- team statistics: 98.27% home / 98.13% away.

Early-season current-game-depth counts across team sides are 2,727 with zero current games, 3,027 with one, 2,925 with two, 111 with three, and 2,604 with four or more. The fixed blend uses `n/(n+3)` current-season weight and `3/(n+3)` prior weight. Priors use available prior-three-season program history and fall back to the prior-only population mean. This is a transparent baseline policy, not a trained coefficient.

## Point-in-time and leakage guarantees

For reconstructed football facts, `effective_at` is the source occurrence/kickoff boundary, `available_at` is kickoff plus 24 hours, and actual 2026 local ingestion remains separate. The builder admits facts only when effective and available times are no later than `prediction_as_of`. It never falsifies ingestion time.

Automated tests prove:

- the target game's plays and score do not alter its features;
- later games and future opponent outcomes cannot alter earlier rows;
- facts/corrections available after the cutoff cannot leak backward;
- all horizons are explicit and game-day slate grouping uses the Eastern calendar day;
- 2025 is rejected by ordinary builders;
- chronological order and feature values are deterministic; and
- same-source rebuilds preserve hashes and artifact integrity.

Targets remain labels in the row (`margin`, `total`) and are never feature inputs.

## 2020 and folds

The corpus retains 2020 with `covid_2020_regime=true` on 1,602 horizon rows. Later experiments may include it normally, include the indicator, or exclude it in a predeclared ablation; 5B-2 does not choose among them.

Fold metadata is chronological and versioned under `ncaaf-expanding-folds-v1`: 2014–2018 warmup, expanding 2019–2023 development evaluations, and 2024 validation/model-selection. 2025 does not appear in the development artifacts and remains the locked once-only test; 2026 remains prospective shadow.

## Limits and Phase 5B-3 readiness

The dataset is ready for naive, Elo, and Ridge falsification baselines under the frozen chronological folds. It is not evidence of predictive accuracy or betting edge.

Remaining research limits are deliberate:

- the 2014 boundary lacks pre-2014 program history, so its earliest rows use population-only priors/null quality fields;
- opponent adjustment is a transparent one-pass prior-only residual, not a final learned strength system;
- the exact operational morning convention awaits historical-odds coverage evidence;
- cfbfastR source differences require coverage sensitivity checks, especially in 2021–2022;
- weather, injuries, personnel, recruiting, transfers, returning production, quarterback, and coaching features remain deferred; and
- market-relative/residual claims remain blocked on the separate historical-odds audit.
