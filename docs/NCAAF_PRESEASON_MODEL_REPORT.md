# NCAAF Preseason and Personnel Model Report

Status: **Phase 5B-6 completed offline on 2026-08-30.** This is reconstructed 2014–2024 development evidence. It does not inspect 2025, use sportsbook prices, calculate EV, or change production recommendations.

## Frozen inputs and scope

- Base efficiency dataset: `b2f7444e2a7451d90c9078fb3b694d1586b1d30dd7f9c3a60b869381532b8bfe`
- Base feature set: `0d4d5b3e9996c5682bc6e5366f70c4a82fd80fce8a3ebaa8db7a6ee22bc446ad`
- Corrected combined preseason dataset: `1d6137b1c6100629eaddcbec9e24be7de89acec69ac52ad90186c711ac732a93`
- Preseason registry: `ncaaf-preseason-personnel-v1`
- Preseason feature-set hash: `699a92b434f7421ac9fd61e803bd32b613d3c412bdf19085858b3d3425841a4b`
- Source/feature manifest: `aa4a1d05427e7dac6e8721f818e8384a30f492e586ac0057fe3eab8e3b4c7221`
- Primary model run: `209418790050f5afba640ee04d6f72a571bac3c1c16bfc5f993eabef6006d256`
- Supplemental family/probability run: `a05ffee783bd60cd8e535e6cb079ab6c4a40c9e4a8af51a95ecd67ce82b38db5`

The experiment kept the Phase 5B-3 folds: 2014–2018 first training history, chronological 2019–2023 development evaluations, and 2024 validation. All three horizons were fitted separately. The primary run emitted 53,328 OOF predictions. No provider call occurred during feature building or modeling, and 2025 remained sealed.

## Source and feature coverage

The bounded CFBD audit consumed 68 billable calls and reused immutable Phase 5B-1 caching. It yielded 2,837 normalized program-season rows. Each horizon contains 8,277 eligible games. Team-side preseason availability was 99.65% at 24 hours, 99.94% at 60 minutes, and 99.70% at game-day morning.

Coverage is not strict historical publication fidelity. All products were retrieved in 2026. Returning production, recruiting/talent, roster, and coach facts use the documented reconstructed season-start boundary. Portal coverage is absent in 2014–2020 and begins in 2021; absent coverage is null, not zero. Talent is absent in 2014 and has lower provider coverage in 2017 and 2024. Coordinator features were deferred because no verified structured CFBD history exists.

## Point results

The 24-hour horizon is the primary comparison. MAE values are chronological OOF across 2019–2024.

| Target | Candidate | Overall MAE | Weeks 0–3 | 2024 | Paired MAE vs frozen baseline | Decision |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| Margin | Chronological power baseline | 13.418 | 14.861 | 13.364 | — | Retain benchmark |
| Margin | Preseason-adjusted power | **13.244** | **13.943** | **13.309** | **-0.174**, 95% season-block `[-0.382, 0.005]` | Advance offline |
| Margin | Ridge + all preseason | 13.554 | 13.806 | 13.250 | -0.006, interval crosses zero | Reject as replacement |
| Total | Ridge no-opponent benchmark | 13.202 | 13.126 | 12.964 | — | Retain probability benchmark |
| Total | CatBoost + preseason | 13.122 | 12.920 | 12.878 | **-0.080**, `[-0.143, -0.012]` | Advance as offline point challenger |
| Total | Ridge + all preseason | 13.446 | 13.456 | 13.191 | +0.244, wholly unfavorable | Reject |

The power-prior margin result also passed the frozen point gates at morning and 60 minutes. The 60-minute paired interval was fully favorable; the 24-hour and morning intervals narrowly crossed zero, so the evidence is useful but not conclusive. Preseason CatBoost total advanced at 24 hours and 60 minutes, but not morning under the full frozen gate set.

At 24 hours, preseason-adjusted margin MAE was 13.959 in Weeks 0–1, 13.928 in Weeks 2–3, 12.759 in Weeks 4–6, and 13.142 in Weeks 7+. Its 2020 MAE was 13.547 and 2021–2022 MAE was 13.382. CatBoost total MAE was 13.064, 12.787, 13.302, and 13.138 for the same week buckets; its 2020 and 2021–2022 MAEs were 13.849 and 12.957. No single tagged regime explains the full result.

## Family ablations and advancement

Family-only results mean the frozen efficiency inputs plus only the named preseason family. Leave-one-out results mean all preseason families except the named family.

| Family | Margin family-only MAE | Margin leave-out MAE | Total family-only MAE | Total leave-out MAE | Disposition |
| --- | ---: | ---: | ---: | ---: | --- |
| Recruiting/talent | **13.309** | **13.727** | 13.201 | 13.448 | Advance for offline margin-prior research; reconstructed-vintage caveat remains |
| Returning production | 13.550 | 13.528 | 13.266 | 13.406 | Do not independently advance; retain as exploratory/ablation input |
| QB continuity proxy | 13.554 | 13.554 | 13.217 | 13.451 | Do not independently advance; source does not prove Week 1 starter |
| Coaching continuity | 13.536 | 13.545 | 13.225 | 13.418 | Do not independently advance |
| Roster continuity | 13.578 | 13.556 | 13.224 | 13.420 | Do not independently advance |
| Transfers | 13.766 | **13.350** | 13.332 | **13.306** | Reject from the common 2014–2024 core; evaluate only in a predeclared 2021+ common-coverage experiment |
| Quality flags | 13.553 | 13.548 | 13.221 | 13.445 | Retain for audit/missingness, not as a football-signal claim |

