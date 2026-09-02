# POLARIS live pricing methodology audit

Status: completed offline on 2026-09-02 from the bounded live-verification summaries captured by the preceding freshness hotfix. No additional Odds API request was made.

## Preserved live evidence

The verified live run reached a healthy pricing funnel:

| Stage | Count |
| --- | ---: |
| Events received | 146 |
| Eligible observations | 3,088 |
| Exact paired book markets | 1,544 |
| Comparable exact-line groups | 637 |
| Calculable candidate sides | 572 |
| Positive-edge and positive-EV candidates | 47 |
| Watchlist candidates | 15 |
| Phase 4 pricing-qualified candidates | 20 |
| Final actionable recommendations under the prior policy | 0 |

The one-shot verifier intentionally used temporary storage and deleted the raw provider payload. This repository has no production PostgreSQL credential, so the complete 20-candidate book-level state cannot be reconstructed without either a new provider request or a read-only production export. Both were outside this correction. The table below therefore audits the ten candidate summaries preserved in the verification output and does not claim to be a complete rerun.

## Corrected diagnosis

The claim that every known candidate was rejected by `material_book_outlier` is not consistent with the recorded numbers. The diagnostic threshold is an absolute 3-percentage-point deviation from the median. If the full probability range is below 3 points, no contributor can exceed that deviation. Eight of the ten preserved candidates had total dispersion below 3 points and therefore could not have received that warning. Clemson–LSU (3.178 points) and Arkansas–Utah (4.226 points) could have contained an outlier, but the deleted per-book rows are required to confirm which book.

All ten known candidates independently sized below the unchanged `$1.00` minimum at the `$200` test bankroll. Their prior zero-actionable result therefore has a valid risk-control explanation even after the blanket outlier rejection is removed. Under the subsequently approved `ncaaf-qualification-v3` main-board policy, the six offers above `+500` also receive `outside_main_board_odds_profile`; their calculations remain available for research, but they cannot become ordinary straights or parlay legs. The `+300`, `+340`, `+350`, and `+450` rows remain mathematically eligible and still PASS solely because the calculated stakes are below the operational minimum.

The following uses the stored fair probability, executable odds, dispersion-based uncertainty band, quarter Kelly, and the existing `0.60` OPPORTUNISTIC multiplier. `Growth` is consensus expected log growth at the projected adjusted fraction, not the new robust minimum-book score; the latter requires the unavailable per-book no-vig probabilities.

| Matchup / side | Odds | Fair p | Edge | Raw EV | Books | Dispersion | Full Kelly | Quarter Kelly | Adjusted fraction | `$200` stake | Growth |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Duquesne @ Air Force — away ML | +4000 | 3.626% | 1.187% | 48.671% | 4 | 2.662% | 1.217% | 0.304% | 0.137% | $0.27 | 0.0613% |
| Mercyhurst @ New Mexico State — away ML | +3500 | 4.058% | 1.280% | 46.093% | 4 | 2.597% | 1.317% | 0.329% | 0.148% | $0.30 | 0.0629% |
| Austin Peay @ Vanderbilt — away ML | +2400 | 5.119% | 1.119% | 27.965% | 3 | 1.491% | 1.165% | 0.291% | 0.175% | $0.35 | 0.0444% |
| Western Michigan @ Michigan — away ML | +2500 | 4.632% | 0.786% | 20.436% | 5 | 1.933% | 0.817% | 0.204% | 0.092% | $0.18 | 0.0175% |
| Houston Baptist @ Rice — away ML | +1400 | 7.443% | 0.777% | 11.650% | 5 | 2.242% | 0.832% | 0.208% | 0.094% | $0.19 | 0.0102% |
| Arkansas @ Utah — away ML | +300 | 26.992% | 1.992% | 7.969% | 3 | 4.226% | 2.656% | 0.664% | 0.159% | $0.32 | 0.0123% |
| Miami (OH) @ Pittsburgh — away ML | +650 | 14.206% | 0.872% | 6.542% | 6 | 2.264% | 1.006% | 0.252% | 0.113% | $0.23 | 0.0070% |
| Clemson @ LSU — away ML | +350 | 23.483% | 1.261% | 5.676% | 6 | 3.178% | 1.622% | 0.405% | 0.097% | $0.19 | 0.0054% |
| Oklahoma State @ Tulsa — home ML | +450 | 19.096% | 0.915% | 5.030% | 6 | 2.313% | 1.118% | 0.279% | 0.126% | $0.25 | 0.0060% |
| Toledo @ Michigan State — away ML | +340 | 23.633% | 0.906% | 3.987% | 6 | 2.542% | 1.173% | 0.293% | 0.132% | $0.26 | 0.0050% |

