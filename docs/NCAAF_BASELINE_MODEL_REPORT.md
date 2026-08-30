# NCAAF Baseline Model Report

Status: Phase 5B-3 completed offline on 2026-08-29. No provider calls, 2025 access, production inference, probability calibration, recommendation integration, or betting claim occurred.

## Frozen input and protocol

- Dataset hash: `b2f7444e2a7451d90c9078fb3b694d1586b1d30dd7f9c3a60b869381532b8bfe`
- Feature-set hash: `0d4d5b3e9996c5682bc6e5366f70c4a82fd80fce8a3ebaa8db7a6ee22bc446ad`
- Feature set: `ncaaf-efficiency-point-in-time-v1`
- Availability: `cfbd-reconstructed-kickoff-plus-24h-v1`
- Tournament: `ncaaf-baseline-tournament-v1`
- Folds: train 2014 through year N-1 and evaluate N for 2019–2024. Seasons 2019–2023 select Ridge alpha; 2024 is validation. The command rejects 2025.
- Rows: 8,277 per horizon before folds; 4,444 OOF games per target/horizon across 2019–2024.

The input audit found no duplicate game/horizon rows, missing targets, or non-finite admitted features. Identifiers, targets, model features, quality fields, and excluded provenance metadata are frozen separately in the local run manifest. All preprocessing is trained inside each fold.

## Candidates and configuration

Naive floors are the training-set mean, a transparent home/neutral group mean, and a prior-team-average. `ncaaf-margin-power-v1` is sequential, predicts before update, regresses ratings 35% toward zero between seasons, applies 2.5 home points unless neutral, caps update error at 35, and uses a 0.15 update rate. Ridge evaluates alpha `{0.1, 1, 10, 100}`; every horizon/target selected `100` using development OOF only.

Elastic Net was attempted with alpha `{0.001, 0.01, 0.1}` and l1 ratio `{0.1, 0.5}`. Several configurations failed to converge reliably on the wide v1 matrix, so it is explicitly deferred. The search was not expanded after seeing results.

## Chronological OOF results

The table shows the 24-hour horizon; morning and 60-minute results differ by less than 0.004 MAE for the shown Ridge configurations. They were nevertheless fitted separately because exact feature-vector comparison found legitimate point-in-time differences.

| Target | Candidate | OOF rows | MAE | RMSE | Bias | 2024 MAE | Weeks 0–3 MAE |
|---|---|---:|---:|---:|---:|---:|---:|
| Margin | Power rating | 4,444 | 13.418 | 16.941 | -0.756 | 13.364 | 14.861 |
| Margin | Ridge full v1 | 4,444 | 13.560 | 17.072 | 0.634 | 13.559 | 14.763 |
| Margin | Ridge raw efficiency | 4,444 | 13.620 | 17.164 | — | — | — |
| Margin | Ridge context/prior | 4,444 | 14.831 | 18.645 | — | — | — |
| Margin | Prior-team naive | 4,444 | 15.356 | 19.278 | -3.085 | 15.762 | 15.904 |
| Total | Ridge without opponent adjustment | 4,444 | 13.202 | 16.618 | -0.537 | 12.964 | 13.126 |
| Total | Ridge full v1 | 4,444 | 13.203 | 16.624 | -0.541 | 12.992 | 13.128 |
| Total | Ridge raw efficiency | 4,444 | 13.263 | 16.624 | — | — | — |
| Total | Prior-team naive | 4,444 | 13.496 | 17.012 | 0.699 | 13.216 | 13.166 |
| Total | Training-mean naive | 4,444 | 13.941 | 17.465 | — | — | — |

The margin power rating is the strongest simple point baseline on aggregate and 2024 MAE. Ridge full v1 is stronger in Weeks 0–3 RMSE/MAE than power but does not beat it overall. For total, removing opponent adjustment is numerically best, but the 0.001 OOF-MAE difference from full v1 is operationally indistinguishable; the simpler interpretation is that opponent-adjusted features have not earned a place in the total baseline.

