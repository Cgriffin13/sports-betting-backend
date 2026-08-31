from __future__ import annotations

import hashlib
import json
import math
import time
from collections import defaultdict
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

from app.research.ncaaf.artifacts import ResearchArtifactStore, schema_hash, table_content_hash
from app.research.ncaaf.calibration import build_probability_rows, paired_season_bootstrap
from app.research.ncaaf.challenger_distribution import summarize_challenger_distributions
from app.research.ncaaf.contracts import stable_hash
from app.research.ncaaf.key_numbers import (
    EMPIRICAL_DISCRETE_MARGIN_VERSION,
    build_key_number_rows,
    summarize_key_number_rows,
)
from app.research.ncaaf.modeling import elo_predictions, feature_columns, fit_predict_fold, frozen_folds
from app.research.ncaaf.probability import EMPIRICAL_VERSION, NORMAL_VERSION
from app.research.ncaaf.preseason_modeling import (
    FAMILY_TOKENS,
    POWER_PRIOR_VERSION,
    RIDGE_ALPHA,
    _rows,
    _fit_power_prior,
    load_preseason_tables,
    preseason_feature_columns,
)

SUPPLEMENT_VERSION = "ncaaf-preseason-supplement-v1"


def run_preseason_supplement(
    store: ResearchArtifactStore,
    manifest: Mapping[str, Any],
    *,
    primary_root: Path,
    key_number_root: Path,
    probability_root: Path,
    output_root: Path,
) -> dict[str, Any]:
    started = time.perf_counter()
    table = load_preseason_tables(store, manifest)["24_hours_before_kickoff"]
    family_rows: list[dict[str, Any]] = []
    model_artifacts: list[dict[str, Any]] = []
    family_summary: dict[str, Any] = {}
    elo_all = np.asarray(elo_predictions(table.to_pylist()), dtype=float)
    for fold in frozen_folds():
        _, artifact = _fit_power_prior(table, fold, preseason_feature_columns(table), elo_all)
        model_artifacts.append({**artifact, "experiment": "power_prior_full"})
    for target in ("target_margin", "target_total"):
        family_summary[target] = {}
        for family in FAMILY_TOKENS:
            columns = _family_only_columns(table, target, family)
            rows: list[dict[str, Any]] = []
            for fold in frozen_folds():
                predicted, artifact = fit_predict_fold(
                    table, fold, target, "ridge", {"alpha": RIDGE_ALPHA}, columns
                )
                model_artifacts.append({**artifact, "family": family, "experiment": "family_only"})
                rows.extend(_rows(table, fold, target, predicted, "ridge", f"family_only_{family}", manifest))
            family_rows.extend(rows)
            family_summary[target][family] = _metrics(rows)

    primary_manifest = json.loads((primary_root / "run_manifest.json").read_text(encoding="utf-8"))
    primary = pq.read_table(primary_root / "oof_preseason_predictions.parquet")
    candidate = primary.filter(
        pc.and_(
            pc.equal(primary["target"], "margin"),
            pc.and_(pc.equal(primary["model_family"], "power"), pc.equal(primary["variant"], POWER_PRIOR_VERSION)),
        )
    ).to_pylist()
    tables = load_preseason_tables(store, manifest)
    enriched = _enrich_margin_rows(candidate, tables)
    probability_rows, pools = build_key_number_rows(pa.Table.from_pylist(enriched))
    for row in probability_rows:
        row["point_model_family"] = "power"
        row["point_model_variant"] = POWER_PRIOR_VERSION
    probability_table = pa.Table.from_pylist(probability_rows).sort_by(
        [(name, "ascending") for name in ("horizon", "distribution_family", "kickoff", "provider_game_id")]
    )
    benchmark = pq.read_table(key_number_root / "oof_key_number_probabilities.parquet")
    probability_summary = {"margin": _probability_comparison(probability_rows, benchmark)}
    total_candidate = primary.filter(
        pc.and_(
            pc.equal(primary["target"], "total"),
            pc.and_(pc.equal(primary["model_family"], "catboost"), pc.equal(primary["variant"], "preseason_full")),
        )
    ).to_pylist()
    total_probability_rows, total_fits, total_pools = build_probability_rows(
        _enrich_quality_rows(total_candidate, tables),
        selected_families=(NORMAL_VERSION, EMPIRICAL_VERSION),
    )
    probability_benchmark = pq.read_table(probability_root / "oof_probabilities.parquet")
    probability_summary["total"] = summarize_challenger_distributions(
        total_probability_rows, probability_benchmark
    )
    uncertainty = _uncertainty_segments(candidate, tables)

    output_root.mkdir(parents=True, exist_ok=True)
    family_path = output_root / "oof_family_only_predictions.parquet"
    probability_path = output_root / "oof_preseason_key_number_probabilities.parquet"
    total_probability_path = output_root / "oof_preseason_total_probabilities.parquet"
    artifacts_path = output_root / "family_model_artifacts.json"
    pools_path = output_root / "empirical_discrete_pools.json"
    total_fits_path = output_root / "total_distribution_fits.json"
    total_pools_path = output_root / "total_distribution_pools.json"
    pq.write_table(pa.Table.from_pylist(family_rows), family_path, compression="zstd")
    pq.write_table(probability_table, probability_path, compression="zstd")
    total_probability_table = pa.Table.from_pylist(total_probability_rows)
    pq.write_table(total_probability_table, total_probability_path, compression="zstd")
    artifacts_path.write_text(json.dumps(model_artifacts, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    pools_path.write_text(json.dumps(pools, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    total_fits_path.write_text(json.dumps(total_fits, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    total_pools_path.write_text(json.dumps(total_pools, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    result: dict[str, Any] = {
        "version": SUPPLEMENT_VERSION,
        "primary_run_hash": primary_manifest["run_hash"],
        "input_dataset_hash": manifest["dataset_hash"],
        "preseason_feature_set_hash": manifest["preseason_feature_set_hash"],
        "family_only_summary": family_summary,
        "probability_summary": probability_summary,
        "uncertainty_segments": uncertainty,
        "family_prediction_rows": len(family_rows),
        "probability_rows": probability_table.num_rows,
        "total_probability_rows": total_probability_table.num_rows,
        "family_content_hash": table_content_hash(pa.Table.from_pylist(family_rows)),
        "probability_content_hash": table_content_hash(probability_table),
        "probability_schema_hash": schema_hash(probability_table.schema),
        "model_artifact_hash": stable_hash(model_artifacts),
        "file_hashes": {
            path.name: _sha256(path)
            for path in (
                family_path, probability_path, total_probability_path, artifacts_path,
                pools_path, total_fits_path, total_pools_path,
            )
        },
        "provider_calls": 0,
        "holdout_accessed": False,
    }
    result["run_hash"] = stable_hash(result)
    result["elapsed_seconds"] = time.perf_counter() - started
    (output_root / "run_manifest.json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return result


def validate_preseason_supplement(output_root: Path) -> list[str]:
    manifest = json.loads((output_root / "run_manifest.json").read_text(encoding="utf-8"))
    family = pq.read_table(output_root / "oof_family_only_predictions.parquet")
    probability = pq.read_table(output_root / "oof_preseason_key_number_probabilities.parquet")
    total_probability = pq.read_table(output_root / "oof_preseason_total_probabilities.parquet")
    errors: list[str] = []
    if max(family["season"].to_pylist()) >= 2025 or manifest["holdout_accessed"]:
        errors.append("locked 2025 holdout accessed")
    if family.num_rows != manifest["family_prediction_rows"]:
        errors.append("family prediction row mismatch")
    if probability.num_rows != manifest["probability_rows"]:
        errors.append("probability row mismatch")
    if total_probability.num_rows != manifest["total_probability_rows"]:
        errors.append("total probability row mismatch")
    if table_content_hash(probability) != manifest["probability_content_hash"]:
        errors.append("probability content mismatch")
    return errors


def _family_only_columns(table: pa.Table, target: str, family: str) -> tuple[str, ...]:
    variant = "full_v1" if target == "target_margin" else "full_without_opponent_adjustment"
    base = tuple(name for name in feature_columns(table, variant) if "preseason_" not in name)
    preseason = preseason_feature_columns(table)
    selected = tuple(name for name in preseason if any(token in name for token in FAMILY_TOKENS[family]))
    return tuple(sorted({*base, *selected}))


def _enrich_margin_rows(
    rows: Sequence[Mapping[str, Any]], tables: Mapping[str, pa.Table]
) -> list[dict[str, Any]]:
    lookup: dict[tuple[str, int], Mapping[str, Any]] = {}
    for horizon, table in tables.items():
        for row in table.select(
            ["provider_game_id", "home_pbp_coverage_ratio", "away_pbp_coverage_ratio", "covid_2020_regime"]
        ).to_pylist():
            lookup[(horizon, int(row["provider_game_id"]))] = row
    output: list[dict[str, Any]] = []
    for row in rows:
        quality = lookup[(str(row["horizon"]), int(row["provider_game_id"]))]
        output.append(
            {
                **row,
                "model_family": "elo",
                "variant": "ncaaf-margin-power-v1",
                "home_pbp_coverage_ratio": quality["home_pbp_coverage_ratio"],
                "away_pbp_coverage_ratio": quality["away_pbp_coverage_ratio"],
                "covid_2020_regime": quality["covid_2020_regime"],
            }
        )
    return output


def _enrich_quality_rows(
    rows: Sequence[Mapping[str, Any]], tables: Mapping[str, pa.Table]
) -> list[dict[str, Any]]:
    lookup: dict[tuple[str, int], Mapping[str, Any]] = {}
    for horizon, table in tables.items():
        for row in table.select(
            [
                "provider_game_id", "home_pbp_coverage_ratio", "away_pbp_coverage_ratio",
                "home_current_season_games", "away_current_season_games", "covid_2020_regime",
            ]
        ).to_pylist():
            lookup[(horizon, int(row["provider_game_id"]))] = row
    return [
        {**row, **lookup[(str(row["horizon"]), int(row["provider_game_id"]))]}
        for row in rows
    ]


def _probability_comparison(rows: Sequence[Mapping[str, Any]], benchmark: pa.Table) -> dict[str, Any]:
    summary = summarize_key_number_rows(rows)
    comparisons: dict[str, Any] = {}
    for horizon in sorted(summary):
        candidate = [
            row for row in rows
            if row["horizon"] == horizon and row["distribution_family"] == EMPIRICAL_DISCRETE_MARGIN_VERSION
        ]
        baseline = benchmark.filter(
            pc.and_(
                pc.equal(benchmark["horizon"], horizon),
                pc.equal(benchmark["distribution_family"], EMPIRICAL_DISCRETE_MARGIN_VERSION),
            )
        ).to_pylist()
        comparisons[horizon] = {
            "candidate": summary[horizon][EMPIRICAL_DISCRETE_MARGIN_VERSION],
            "paired_candidate_minus_baseline": {
                "nll": paired_season_bootstrap(candidate, baseline, score="nll"),
                "discrete_crps": paired_season_bootstrap(candidate, baseline, score="discrete_crps"),
            },
        }
    return comparisons


def _uncertainty_segments(
    rows: Sequence[Mapping[str, Any]], tables: Mapping[str, pa.Table]
) -> dict[str, Any]:
    fields = (
        "provider_game_id", "home_preseason_prior_leading_qb_returns",
        "away_preseason_prior_leading_qb_returns", "home_preseason_head_coach_change",
        "away_preseason_head_coach_change", "home_preseason_transfer_in_count",
        "home_preseason_transfer_out_count", "away_preseason_transfer_in_count",
        "away_preseason_transfer_out_count", "home_preseason_returning_percent_ppa",
        "away_preseason_returning_percent_ppa",
    )
    context: dict[tuple[str, int], Mapping[str, Any]] = {}
    for horizon, table in tables.items():
        for row in table.select(fields).to_pylist():
            context[(horizon, int(row["provider_game_id"]))] = row
    groups: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in rows:
        complete = bool(row["home_preseason_available"] and row["away_preseason_available"])
        groups["complete" if complete else "incomplete"].append(row)
        detail = context[(str(row["horizon"]), int(row["provider_game_id"]))]
        qb = (detail["home_preseason_prior_leading_qb_returns"], detail["away_preseason_prior_leading_qb_returns"])
        if all(value is not None for value in qb):
            groups["qb_both_returning" if all(qb) else "qb_not_both_returning"].append(row)
        coach = (detail["home_preseason_head_coach_change"], detail["away_preseason_head_coach_change"])
        if all(value is not None for value in coach):
            groups["coach_change_any" if any(coach) else "coach_no_change"].append(row)
        transfer_values = [detail[name] for name in fields if "transfer_" in name]
        if all(value is not None for value in transfer_values):
            churn = sum(float(value) for value in transfer_values)
            groups["transfer_churn_10_plus" if churn >= 10 else "transfer_churn_below_10"].append(row)
        returning = (detail["home_preseason_returning_percent_ppa"], detail["away_preseason_returning_percent_ppa"])
        if all(value is not None for value in returning):
            mean_returning = sum(float(value) for value in returning) / 2
            groups["returning_ppa_half_plus" if mean_returning >= 0.5 else "returning_ppa_below_half"].append(row)
    return {name: {**_metrics(group), "residual_sd": float(np.std([float(row["residual"]) for row in group], ddof=1))} for name, group in groups.items() if len(group) > 1}


def _metrics(rows: Sequence[Mapping[str, Any]]) -> dict[str, float]:
    residuals = np.asarray([float(row["residual"]) for row in rows], dtype=float)
    return {
        "n": float(len(rows)), "mae": float(np.mean(np.abs(residuals))),
        "rmse": float(math.sqrt(np.mean(np.square(residuals)))), "bias": float(np.mean(residuals)),
        "median_absolute_error": float(np.median(np.abs(residuals))),
    }


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()