The transfer result is a warning about era coverage, not evidence that transfers are irrelevant. A source family that is structurally absent for seven development seasons cannot be promoted from this common-cohort design.

Fold-local standardized coefficient magnitudes identify contribution, not causality. The strongest recruiting/talent terms were home-away recruiting rank/points and home recruiting points. Other large but less stable terms included returning passing-production fields, prior-leading-QB-return indicators, offensive-line/defensive roster overlap, coach-change flags, and portal-era coverage indicators. The coefficient manifests preserve every fold's imputation, variance mask, scaling, coefficients, and training cutoff.

## Probability and uncertainty effect

The limited probability pass reused only the already-approved distribution families.

For margin at 24 hours, preseason-adjusted power plus empirical-discrete residuals produced NLL `4.10450`, discrete CRPS `9.40192`, 90% coverage `90.54%`, and mean 90% width `54.96`. Versus the frozen power empirical-discrete benchmark, paired differences were `-0.00635` NLL (`[-0.01907, 0.00545]`) and `-0.02137` CRPS (`[-0.12139, 0.07772]`). Both intervals cross zero. Exact push/key-number calibration remained coherent—half-point push is zero—but the probability benchmark is **not displaced**.

For total at 24 hours, preseason CatBoost plus empirical residuals produced NLL `4.21661`, CRPS `9.22831`, 90% coverage `91.69%`, and width `56.66`, versus Ridge empirical NLL `4.22481` and CRPS `9.30423`. Paired candidate-minus-benchmark intervals were `[-0.02408, 0.00305]` for NLL and `[-0.21957, 0.03374]` for CRPS. Both cross zero, so Ridge empirical remains the total probability benchmark.

Incomplete preseason rows were rare but materially harder for the advancing power-prior candidate: 44 OOF rows had MAE `18.492` and residual SD `23.183`, versus 13,288 complete rows with MAE `13.220` and SD `16.583`. Both-prior-leading-passers-returning rows had MAE/SD `13.122/16.338`, versus `13.246/16.668` otherwise. Coach-change games were harder (`13.490/16.876`) than no-change games (`13.031/16.374`). Mean returning PPA at least 0.5 was also associated with modestly lower error/scale. These are descriptive strata, not causal evidence or permission for hand-set sigma adjustments. The low-transfer-churn group contained only 16 rows and is too sparse to interpret.

## Prospective practicality and limitations

- CFBD can reproduce the accepted structured families for a 2026 prospective run within the existing immutable cache/manifest architecture. Fetch once after the products stabilize and preserve each update vintage if monitoring revisions.
- Returning-production and recruiting/talent publication timing must be measured prospectively; v1 has reconstructed, not strict-live, historical availability.
- Portal updates can be refreshed incrementally using transfer dates, but a 2021+ common-coverage experiment must be frozen before reconsidering the family.
- Roster/player-stat matching is adequate for continuity proxies, not declared starter certainty. A future official depth-chart source needs a separate timestamped contract.
- Head-coach continuity is practical; coordinator continuity remains deferred. Injuries, weather, and news were explicitly out of scope.
- The corrected dataset keeps absent portal history null. The earlier temporary artifact that encoded absence as zero was rejected before final reporting and is not the reported input.

## Advancement decision

Advance the bounded preseason-adjusted power model and recruiting/talent family to further **offline** research. Carry preseason CatBoost total only as a point challenger. Do not replace the empirical-discrete margin or Ridge-empirical total probability benchmarks because paired probability intervals include zero. Reject full preseason Ridge total and the common-era transfer feature set; keep returning production, QB, coaching, and roster features as explicit exploratory ablations rather than core promoted families.

No result establishes market edge, profitability, fair-probability superiority, or production readiness. Phase 5B-7 still requires bounded same-horizon historical sportsbook coverage, then market-relative residual and calibration evaluation. Phase 4 market consensus remains the implemented fair probability.

## Operational evidence

- Canonical primary run: 635.6 seconds, peak working set 1,446,846,464 bytes (1.35 GiB), 53,328 prediction rows, and about 1.22 MB of local artifacts.
- Supplemental family/probability run: 284.1 seconds, 62,216 family-only prediction rows, 44,040 probability rows, and about 19.6 MB of local artifacts.
- The current corrected preseason artifact generation contains 30.37 MB; the local immutable namespace is larger because it preserves the rejected pre-correction content-addressed version rather than mutating it.
- Training is deliberately offline. The measured memory profile is not suitable for the Render web instance and no research module or dependency is imported there.
- Two unchanged-code primary runs produced identical run hash `209418790050f5afba640ee04d6f72a571bac3c1c16bfc5f993eabef6006d256`. Supplemental repeat evidence is recorded by its validated identical run hash.
