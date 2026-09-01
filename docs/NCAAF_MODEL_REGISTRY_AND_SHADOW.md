# NCAAF Model Registry and Prospective Shadow Operation

Status: **Phase 5B-10 implemented. Phase 5 is complete.** This is a model-governance and prospective-recording boundary, not authorization for production betting, recommendations, EV qualification, or staking.

Machine registry: [`reports/NCAAF_MODEL_REGISTRY_V1.json`](reports/NCAAF_MODEL_REGISTRY_V1.json), registry hash `42bba06ef7165127615ae3724db4c333655581f41c076b63ab2748b1cbc64418`.

## Retained NCAAF v1 benchmark

The locked 2025 holdout failed the constrained total-blend promotion gates. The registered v1 fair-value source is therefore:

| Target/market | Registered model | Status | Fair-value source |
| --- | --- | --- | --- |
| Margin | `ncaaf-market-consensus-margin-v1@1.0.0` | `retained_benchmark` | market consensus |
| Moneyline | `ncaaf-market-consensus-moneyline-v1@1.0.0` | `retained_benchmark` | market consensus |
| Spread | `ncaaf-market-consensus-spread-v1@1.0.0` | `retained_benchmark` | market consensus |
| Total | `ncaaf-market-consensus-total-v1@1.0.0` | `retained_benchmark` | market consensus |

The consensus and vig versions remain `unweighted-median-v1` and `proportional-v1`. The operational horizon is `morning_first_kickoff_minus_3h`, and at least two complete supported books are required.

The following research records are preserved without promotion:

- `ncaaf-football-power-margin-v1@1.0.0`: `diagnostic`;
- `ncaaf-ridge-total-no-opponent-adjustment-v1@1.0.0`: `diagnostic`;
- `ncaaf-market-ridge-total-blend-v1@1.0.0`: `rejected` after the locked 2025 holdout.

The Phase 5B-8 freeze, Phase 5B-9 holdout, frozen Ridge artifact, and market-aware probability artifact are registered separately as immutable artifact/evidence records. Their original hashes are not rewritten.

## Registry contract

`model_registry_entries` stores one immutable row per `model_id + version`, including league, target/market, status, family, feature/source/run hashes, calibration/consensus/vig versions, holdout outcome, promotion decision, artifact locations, build version, and deterministic entry hash.

`artifact_registry_entries` stores immutable governance, model, probability, and holdout artifacts independently from model lifecycle. A repeated registration with the same identity and hash is idempotent. Reusing an identity/version with different content is a conflict. Updating or deleting a registry row is rejected; a future change creates a new version.

Allowed lifecycle labels are `retained_benchmark`, `shadow_candidate`, `diagnostic`, `rejected`, and `retired`. Phase 5B-10 registers no proprietary shadow candidate because none passed the locked holdout.

## Phase 6 fair-value interface

`FairValueService.quote` accepts an exact registered benchmark and provider-neutral consensus input. It returns:

```text
canonical_event_id
model_id / model_version / model_status
market_type / selection_side
fair_probability
fair_point (spread/total where applicable)
push_probability (spread/total)
source_as_of
source_books / source_book_count
consensus_dispersion
uncertainty_quality
provenance, including registry and pricing-policy versions
interface_version = ncaaf-fair-value-v1
```

The service fails closed unless the registry row is both `retained_benchmark` and `market_consensus`. A diagnostic or rejected football model cannot supply fair value. Integer spread/total lines require an explicit nonzero push model; Phase 5B-10 does not silently treat their push probability as zero.

The interface deliberately contains no sportsbook odds or executable-price field:

```text
retained benchmark -> fair probability / fair line
Phase 4 live pricing -> best executable sportsbook price
Phase 6 -> compare the two, calculate EV, apply risk and approval policy
```

Fair value is not the best offered price. Phase 5B-10 calculates neither edge nor EV.

## Prospective 2026 shadow workflow

The offline/service workflow is:

1. List reliably matched NCAAF events for the UTC slate date.
2. Calculate the frozen cutoff from the first scheduled kickoff minus three hours.
3. Explicitly ingest or load current market data through the existing provider/Phase 3 path.
4. Build `proportional-v1` / `unweighted-median-v1` consensus from data at that cutoff.
5. Ask the retained registry entry for a fair-value quote.
6. Append one immutable `shadow_predictions` row per event/market/side and market state.
7. After completion, append a separate `shadow_prediction_outcomes` row.

The service does not schedule itself and does not call a provider implicitly. A repeated identical prediction is idempotent; later market movement produces a different hash and a new row. Pregame rows cannot be updated or deleted. Every row preserves the registry version and status that produced it, so later registrations do not rewrite history.

`shadow_prediction_outcomes` references the original prediction and stores final score, settlement result, evaluation metadata, source, final timestamp, and deterministic outcome hash. Outcome attachment never modifies the pregame fair-value payload and remains separate from bankroll, bet settlement, and realized P&L.

Diagnostic football models may later emit parallel records only through an explicitly diagnostic path. They cannot enter the retained fair-value service without a new independently validated promotion decision and registry version.

## Commands

Apply migrations before database commands:

```powershell
python -m alembic upgrade head
```

Registry:

```powershell
python -m app.cli.ncaaf_model_registry build
python -m app.cli.ncaaf_model_registry validate
python -m app.cli.ncaaf_model_registry sync
python -m app.cli.ncaaf_model_registry list
python -m app.cli.ncaaf_model_registry inspect ncaaf-market-consensus-total-v1 1.0.0
```

Shadow operation:

```powershell
python -m app.cli.ncaaf_shadow plan-slate --date YYYY-MM-DD
python -m app.cli.ncaaf_shadow generate --input path/to/provider-neutral-consensus.json
python -m app.cli.ncaaf_shadow inspect PREDICTION_ID
python -m app.cli.ncaaf_shadow attach-outcome PREDICTION_ID --home-score 31 --away-score 24 --source official-final --final-at TIMESTAMP
python -m app.cli.ncaaf_shadow summarize
```

`generate` reads an explicit provider-neutral local input. It does not contact The Odds API. Live acquisition remains an explicit separate operation.

## Limitations and Phase 6 readiness

- Market consensus is a retained benchmark, not a proprietary predictive model.
- Phase 5 found no independently validated proprietary edge and the failed 2025 result remains immutable.
- No candidate is authorized to affect production recommendations.
- Phase 6 may consume the fair-value interface and separately obtain an executable offer, but must add its own immutable recommendation, EV, uncertainty, risk, correlation, bankroll, and human-approval boundaries.
- Prospective 2026 evidence is monitoring data. It cannot rewrite the model version or decision-time payload that generated it.
