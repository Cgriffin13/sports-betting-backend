from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

from app.research.ncaaf.artifacts import schema_hash, table_content_hash
from app.research.ncaaf.calibration import build_probability_rows, paired_season_bootstrap
from app.research.ncaaf.contracts import stable_hash
from app.research.ncaaf.probability import EMPIRICAL_VERSION, NORMAL_VERSION

CHALLENGER_DISTRIBUTION_VERSION = "ncaaf-strong-challenger-distribution-v1"


def _strong_total_rows(table: pa.Table, *, end_season: int = 2024) -> list[dict[str, Any]]:
    if end_season >= 2025:
        raise ValueError("locked 2025 holdout cannot enter challenger distributions")
    mask = pc.and_(
        pc.and_(pc.equal(table["target"], "total"), pc.equal(table["model_family"], "catboost")),
        pc.and_(pc.equal(table["variant"], "full_v1"), pc.less_equal(table["season"], end_season)),
    )
    rows = table.filter(mask).to_pylist()
    if not rows or max(int(row["season"]) for row in rows) >= 2025:
        raise ValueError("sealed strong-model total rows are unavailable")
    return rows


def _benchmark_rows(table: pa.Table, horizon: str) -> list[dict[str, Any]]:
    mask = pc.and_(
        pc.and_(pc.equal(table["horizon"], horizon), pc.equal(table["target"], "total")),
        pc.and_(
            pc.and_(pc.equal(table["point_model_family"], "ridge"), pc.equal(table["point_model_variant"], "full_without_opponent_adjustment")),
            pc.equal(table["distribution_family"], EMPIRICAL_VERSION),
        ),
    )
    return table.filter(mask).to_pylist()


def _candidate_rows(rows: Sequence[Mapping[str, Any]], horizon: str, family: str) -> list[Mapping[str, Any]]:
    return [row for row in rows if row["horizon"] == horizon and row["distribution_family"] == family]


def _summary(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    return {
        "rows": len(rows), "nll": float(np.mean([float(row["nll"]) for row in rows])),
        "crps": float(np.mean([float(row["crps"]) for row in rows])),
        "interval_90_coverage": float(np.mean([float(row["interval_90_covered"]) for row in rows])),
        "interval_90_width": float(np.mean([float(row["interval_90_width"]) for row in rows])),
    }


def summarize_challenger_distributions(
    candidate_rows: Sequence[Mapping[str, Any]],
    benchmark_table: pa.Table,
) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for horizon in sorted({str(row["horizon"]) for row in candidate_rows}):
        benchmark = _benchmark_rows(benchmark_table, horizon)
        normal = _candidate_rows(candidate_rows, horizon, NORMAL_VERSION)
        empirical = _candidate_rows(candidate_rows, horizon, EMPIRICAL_VERSION)
        nll = paired_season_bootstrap(empirical, benchmark, score="nll")
        crps = paired_season_bootstrap(empirical, benchmark, score="crps")
        candidate_summary = _summary(empirical)
        benchmark_summary = _summary(benchmark)
        coverage_error = abs(candidate_summary["interval_90_coverage"] - 0.90)
        benchmark_coverage_error = abs(benchmark_summary["interval_90_coverage"] - 0.90)
        result[horizon] = {
            "catboost_normal": _summary(normal), "catboost_empirical": candidate_summary,
            "ridge_empirical_benchmark": benchmark_summary,
            "paired_catboost_empirical_minus_ridge_empirical": {"nll": nll, "crps": crps},
            "advancement_gates": {
                "nll_interval_below_zero": float(nll["ci_97_5"]) < 0,
                "crps_interval_below_zero": float(crps["ci_97_5"]) < 0,
                "coverage_error_not_worse_by_0_01": coverage_error <= benchmark_coverage_error + 0.01,
            },
        }
        result[horizon]["advancement_gates"]["advances"] = all(
            result[horizon]["advancement_gates"].values()
        )
    return result


def run_challenger_distribution(
    strong_root: Path,
    probability_root: Path,
    output_root: Path,
    *,
    end_season: int = 2024,
) -> dict[str, Any]:
    if end_season >= 2025:
        raise ValueError("locked 2025 holdout cannot enter challenger distributions")
    started = time.perf_counter()
    strong_manifest = json.loads((strong_root / "run_manifest.json").read_text(encoding="utf-8"))
    probability_manifest = json.loads((probability_root / "run_manifest.json").read_text(encoding="utf-8"))
    strong_table = pq.read_table(strong_root / "oof_predictions.parquet")
    rows = _strong_total_rows(strong_table, end_season=end_season)
    probability_rows, fits, pools = build_probability_rows(
        rows, end_season=end_season, selected_families=(NORMAL_VERSION, EMPIRICAL_VERSION)
    )
    table = pa.Table.from_pylist(probability_rows)
    benchmark_table = pq.read_table(probability_root / "oof_probabilities.parquet")
    output_root.mkdir(parents=True, exist_ok=True)
    path = output_root / "oof_challenger_probabilities.parquet"
    pq.write_table(table, path, compression="zstd")
    fits_path = output_root / "distribution_fits.json"
    fits_path.write_text(json.dumps(fits, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    pools_path = output_root / "distribution_pools.json"
    pools_path.write_text(json.dumps(pools, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    manifest: dict[str, Any] = {
        "version": CHALLENGER_DISTRIBUTION_VERSION,
        "experiment_plan": "docs/NCAAF_STRONG_MODEL_EXPERIMENT_PLAN.md",
        "strong_run_hash": strong_manifest["run_hash"],
        "probability_benchmark_run_hash": probability_manifest["run_hash"],
        "dataset_hash": strong_manifest["dataset_hash"], "feature_set_hash": strong_manifest["feature_set_hash"],
        "point_model": ["catboost", "full_v1", "total"],
        "families": [NORMAL_VERSION, EMPIRICAL_VERSION], "evaluation_seasons": [2020, end_season],
        "probability_rows": table.num_rows, "fit_rows": len(fits), "pool_rows": len(pools),
        "probability_schema_hash": schema_hash(table.schema), "probability_content_hash": table_content_hash(table),
        "probability_file_sha256": _sha256(path), "fits_file_sha256": _sha256(fits_path),
        "pools_file_sha256": _sha256(pools_path),
        "summary": summarize_challenger_distributions(probability_rows, benchmark_table),
        "provider_calls": 0, "holdout_accessed": False,
        "elapsed_seconds": round(time.perf_counter() - started, 3),
    }
    deterministic = {key: value for key, value in manifest.items() if key != "elapsed_seconds"}
    manifest["run_hash"] = stable_hash(deterministic)
    (output_root / "run_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return manifest


def validate_challenger_distribution(output_root: Path) -> list[str]:
    errors: list[str] = []
    manifest = json.loads((output_root / "run_manifest.json").read_text(encoding="utf-8"))
    table = pq.read_table(output_root / "oof_challenger_probabilities.parquet")
    if table.num_rows != manifest["probability_rows"]:
        errors.append("challenger probability row count mismatch")
    if max(table["season"].to_pylist()) >= 2025 or manifest["holdout_accessed"]:
        errors.append("locked holdout accessed")
    if table_content_hash(table) != manifest["probability_content_hash"]:
        errors.append("challenger probability content mismatch")
    if _sha256(output_root / "oof_challenger_probabilities.parquet") != manifest["probability_file_sha256"]:
        errors.append("challenger probability file mismatch")
    return errors


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()
