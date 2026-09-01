# NCAAF 2025 Locked Holdout Report

Status: **FAIL — fallback to market consensus**

This is the first and only evaluation of the frozen Phase 5B-8 finalists on 2025. It is an offline model-governance result, not evidence of betting profitability or production readiness. No candidate, feature, calibration method, blend weight, or gate was changed after the holdout opened.

## Integrity and first access

- Phase 5B-8 freeze hash: `5aff62fe0faf9a246c49f2e1ad732b4b6bbb412aa084f9ccd1f635aacb498420` — verified before access.
- One-time unlock: `a02f96a85f54e90ca5917a705ddc87410d17aa0bbab3528988a93b907bdb7c28`.
- Unlock timestamp: `2026-08-31T23:56:44.749145+00:00`.
- Unlock code commit: `559e66bbd854e0a03a6cce28410056742d318151`.
- Evaluation code commit: `dc8b47752dd7a151c0dac9b172a6210877b1d982`.
- Frozen Ridge replay: exact reproduction of the 2024 saved predictions; maximum absolute difference `0.0`.
- Candidate allowlist and fixed football weight `0.17854145992095644` matched the freeze.
- Holdout run hash: `e32e8102de3ac51d1a5690fd6cd3e680fa36d9424060784be645c80d8e526256`.

Ordinary development commands remain sealed. The explicit unlock is stored outside Git beneath `.ncaaf-data/holdout-2025/` and a second unlock is rejected.

## Acquisition and point-in-time inputs

The 2025 CFBD plan made 37 calls and cached 194,172 source rows. A retry exposed and fixed an immutable-cache recovery defect: identical provider content with a missing local artifact now restores the content-addressed artifact instead of attempting a duplicate manifest insert.

Before any billable historical-odds request, the frozen morning plan reported:

| Item | Value |
| --- | ---: |
| Logical requests | 79 |
| Unique new requests | 79 |
| Cache hits | 0 |
| Expected credits | 2,370 |
| Available credits | 20,000 |
| Projected remaining | 17,630 |
| Plan hash | `6e5dfe394c2da1e1b11deacbaa850336d54ee1f1c552c04aa329bf740ff07c6a` |

Execution matched the plan exactly: 79 calls consumed 2,370 credits and left 17,630. The market layer retained only closest-prior snapshots at or before the first-scheduled-kickoff-minus-three-hours cutoff. No 60-minute or near-close observation entered the holdout.

## Coverage

| Cohort | Games |
| --- | ---: |
| Eligible 2025 FBS-vs-FBS football rows | 808 |
| Football feature rows available | 808 |
| Moneyline consensus | 724 |
| Spread consensus | 719 |
| Total consensus / identical blend comparison cohort | 758 |

The total decision therefore exceeded the frozen 500-game minimum. Fifty eligible games lacked a qualified total consensus under the unchanged exact-line, minimum-two-book, event-reconciliation, and timestamp rules. Market normalization produced 46,268 individual observations across 808 events and 2,424 event-market groups.

## Frozen benchmark context

Market consensus remained the frozen margin, spread, and moneyline estimator. On the available 2025 cohorts:

- Moneyline: 724 games, Brier `0.1790510607`, log loss `0.5320297880`.
- Consensus spread expectation: 719 games, MAE `11.7913769124`, RMSE `14.9350704127`, bias `0.6397774687`.
- Football power diagnostic: the same 719 games, MAE `13.0354735107`, RMSE `16.6073334661`, bias `1.9664130886`.

The power result is diagnostic only and does not reopen the frozen market-first decision.

## Total finalist results

The frozen challenger was applied exactly:

```text
blend = market_total
      + 0.17854145992095644 * (frozen_ridge_total - market_total)
```

| Metric | Market | Frozen blend | Frozen comparison |
| --- | ---: | ---: | ---: |
| MAE | 12.5250659631 | 12.5306280735 | improvement `-0.0055621104` |
| RMSE | 15.5789545817 | 15.6113313576 | degradation `+0.0323767759` |
| Multiclass Brier | 0.5003294653 | 0.5003266030 | improvement `+0.0000028623` |
| Multiclass log loss | 0.6934766518 | 0.6934782005 | improvement `-0.0000015487` |
| Weighted calibration error | — | 0.0124432711 | limit `0.05` |

The paired week-block 90% interval for blend-minus-market MAE was `[-0.0380195406, +0.0481338093]` using 16 week blocks, 10,000 deterministic resamples, and seed `53107`.

All 2025 consensus totals were half-point lines, so observed line push mass was correctly zero. Both candidates nevertheless emitted an explicit push-probability field, all win/push/loss triples normalized to one, and the frozen integer-lattice implementation remains covered by integer-line tests. Zero push mass was not treated as missing push semantics.

## Frozen promotion gates

| Gate | Result | Observed | Required |
| --- | --- | ---: | ---: |
| Identical cohort size | PASS | 758 | >= 500 |
| MAE improvement | **FAIL** | -0.005562 | >= 0.10 |
| RMSE degradation | PASS | +0.032377 | <= 0.10 |
| Multiclass Brier improvement | **FAIL** | +0.0000029 | >= 0.001 |
| Multiclass log-loss improvement | **FAIL** | -0.0000015 | >= 0.001 |
| Week-block 90% MAE upper bound | PASS | +0.048134 | <= +0.05 |
| Weighted calibration error | PASS | 0.012443 | <= 0.05 |
| Explicit push probabilities | PASS | preserved/normalized | required |
| Any broad segment MAE/Brier degradation | PASS | +0.087737 / +0.004829 | <= +0.50 / +0.01 |
| Segments with MAE degradation > 0.25 | PASS | 0 | <= 1 |

Because the frozen rule is all-or-fallback, the three failed practical/proper-score gates require:

```text
total blend does not promote
fallback = market consensus
```

## Segment checks

All predeclared segments with at least 75 games stayed within the degradation caps. High market dispersion (18 games) and disagreement of at least seven points (65 games) were marked unevaluable rather than interpreted. The largest evaluated MAE degradation was `0.087737` in the 82 low-quality rows; the largest evaluated Brier degradation was `0.004829` in the same segment.

No post-hoc segment was added after results were visible.

## Immutable outputs and Phase 5B-10 handoff

- Holdout football feature dataset: `ce04f50bea76923ece336e18d384e5f0a8a607bc91c827ebc8501a5956bde4bb`.
- Holdout historical market dataset: `2aabb8f871906dbb4ea6608967a18c4fac3d4845bde7b7ca1d876fbc47724c48`.
- Total prediction content hash: `11166d8ed4ac3066ce1a6a6393f476dac440f42bdb0c4f0f5417327f840a8633`.
- Total probability content hash: `91fb8b2797a315fd0b4ed62fbbe6f276f79fa19d529063c9852b567ff8d7dfd0`.

Phase 5B-10 may register market consensus as the retained NCAAF margin, moneyline, spread, and total benchmark for prospective shadow operations. The fixed total blend is rejected for promotion under the predeclared holdout gates. Phase 5B-10 must not tune the rejected blend on 2025 or reinterpret these results as profitability, edge, or production-betting approval.
