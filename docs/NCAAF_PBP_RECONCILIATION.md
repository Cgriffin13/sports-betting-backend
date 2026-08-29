# NCAAF PBP Reconciliation

Status: **Phase 5B-2 complete for the 2014–2024 feature-input decision.** This is source QA, not a model-performance report. The machine-readable companion is `reports/NCAAF_PBP_RECONCILIATION_2014_2024.json`.

## Decision

The discrepancy is a **feature-specific and season-specific concern, but it does not block the CFBD baseline dataset**. CFBD remains the authoritative facts input. cfbfastR/SportsDataverse remains QA only. Every downstream row retains PBP coverage and missingness, and 2021–2022 must remain a predefined coverage segment.

The previously reported “CFBD has 123,444 fewer plays” was not a like-for-like comparison. It compared the 2014–2024 CFBD corpus (1,695,709 plays) with the 2014–2025 public QA corpus (1,819,153 plays). The public 2025 file alone contains 165,850 rows. Across the common 2014–2024 range:

- CFBD: **1,695,709** plays;
- cfbfastR: **1,653,303** plays; and
- CFBD minus cfbfastR: **+42,406** plays.

This correction does not imply that CFBD is uniformly more complete. The sources use different play taxonomies, processing, and universes, and game-level differences exist in both directions.

## Season reconciliation

| Season | CFBD rows | cfbfastR rows | Difference | Matched games | CFBD-only | cfbfastR-only |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 2014 | 158,170 | 155,521 | +2,649 | 848 | 2 | 6 |
| 2015 | 160,180 | 158,501 | +1,679 | 863 | 0 | 3 |
| 2016 | 158,518 | 155,622 | +2,896 | 856 | 1 | 2 |
| 2017 | 158,574 | 155,505 | +3,069 | 869 | 0 | 3 |
| 2018 | 160,512 | 158,249 | +2,263 | 881 | 0 | 3 |
| 2019 | 159,915 | 156,888 | +3,027 | 887 | 0 | 3 |
| 2020 | 99,460 | 100,420 | -960 | 544 | 5 | 21 |
| 2021 | 158,498 | 146,367 | +12,131 | 839 | 48 | 3 |
| 2022 | 160,282 | 149,654 | +10,628 | 857 | 39 | 4 |
| 2023 | 158,995 | 153,626 | +5,369 | 902 | 8 | 1 |
| 2024 | 162,605 | 162,950 | -345 | 900 | 18 | 46 |

The known public 2021–2022 game-coverage gaps explain a material share of the positive CFBD difference: those seasons contribute +22,759 rows and 87 CFBD-only games. The issue is concentrated in regular-season data. Postseason differences are comparatively small.

## Game-level findings

Exact ESPN/CFBD game IDs matched across the sources. Of those matches, 9,203 have differing play counts, confirming that row taxonomy/processing—not only missing games—drives the discrepancy. Most differences are modest, but a few require quarantine-style QA:

- Game `400756912` has 199 CFBD rows versus 1,493 public rows, a likely public duplication/processing anomaly.
- Games `400869339`, `401249031`, and `401282717` differ by more than 100 plays.
- Differences occur in both FBS-vs-FBS and FBS-vs-FCS/other games; the latter are more sensitive to the sources' FBS filters.

No exact play-level equality is expected or required. Feature calculations use CFBD fields and definitions only, while the machine report preserves the largest game-level deltas for targeted review.

## Bias assessment and controls

The baseline can proceed because the primary CFBD FBS-participant game coverage remains high, identities are exact, and feature rows expose coverage. Controls are:

1. retain play/drive/stat coverage per team and target row;
2. do not treat missing PBP as zero performance;
3. report 2021, 2022, 2020, and lower-division-context segments separately;
4. retain source manifest/content hashes for every normalized partition;
5. quarantine material single-game count anomalies during sensitivity analyses rather than rewriting source facts; and
6. run a later ablation excluding low-coverage games/seasons before any model promotion.

The reconciliation made **zero CFBD calls**. It used one explicit bounded download of the public 2014–2024 QA Parquet assets, retained only ignored per-game counts locally, and committed only aggregate non-secret results.