These rows are pricing-qualified but not necessarily portfolio-actionable. None may be rounded up to create activity. At a larger future equity, the same versioned Kelly calculation would scale automatically; the fixed `$1` operational floor is the reason these ten do not become paper positions at `$200`.

## Ranking correction

The prior Phase 6 order was:

```text
CORE before OPPORTUNISTIC
then EV * uncertainty_multiplier / (1 + 10 * dispersion)
then raw EV, kickoff, candidate ID
```

That interpretable-but-heuristic score was still dominated by raw EV and did not account for the prudent amount of capital the opportunity could support. Persisted reads could then lose even that order by sorting generated recommendation hashes.

The replacement is:

```text
full push-aware Kelly
-> existing quarter-Kelly / quality / class / state multipliers
-> projected standalone risk caps
-> consensus expected log growth
-> minimum expected log growth across contributing no-vig book probabilities
-> deterministic quality/tie-break order
-> sequential stake and exposure controls
-> Top N successful positions
```

For fraction `f`, decimal net profit `b`, and probabilities `p_win`, `p_push`, `p_loss`:

```text
g = p_win * ln(1 + f*b) + p_loss * ln(1 - f) + p_push * ln(1)
```

The robust ranking score is the minimum `g` across contributing books. The score never changes EV qualification or stake math.

### Synthetic proof: standard juice can outrank a larger-raw-EV longshot

Case A is a `+2000` moneyline with fair probability `6%`:

```text
implied p = 1 / 21 = 4.7619%
edge = 6.0000% - 4.7619% = 1.2381%
EV = 0.06 * 21 - 1 = 26.0000%
full Kelly = 1.3000%
adjusted fraction = 1.3000% * 0.25 * 0.60 = 0.1950%
stake at $200 = $0.39
expected log growth = 0.0461%
```

Case B is a `-110` half-point spread with fair cover probability `55%`:

```text
decimal odds = 1 + 100/110 = 1.9090909
implied p = 52.3810%
edge = 2.6190%
EV = 0.55 * 1.9090909 - 1 = 5.0000%
full Kelly = 5.5000%
adjusted fraction = 5.5000% * 0.25 = 1.3750%
stake at $200 = $2.75
expected log growth = 0.0602%
```

Case B has much lower raw EV but higher prudent expected bankroll growth, so it ranks first and is actionable. A `+1000` candidate at fair probability `10%` likewise has higher raw EV (`10%`) but only `0.0138%` projected growth and a `$0.30` stake, so the same `-110` spread ranks first on mathematics alone. These two examples prove the correction does not need a hard odds band to obtain practical ordering.

A genuinely stronger `+1000` candidate at fair probability `13%` would support a `$2.15` capped-fraction stake and approximately `0.3871%` expected log growth. That is the important tail-risk diagnosis: sufficiently large estimated probability separation can still dominate Kelly/log growth, but its result is unusually sensitive to small probability-estimation error. POLARIS currently has no separately validated longshot probability policy or exposure sleeve. The `>+500` main-board safety guardrail therefore keeps that row calculable but non-actionable. No additional `+300` evidence heuristic, negative-odds boundary, fair-value adjustment, or market quota was added.

## Executable outlier correction

`unweighted-median-v1` remains frozen:

1. validate a current, active, supported book and complete exact opposing pair;
2. remove vig within each book;
3. take the unweighted median across books;
4. label contributors more than 3 points from that median;
5. reject a market above the Phase 4 8-point dispersion ceiling;
6. Phase 6 applies its stricter 6-point ceiling.

Outlier contributors remain in the recorded input set, but one extreme contributor cannot define the median. There is not enough validated evidence to invent sharp-book weights or delete a book solely because it differs.

Before this correction, any `material_book_outlier` warning caused a hard Phase 6 rejection—even when the flagged book was not the best offer. Afterward, `material_book_outlier` and `best_executable_book_outlier` are explicit informational integrity states. The best quote remains separately executable if all independent checks pass. Unknown/malformed integrity warnings, stale/inactive/unsupported books, invalid pairs, and excess dispersion still fail closed. The ranking score uses the least favorable contributing probability, so weak corroboration reduces portfolio priority without conflating a desirable price difference with corrupt data.

## Conclusion

The funnel is healthy, but an exact 20-row post-change replay is unavailable from retained local artifacts. The known ten are all honest portfolio PASS outcomes at `$200`: every calculated stake is below `$1`, and six are additionally outside the ordinary `>+500` main-board profile. Eight are definitively not material probability outliers. The correction is ready for another operator-triggered paper refresh after deployment: it preserves fair value, EV, Kelly, staking, and exposure math; changes qualified ordering and outlier-warning semantics; applies only the explicit no-longshot-sleeve guardrail; and exposes enough provenance to distinguish fair value, executable price, Kelly, ranking, eligibility, and integrity.

This is still paper trading. It is not evidence of proprietary edge, profitability, or real-money readiness.