Deterministic season-block bootstrap comparisons reinforce that caution. Power minus full-Ridge margin MAE is `-0.143` with a 95% interval of `[-0.376, 0.091]`; reduced-feature Ridge minus prior-team total MAE is `-0.294` with `[-0.601, 0.023]`; reduced-feature minus full-Ridge total MAE is `-0.001` with `[-0.013, 0.010]`. Every interval crosses zero, so tiny aggregate differences do not justify a strong superiority claim.

## Ablations and sensitivity

- Raw-efficiency Ridge improves materially over context/prior-only Ridge for both targets.
- Opponent-adjusted-only features are weaker than full/raw variants. Removing opponent adjustment improves total by only 0.001 MAE and margin by 0.111 MAE relative to full v1.
- Excluding 2014 training changes 2024 margin MAE from 13.559 to 13.527 and total from 12.992 to 13.006. This is small and mixed; retain 2014 as training history while continuing to tag sparse early priors.
- Excluding 2021–2022 training changes 2024 margin MAE to 13.535 and total MAE to 13.087. It does not improve both targets and is not blocking. The underlying source concern remains a modest, feature-specific sensitivity rather than a reason to delete seasons.
- In the tagged 2021–2022 segment, full Ridge MAE is 13.465 margin and 12.984 total. The 2020 full-Ridge MAE is 13.932 margin and 13.968 total. Neither segment is silently excluded.
- Low-PBP-quality rows are sparse (224 versus 4,220 high-quality OOF rows) and worse for Ridge: 14.471 vs 13.512 margin MAE and 13.826 vs 13.170 total MAE. Coverage remains an uncertainty signal, not a zero-filled feature.

## Residual diagnostics

Power-rating margin residuals have mean `0.756`, standard deviation `16.924`, 5th/95th percentiles `-27.290 / 28.731`, skew `-0.035`, and excess kurtosis `0.087`. Full-Ridge margin residuals have mean `-0.634`, standard deviation `17.061`, 5th/95th percentiles `-29.186 / 27.208`, skew `-0.049`, and excess kurtosis `0.082`.

The leading total Ridge residuals have mean `0.537`, standard deviation `16.609`, 5th/95th percentiles `-25.469 / 29.106`, skew `0.300`, and excess kurtosis `0.230`. Total errors are more asymmetric than margin errors. These diagnostics make Normal a useful falsification distribution, while empirical OOF and Student-t/skew-aware alternatives remain Phase 5B-4 challengers. No probability has been emitted yet.

## Advancement decision

Advance the margin power rating and the Ridge full-v1 margin model as separate Phase 5B-4 distribution candidates: power is the primary simple benchmark; Ridge remains useful for early-season/quality diagnostics. Advance Ridge without opponent adjustment for total, with full-v1 Ridge retained as the indistinguishable comparison. This is advancement to offline residual/distribution research only—not model promotion, production use, or a claim of market edge.

Phase 5B-4 must freeze distribution and calibration experiments, add paired/block uncertainty around differences, and continue to keep 2025 sealed. Historical odds acquisition remains required before any market-relative or economic claim.

## Reproducibility and resources

The completed run produced 267,504 provenance-rich prediction rows (including explicitly tagged sensitivity variants), a 3.70 MB compressed OOF Parquet file, and 7.59 MB of transparent JSON fold parameters. Deterministic run hash: `036989b3c5b65226f93f72164e73ec4070b14ca7105d9b55c9e86af9c9778cfb`. Runtime was 571.642 seconds; measured Windows peak working set was about 1.47 GB. This is an offline research workload and does not affect Render memory or dependencies.

Machine-readable aggregate evidence is in [`reports/NCAAF_BASELINE_MODEL_2014_2024.json`](reports/NCAAF_BASELINE_MODEL_2014_2024.json). Binary/local artifacts remain ignored.
