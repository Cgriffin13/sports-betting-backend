from __future__ import annotations

import hashlib
import json
import platform
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import numpy as np
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq
import sklearn

from app.research.ncaaf.artifacts import (
    ResearchArtifactStore,
    artifact_dict,
    dataset_hash,
    schema_hash,
    table_content_hash,
)
from app.research.ncaaf.contracts import stable_hash
from app.research.ncaaf.modeling import feature_columns, make_pipeline, metrics, residual_diagnostics
from app.research.ncaaf.probability import (
    binary_scores,
    fit_empirical_grid,
    moneyline_probabilities,
    multiclass_scores,
    spread_probabilities,
    total_probabilities,
)
from app.research.ncaaf.strong_models import CONFIGURATIONS, make_tree_model

TOURNAMENT_VERSION = "ncaaf-market-aware-tournament-v1"
SCHEMA_VERSION = "ncaaf-market-aware-results-v1"
PROBABILITY_VERSION = "chronological-empirical-market-aware-v1"
BLEND_VERSION = "constrained-oof-least-squares-v1"
PREPROCESSING_VERSION = "fold-local-market-aware-v1"
PRIMARY_HORIZON = "morning_first_kickoff_minus_3h"
FOOTBALL_HORIZON = "game_day_morning"
DEVELOPMENT_SEASONS = (2020, 2021, 2022, 2023)
VALIDATION_SEASON = 2024
SEED = 53107
RIDGE_ALPHA = 100.0
MIN_RESIDUAL_POOL = 100

# Frozen before the tournament is run. These are prior-phase finalists, not a reopened search.
FOOTBALL_FINALISTS: tuple[tuple[str, str, str, str, str], ...] = (
    ("baseline", "margin", "elo", "ncaaf-margin-power-v1", "football_power"),
    ("baseline", "margin", "ridge", "full_v1", "football_ridge_full"),
    ("preseason", "margin", "power", "ncaaf-margin-power-preseason-prior-v1", "football_power_preseason"),
    ("baseline", "total", "ridge", "full_without_opponent_adjustment", "football_ridge_no_opp"),
    ("strong", "total", "catboost", "full_v1", "football_catboost_full"),
    ("preseason", "total", "catboost", "preseason_full", "football_catboost_preseason"),
)
NEW_CANDIDATES: tuple[tuple[str, str, str], ...] = (
    ("margin", "ridge", "market_residual_ridge"),
    ("margin", "ridge", "market_feature_ridge"),
    ("total", "ridge", "market_residual_ridge"),
    ("total", "ridge", "market_feature_ridge"),
    ("total", "catboost", "market_residual_catboost"),
    ("total", "catboost", "market_feature_catboost"),
)
BLEND_COMPONENTS: tuple[tuple[str, str], ...] = (
    ("margin", "football_power_preseason"),
    ("margin", "football_power"),
    ("total", "football_catboost_preseason"),
    ("total", "football_ridge_no_opp"),
)
MARKET_FEATURES = {
    "margin": (
        "market_home_no_vig_probability",
        "market_expected_margin",
        "market_moneyline_books",
        "market_spread_books",
        "market_moneyline_dispersion",
        "market_spread_dispersion",
    ),
    "total": (
        "market_consensus_total",
        "market_total_books",
        "market_total_dispersion",
    ),
}


def _read_current_manifest(root: Path, namespace: str) -> dict[str, Any]:
    return ResearchArtifactStore(root).load_manifest(namespace)


def _artifact_table(root: Path, manifest: Mapping[str, Any], dataset: str) -> pa.Table:
    matches = [item for item in manifest["artifacts"] if item["dataset"] == dataset]
    if len(matches) != 1:
        raise ValueError(f"expected one {dataset} artifact")
    return ResearchArtifactStore(root).read_table(str(matches[0]["uri"]))


def _morning_feature_table(root: Path, manifest: Mapping[str, Any]) -> pa.Table:
    store = ResearchArtifactStore(root)
    for artifact in manifest["artifacts"]:
        if artifact["dataset"] != "model_ready_games":
            continue
        table = store.read_table(str(artifact["uri"]))
        if table.num_rows and table["prediction_horizon"][0].as_py() == FOOTBALL_HORIZON:
            return table
    raise ValueError("morning feature artifact is unavailable")


def canonical_market_rows(feature_rows: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Collapse 7C's candidate-repeated rows to one immutable event/target market state."""
    grouped: dict[tuple[str, str, str], list[Mapping[str, Any]]] = defaultdict(list)
    for row in feature_rows:
        if int(row["season"]) >= 2025:
            raise ValueError("locked 2025 holdout entered market-aware tournament")
        if row["horizon"] != PRIMARY_HORIZON or row["research_role"] != "primary":
            continue
        grouped[(str(row["canonical_event_id"]), str(row["target"]), str(row["horizon"]))].append(row)
    output: list[dict[str, Any]] = []
    immutable = (
        "actual",
        "season",
        "week",
        "market_home_no_vig_probability",
        "market_home_spread",
        "market_expected_margin",
        "market_consensus_total",
        "source_market_dataset_hash",
    )
    for key, rows in sorted(grouped.items()):
        anchor = dict(rows[0])
        for row in rows[1:]:
            if any(row.get(name) != anchor.get(name) for name in immutable):
                raise ValueError(f"candidate rows disagree on market state: {key}")
        output.append(anchor)
    return output


def _consensus_lookup(consensus: pa.Table) -> dict[tuple[str, str], dict[str, Any]]:
    result: dict[tuple[str, str], dict[str, Any]] = {}
    for row in consensus.to_pylist():
        if row["horizon"] == PRIMARY_HORIZON:
            result[(str(row["canonical_event_id"]), str(row["market_type"]))] = row
    return result


def _load_existing_predictions(root: Path) -> dict[str, list[dict[str, Any]]]:
    paths = {
        "baseline": root / "models" / "baseline-v1" / "oof_predictions.parquet",
        "strong": root / "models" / "strong-v1" / "oof_predictions.parquet",
        "preseason": root / "models" / "preseason-v1" / "oof_preseason_predictions.parquet",
    }
    result: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for source, target, family, variant, candidate in FOOTBALL_FINALISTS:
        table = pq.read_table(paths[source])
        mask = pc.and_(
            pc.equal(table["horizon"], FOOTBALL_HORIZON),
            pc.and_(
                pc.equal(table["target"], target),
                pc.and_(pc.equal(table["model_family"], family), pc.equal(table["variant"], variant)),
            ),
        )
        for row in table.filter(mask).to_pylist():
            if int(row["season"]) >= 2025 or int(row["training_cutoff"]) >= int(row["season"]):
                raise ValueError("non-OOF or holdout football prediction rejected")
            row["candidate"] = candidate
            row["architecture"] = "football_only"
            row["source_run"] = source
            result[target].append(row)
    return result


def _quality(row: Mapping[str, Any]) -> str:
    values = [row.get("home_pbp_coverage_ratio"), row.get("away_pbp_coverage_ratio")]
    return "high" if all(value is not None and float(value) >= 0.8 for value in values) else "low"


def _point_row(
    market: Mapping[str, Any],
    *,
    candidate: str,
    architecture: str,
    prediction: float,
    training_cutoff: int | None,
    parameters: Mapping[str, Any],
) -> dict[str, Any]:
    target = str(market["target"])
    expectation_key = "market_expected_margin" if target == "margin" else "market_consensus_total"
    expected = float(market.get(expectation_key, market.get("market_expectation")))
    actual = float(market["actual"])
    return {
        "canonical_event_id": market["canonical_event_id"],
        "season": int(market["season"]),
        "week": int(market["week"]),
        "target": target,
        "horizon": PRIMARY_HORIZON,
        "research_role": "primary",
        "actual": actual,
        "prediction": float(prediction),
        "residual": actual - float(prediction),
        "market_expectation": expected,
        "model_market_disagreement": float(prediction) - expected,
        "candidate": candidate,
        "architecture": architecture,
        "model_version": TOURNAMENT_VERSION,
        "training_cutoff": training_cutoff,
        "fold_id": f"market_train_through_{training_cutoff}_evaluate_{market['season']}" if training_cutoff else "market_baseline",
        "model_parameters": json.dumps(parameters, sort_keys=True, separators=(",", ":")),
        "market_home_no_vig_probability": market.get("market_home_no_vig_probability"),
        "market_home_spread": market.get("market_home_spread"),
        "market_consensus_total": market.get("market_consensus_total"),
        "market_book_depth": min(
            int(market.get("market_moneyline_books") or 99),
            int(market.get("market_spread_books") or market.get("market_total_books") or 99),
        ),
        "market_dispersion": max(
            float(market.get("market_moneyline_dispersion") or 0),
            float(market.get("market_spread_dispersion") or market.get("market_total_dispersion") or 0),
        ),
        "quality_level": market.get("quality_level", _quality(market)),
        "feature_set_hash": market["feature_set_hash"],
        "football_dataset_hash": market["football_dataset_hash"],
        "market_dataset_hash": market.get("source_market_dataset_hash", market.get("market_dataset_hash")),
    }


def _market_baselines(markets: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for market in markets:
        prediction = market["market_expected_margin"] if market["target"] == "margin" else market["market_consensus_total"]
        rows.append(
            _point_row(
                market,
                candidate="market_consensus",
                architecture="market_only",
                prediction=float(prediction),
                training_cutoff=None,
                parameters={"consensus": "unweighted-median-v1", "vig": "proportional-v1"},
            )
        )
    return rows


def _football_rows(
    markets: Sequence[Mapping[str, Any]], predictions: Mapping[str, Sequence[Mapping[str, Any]]]
) -> list[dict[str, Any]]:
    by_market = {(str(row["canonical_event_id"]), str(row["target"])): row for row in markets}
    output = []
    for target_rows in predictions.values():
        for source in target_rows:
            market = by_market.get((str(source["canonical_event_id"]), str(source["target"])))
            if market is None:
                continue
            output.append(
                _point_row(
                    market,
                    candidate=str(source["candidate"]),
                    architecture="football_only",
                    prediction=float(source["prediction"]),
                    training_cutoff=int(source["training_cutoff"]),
                    parameters={"source_run": source["source_run"], "source_model_version": source["model_version"]},
                )
            )
    return output


def _numeric_matrix(rows: Sequence[Mapping[str, Any]], columns: Sequence[str]) -> np.ndarray:
    return np.asarray(
        [[np.nan if row.get(name) is None else float(row[name]) for name in columns] for row in rows],
        dtype=np.float64,
    )


def _train_new_candidates(
    markets: Sequence[Mapping[str, Any]], feature_table: pa.Table
) -> list[dict[str, Any]]:
    feature_by_id = {str(row["canonical_event_id"]): row for row in feature_table.to_pylist()}
    standard_columns = feature_columns(feature_table, "full_v1")
    output: list[dict[str, Any]] = []
    for target, family, candidate in NEW_CANDIDATES:
        rows = [dict(row) for row in markets if row["target"] == target and str(row["canonical_event_id"]) in feature_by_id]
        rows.sort(key=lambda row: (int(row["season"]), row["scheduled_kickoff"], str(row["canonical_event_id"])))
        model_columns = list(standard_columns)
        if "market_feature" in candidate:
            model_columns.extend(MARKET_FEATURES[target])
        merged = [{**feature_by_id[str(row["canonical_event_id"])], **row} for row in rows]
        for season in (2021, 2022, 2023, 2024):
            train = [row for row in merged if 2020 <= int(row["season"]) < season]
            evaluate = [row for row in merged if int(row["season"]) == season]
            if not train or not evaluate:
                continue
            x_train = _numeric_matrix(train, model_columns)
            x_eval = _numeric_matrix(evaluate, model_columns)
            if "residual" in candidate:
                y_train = np.asarray(
                    [float(row["actual"]) - float(row["market_expected_margin"] if target == "margin" else row["market_consensus_total"]) for row in train]
                )
            else:
                y_train = np.asarray([float(row["actual"]) for row in train])
            if family == "ridge":
                model = make_pipeline("ridge", {"alpha": RIDGE_ALPHA})
            else:
                model = make_tree_model("catboost", CONFIGURATIONS[0])
            model.fit(x_train, y_train)
            predicted = np.asarray(model.predict(x_eval), dtype=float)
            if "residual" in candidate:
                predicted += np.asarray(
                    [float(row["market_expected_margin"] if target == "margin" else row["market_consensus_total"]) for row in evaluate]
                )
            parameters = {
                "family": family,
                "variant": "residual" if "residual" in candidate else "market_as_feature",
                "ridge_alpha": RIDGE_ALPHA if family == "ridge" else None,
                "tree_configuration": CONFIGURATIONS[0]["name"] if family == "catboost" else None,
                "feature_count": len(model_columns),
                "training_rows": len(train),
                "preprocessing_version": PREPROCESSING_VERSION,
            }
            for row, value in zip(evaluate, predicted, strict=True):
                output.append(
                    _point_row(
                        row,
                        candidate=candidate,
                        architecture="market_residual" if "residual" in candidate else "market_as_feature",
                        prediction=float(value),
                        training_cutoff=season - 1,
                        parameters=parameters,
                    )
                )
    return output


def constrained_blend_weight(rows: Sequence[Mapping[str, Any]]) -> float:
    if not rows:
        raise ValueError("blend requires prior OOF rows")
    delta = np.asarray([float(row["football_prediction"]) - float(row["market_prediction"]) for row in rows])
    target = np.asarray([float(row["actual"]) - float(row["market_prediction"]) for row in rows])
    denominator = float(np.dot(delta, delta))
    return float(np.clip(np.dot(delta, target) / denominator if denominator else 0.0, 0.0, 1.0))


def _blend_rows(point_rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    index = {(str(row["canonical_event_id"]), str(row["candidate"])): row for row in point_rows}
    market_rows = [row for row in point_rows if row["candidate"] == "market_consensus"]
    output: list[dict[str, Any]] = []
    for target, football_candidate in BLEND_COMPONENTS:
        paired = []
        for market in market_rows:
            if market["target"] != target:
                continue
            football = index.get((str(market["canonical_event_id"]), football_candidate))
            if football is not None:
                paired.append(
                    {
                        "market": market,
                        "actual": market["actual"],
                        "market_prediction": market["prediction"],
                        "football_prediction": football["prediction"],
                    }
                )
        for season in (2021, 2022, 2023, 2024):
            training = [row for row in paired if int(row["market"]["season"]) < season]
            evaluate = [row for row in paired if int(row["market"]["season"]) == season]
            if not training or not evaluate:
                continue
            weight = constrained_blend_weight(training)
            for row in evaluate:
                market = row["market"]
                value = float(row["market_prediction"]) + weight * (
                    float(row["football_prediction"]) - float(row["market_prediction"])
                )
                output.append(
                    _point_row(
                        market,
                        candidate=f"blend_{football_candidate}",
                        architecture="oof_blend",
                        prediction=value,
                        training_cutoff=season - 1,
                        parameters={
                            "version": BLEND_VERSION,
                            "football_candidate": football_candidate,
                            "football_weight": weight,
                            "market_weight": 1.0 - weight,
                            "training_rows": len(training),
                        },
                    )
                )
    return output


def _outcome_label(row: Mapping[str, Any]) -> str:
    if row["target"] == "margin":
        value = float(row["actual"]) + float(row["market_home_spread"])
        return "win" if value > 0 else "loss" if value < 0 else "push"
    value = float(row["actual"]) - float(row["market_consensus_total"])
    return "win" if value > 0 else "loss" if value < 0 else "push"


def _probability_rows(
    point_rows: Sequence[Mapping[str, Any]],
    consensus: Mapping[tuple[str, str], Mapping[str, Any]],
) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str], list[Mapping[str, Any]]] = defaultdict(list)
    for row in point_rows:
        grouped[(str(row["target"]), str(row["candidate"]))].append(row)
    output = []
    for (target, candidate), candidates in sorted(grouped.items()):
        candidates.sort(key=lambda row: (int(row["season"]), str(row["canonical_event_id"])))
        for row in candidates:
            season = int(row["season"])
            prior = [item for item in candidates if int(item["season"]) < season]
            if len(prior) < MIN_RESIDUAL_POOL:
                continue
            residuals = [float(item["actual"]) - float(item["prediction"]) for item in prior]
            distribution = fit_empirical_grid(
                residuals,
                pool_id=stable_hash({"target": target, "candidate": candidate, "cutoff": season - 1}),
            )
            distribution = type(distribution)(
                float(row["prediction"]),
                distribution.scale,
                distribution.residual_grid,
                distribution.residual_cdf,
                distribution.residual_pdf,
                distribution.pool_id,
                distribution.bandwidth,
            )
            if row["target"] == "margin":
                settlement = spread_probabilities(distribution, float(row["market_home_spread"]))
                moneyline = moneyline_probabilities(distribution)
                market_state = consensus[(str(row["canonical_event_id"]), "spreads")]
                market_probability = float(market_state["side_1_consensus_probability"])
            else:
                settlement = total_probabilities(distribution, float(row["market_consensus_total"]))
                moneyline = None
                market_state = consensus[(str(row["canonical_event_id"]), "totals")]
                market_probability = float(market_state["side_1_consensus_probability"])
            outcome = _outcome_label(row)
            multi = multiclass_scores(settlement, outcome)
            market_conditional = binary_scores(market_probability, outcome == "win") if outcome != "push" else None
            result = {
                **dict(row),
                "distribution_version": PROBABILITY_VERSION,
                "distribution_family": distribution.family,
                "predicted_scale": distribution.scale,
                "residual_pool_rows": len(prior),
                "residual_pool_id": distribution.pool_id,
                "line_win_probability": settlement.win,
                "line_push_probability": settlement.push,
                "line_loss_probability": settlement.loss,
                "line_outcome": outcome,
                "multiclass_brier": multi["brier"],
                "multiclass_log_loss": multi["log_loss"],
                "market_conditional_win_probability": market_probability,
                "market_conditional_nonpush": True,
                "market_conditional_brier": market_conditional["brier"] if market_conditional else None,
                "market_conditional_log_loss": market_conditional["log_loss"] if market_conditional else None,
            }
            if moneyline is not None:
                actual_home_win = float(row["actual"]) > 0
                home_probability = (
                    float(row["market_home_no_vig_probability"])
                    if candidate == "market_consensus"
                    else moneyline.win
                )
                score = binary_scores(home_probability, actual_home_win)
                result.update(
                    {
                        "home_win_probability": home_probability,
                        "away_win_probability": 1.0 - home_probability,
                        "moneyline_brier": score["brier"],
                        "moneyline_log_loss": score["log_loss"],
                        "moneyline_probability_source": (
                            "market_no_vig_consensus" if candidate == "market_consensus" else PROBABILITY_VERSION
                        ),
                    }
                )
            output.append(result)
    return output


def _metric_summary(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    values: dict[str, Any] = metrics(
        np.asarray([float(row["actual"]) for row in rows]),
        np.asarray([float(row["prediction"]) for row in rows]),
    )
    values["rows"] = len(rows)
    values["residual_diagnostics"] = residual_diagnostics(
        np.asarray([float(row["actual"]) for row in rows]),
        np.asarray([float(row["prediction"]) for row in rows]),
    )
    return values


def _point_segments(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    buckets: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in rows:
        expectation = float(row["market_expectation"])
        disagreement = abs(float(row["model_market_disagreement"]))
        if row["target"] == "margin":
            buckets["home_favorite" if expectation > 0 else "home_underdog_or_pickem"].append(row)
            magnitude = abs(expectation)
            buckets["spread_0_3" if magnitude < 3 else "spread_3_7" if magnitude < 7 else "spread_7_plus"].append(row)
        else:
            buckets["total_below_45" if expectation < 45 else "total_45_60" if expectation < 60 else "total_60_plus"].append(row)
        buckets["disagreement_0_3" if disagreement < 3 else "disagreement_3_7" if disagreement < 7 else "disagreement_7_plus"].append(row)
        buckets[f"book_depth_{'3_plus' if int(row['market_book_depth']) >= 3 else '2'}"].append(row)
        buckets[f"dispersion_{'low' if float(row['market_dispersion']) <= 0.02 else 'high'}"].append(row)
        buckets[f"quality_{row['quality_level']}"] .append(row)
    return {name: _metric_summary(bucket) for name, bucket in sorted(buckets.items()) if bucket}


def _calibration_bins(rows: Sequence[Mapping[str, Any]], probability_key: str, outcome_key: str) -> list[dict[str, Any]]:
    bins: list[dict[str, Any]] = []
    for lower in np.arange(0.0, 1.0, 0.1):
        upper = lower + 0.1
        selected = [
            row
            for row in rows
            if row.get(probability_key) is not None
            and lower <= float(row[probability_key]) <= upper
            and (lower == 0.9 or float(row[probability_key]) < upper)
        ]
        if not selected:
            continue
        predicted = float(np.mean([float(row[probability_key]) for row in selected]))
        observed = float(np.mean([1.0 if row[outcome_key] else 0.0 for row in selected]))
        bins.append(
            {
                "lower": float(lower),
                "upper": float(upper),
                "rows": len(selected),
                "mean_probability": predicted,
                "observed_frequency": observed,
                "gap": predicted - observed,
            }
        )
    return bins


def _bootstrap_difference(
    candidate: Sequence[Mapping[str, Any]], market: Sequence[Mapping[str, Any]], iterations: int = 2000
) -> dict[str, float]:
    market_by_id = {str(row["canonical_event_id"]): row for row in market}
    paired = [(row, market_by_id[str(row["canonical_event_id"])]) for row in candidate if str(row["canonical_event_id"]) in market_by_id]
    by_season: dict[int, list[float]] = defaultdict(list)
    for left, right in paired:
        by_season[int(left["season"])].append(
            abs(float(left["actual"]) - float(left["prediction"]))
            - abs(float(right["actual"]) - float(right["prediction"]))
        )
    seasons = sorted(by_season)
    rng = np.random.default_rng(SEED)
    samples = []
    for _ in range(iterations):
        selected = rng.choice(seasons, size=len(seasons), replace=True)
        samples.append(float(np.mean([value for season in selected for value in by_season[int(season)]])))
    return {
        "candidate_minus_market_mae": float(np.mean([value for values in by_season.values() for value in values])),
        "ci_2_5": float(np.quantile(samples, 0.025)),
        "ci_97_5": float(np.quantile(samples, 0.975)),
        "paired_games": len(paired),
    }


def _paired_score_difference(
    candidate: Sequence[Mapping[str, Any]],
    market: Sequence[Mapping[str, Any]],
    field: str,
    *,
    iterations: int = 2000,
) -> dict[str, float]:
    market_by_id = {str(row["canonical_event_id"]): row for row in market}
    by_season: dict[int, list[float]] = defaultdict(list)
    for row in candidate:
        baseline = market_by_id.get(str(row["canonical_event_id"]))
        if baseline is None or row.get(field) is None or baseline.get(field) is None:
            continue
        by_season[int(row["season"])].append(float(row[field]) - float(baseline[field]))
    seasons = sorted(by_season)
    if not seasons:
        return {"candidate_minus_market": 0.0, "ci_2_5": 0.0, "ci_97_5": 0.0, "paired_games": 0}
    rng = np.random.default_rng(SEED)
    samples = []
    for _ in range(iterations):
        selected = rng.choice(seasons, size=len(seasons), replace=True)
        samples.append(float(np.mean([value for season in selected for value in by_season[int(season)]])))
    values = [value for season_values in by_season.values() for value in season_values]
    return {
        "candidate_minus_market": float(np.mean(values)),
        "ci_2_5": float(np.quantile(samples, 0.025)),
        "ci_97_5": float(np.quantile(samples, 0.975)),
        "paired_games": len(values),
    }


def summarize_run(point_rows: Sequence[Mapping[str, Any]], probability_rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    grouped: dict[tuple[str, str], list[Mapping[str, Any]]] = defaultdict(list)
    for row in point_rows:
        grouped[(str(row["target"]), str(row["candidate"]))].append(row)
    point_metrics: dict[str, Any] = {}
    comparisons: dict[str, Any] = {}
    for (target, candidate), rows in sorted(grouped.items()):
        key = f"{target}|{candidate}"
        point_metrics[key] = {
            "overall": _metric_summary(rows),
            "development_2020_2023": _metric_summary([row for row in rows if int(row["season"]) <= 2023]),
            "validation_2024": _metric_summary([row for row in rows if int(row["season"]) == 2024]),
            "by_season": {str(season): _metric_summary([row for row in rows if int(row["season"]) == season]) for season in sorted({int(row["season"]) for row in rows})},
            "early_season": _metric_summary([row for row in rows if int(row["week"]) <= 3]),
            "later_season": _metric_summary([row for row in rows if int(row["week"]) > 3]),
            "segments": _point_segments(rows),
        }
        if candidate != "market_consensus":
            market = grouped.get((target, "market_consensus"), [])
            comparisons[key] = _bootstrap_difference(rows, market)
    probability_metrics: dict[str, Any] = {}
    probability_comparisons: dict[str, Any] = {}
    for target, candidate in sorted({(str(row["target"]), str(row["candidate"])) for row in probability_rows}):
        rows = [row for row in probability_rows if row["candidate"] == candidate and row["target"] == target]
        key = f"{target}|{candidate}"
        enriched = [{**row, "line_win_observed": row["line_outcome"] == "win", "home_win_observed": float(row["actual"]) > 0} for row in rows]
        probability_metrics[key] = {
            "rows": len(rows),
            "multiclass_brier": float(np.mean([float(row["multiclass_brier"]) for row in rows])),
            "multiclass_log_loss": float(np.mean([float(row["multiclass_log_loss"]) for row in rows])),
            "mean_push_probability": float(np.mean([float(row["line_push_probability"]) for row in rows])),
            "moneyline_brier": float(np.mean([float(row["moneyline_brier"]) for row in rows if row.get("moneyline_brier") is not None])) if any(row.get("moneyline_brier") is not None for row in rows) else None,
            "moneyline_log_loss": float(np.mean([float(row["moneyline_log_loss"]) for row in rows if row.get("moneyline_log_loss") is not None])) if any(row.get("moneyline_log_loss") is not None for row in rows) else None,
            "market_conditional_nonpush_brier": float(np.mean([float(row["market_conditional_brier"]) for row in rows if row.get("market_conditional_brier") is not None])),
            "market_conditional_nonpush_log_loss": float(np.mean([float(row["market_conditional_log_loss"]) for row in rows if row.get("market_conditional_log_loss") is not None])),
            "validation_2024": {
                "rows": sum(int(row["season"]) == 2024 for row in rows),
                "multiclass_brier": float(np.mean([float(row["multiclass_brier"]) for row in rows if int(row["season"]) == 2024])),
                "multiclass_log_loss": float(np.mean([float(row["multiclass_log_loss"]) for row in rows if int(row["season"]) == 2024])),
                "moneyline_brier": float(np.mean([float(row["moneyline_brier"]) for row in rows if int(row["season"]) == 2024 and row.get("moneyline_brier") is not None])) if any(int(row["season"]) == 2024 and row.get("moneyline_brier") is not None for row in rows) else None,
                "moneyline_log_loss": float(np.mean([float(row["moneyline_log_loss"]) for row in rows if int(row["season"]) == 2024 and row.get("moneyline_log_loss") is not None])) if any(int(row["season"]) == 2024 and row.get("moneyline_log_loss") is not None for row in rows) else None,
            },
            "line_reliability": _calibration_bins(enriched, "line_win_probability", "line_win_observed"),
            "moneyline_reliability": _calibration_bins(enriched, "home_win_probability", "home_win_observed") if target == "margin" else [],
        }
        if candidate != "market_consensus":
            market = [row for row in probability_rows if row["target"] == target and row["candidate"] == "market_consensus"]
            probability_comparisons[key] = {
                "multiclass_brier": _paired_score_difference(rows, market, "multiclass_brier"),
                "multiclass_log_loss": _paired_score_difference(rows, market, "multiclass_log_loss"),
                "moneyline_brier": _paired_score_difference(rows, market, "moneyline_brier") if target == "margin" else None,
                "moneyline_log_loss": _paired_score_difference(rows, market, "moneyline_log_loss") if target == "margin" else None,
            }
    return {
        "point_metrics": point_metrics,
        "probability_metrics": probability_metrics,
        "paired_market_comparisons": comparisons,
        "paired_probability_comparisons": probability_comparisons,
    }


def later_horizon_diagnostics(market_features: pa.Table, consensus: pa.Table) -> dict[str, Any]:
    rows = [row for row in market_features.to_pylist() if row["research_role"] == "diagnostic_only"]
    by_key: dict[tuple[str, str, str, str], Mapping[str, Any]] = {}
    for row in rows:
        key = (
            str(row["target"]),
            str(row["model_family"]),
            str(row["model_variant"]),
            str(row["canonical_event_id"]),
        )
        by_key[key] = row
    metrics_by_candidate: dict[str, Any] = {}
    for target, family, variant in sorted({key[:3] for key in by_key}):
        selected = [row for key, row in by_key.items() if key[:3] == (target, family, variant)]
        actual = np.asarray([float(row["actual"]) for row in selected])
        football = np.asarray([float(row["football_prediction"]) for row in selected])
        market = np.asarray(
            [
                float(row["market_expected_margin"] if target == "margin" else row["market_consensus_total"])
                for row in selected
            ]
        )
        metrics_by_candidate[f"{target}|{family}|{variant}"] = {
            "games": len(selected),
            "football": metrics(actual, football),
            "market": metrics(actual, market),
            "role": "diagnostic_only",
        }
    consensus_rows = consensus.to_pylist()
    return {
        "sixty_minute": metrics_by_candidate,
        "near_close_consensus_rows": dict(
            sorted(
                Counter(
                    str(row["market_type"])
                    for row in consensus_rows
                    if row["horizon"] == "near_close_5_minutes"
                ).items()
            )
        ),
        "selection_eligible": False,
        "note": "The bounded sample is diagnostic only; near-close has no same-horizon football OOF prediction.",
    }


def _table(rows: Sequence[Mapping[str, Any]]) -> pa.Table:
    if not rows:
        raise ValueError("cannot persist an empty tournament artifact")
    columns = sorted({key for row in rows for key in row})
    return pa.Table.from_pylist([{key: row.get(key) for key in columns} for row in rows])


def build_market_aware_tournament(root: Path, *, output_namespace: str = "market-aware-v1") -> dict[str, Any]:
    started = time.perf_counter()
    store = ResearchArtifactStore(root)
    comparison_manifest = _read_current_manifest(root, "market-comparison")
    feature_manifest = _read_current_manifest(root, "features")
    market_table = _artifact_table(root, comparison_manifest, "market_features")
    consensus_table = _artifact_table(root, comparison_manifest, "market_consensus")
    markets = canonical_market_rows(market_table.to_pylist())
    features = _morning_feature_table(root, feature_manifest)
    feature_quality = {
        str(row["canonical_event_id"]): row
        for row in features.select(
            [
                "canonical_event_id",
                "home_pbp_coverage_ratio",
                "away_pbp_coverage_ratio",
                "home_current_season_games",
                "away_current_season_games",
            ]
        ).to_pylist()
    }
    markets = [{**feature_quality.get(str(row["canonical_event_id"]), {}), **row} for row in markets]
    point_rows = _market_baselines(markets)
    point_rows.extend(_football_rows(markets, _load_existing_predictions(root)))
    point_rows.extend(_train_new_candidates(markets, features))
    point_rows.extend(_blend_rows(point_rows))
    point_rows.sort(key=lambda row: (row["target"], row["candidate"], row["season"], row["canonical_event_id"]))
    probability_rows = _probability_rows(point_rows, _consensus_lookup(consensus_table))
    probability_rows.sort(key=lambda row: (row["target"], row["candidate"], row["season"], row["canonical_event_id"]))
    summary = summarize_run(point_rows, probability_rows)
    summary["later_horizon_diagnostics"] = later_horizon_diagnostics(market_table, consensus_table)
    sources = [
        {"id": comparison_manifest["manifest_id"], "content_hash": comparison_manifest["dataset_hash"]},
        {"id": feature_manifest["manifest_id"], "content_hash": feature_manifest["dataset_hash"]},
    ]
    artifacts = []
    for name, rows in (("point_predictions", point_rows), ("probability_predictions", probability_rows)):
        artifact = store.write_parquet(
            _table(rows),
            namespace=output_namespace,
            dataset=name,
            season=None,
            schema_version=SCHEMA_VERSION,
            transformation_version=TOURNAMENT_VERSION,
            source_manifests=sources,
            sort_by=(("target", "ascending"), ("candidate", "ascending"), ("season", "ascending"), ("canonical_event_id", "ascending")),
        )
        artifacts.append(artifact_dict(artifact))
    summary_path = root / output_namespace / "summary.json"
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    config = {
        "tournament_version": TOURNAMENT_VERSION,
        "probability_version": PROBABILITY_VERSION,
        "blend_version": BLEND_VERSION,
        "primary_horizon": PRIMARY_HORIZON,
        "development_seasons": list(DEVELOPMENT_SEASONS),
        "validation_season": VALIDATION_SEASON,
        "ridge_alpha": RIDGE_ALPHA,
        "football_finalists": FOOTBALL_FINALISTS,
        "new_candidates": NEW_CANDIDATES,
        "blend_components": BLEND_COMPONENTS,
        "seed": SEED,
    }
    elapsed = time.perf_counter() - started
    (root / output_namespace / "runtime.json").write_text(
        json.dumps({"runtime_seconds": elapsed}, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    manifest: dict[str, Any] = {
        **config,
        "source_market_comparison_manifest": comparison_manifest["manifest_id"],
        "source_market_comparison_hash": comparison_manifest["dataset_hash"],
        "source_market_dataset_hash": comparison_manifest["source_market_dataset_hash"],
        "source_feature_manifest": feature_manifest["manifest_id"],
        "source_feature_dataset_hash": feature_manifest["dataset_hash"],
        "feature_set_hash": feature_manifest["feature_set_hash"],
        "artifacts": artifacts,
        "point_rows": len(point_rows),
        "probability_rows": len(probability_rows),
        "summary_hash": stable_hash(summary),
        "provider_calls": 0,
        "holdout_accessed": False,
        "package_versions": {
            "python": platform.python_version(),
            "numpy": np.__version__,
            "pyarrow": pa.__version__,
            "scikit_learn": sklearn.__version__,
        },
    }
    manifest["dataset_hash"] = dataset_hash(artifacts, config)
    manifest_id, _ = store.write_manifest(output_namespace, manifest)
    manifest["manifest_id"] = manifest_id
    return manifest


def validate_market_aware_tournament(root: Path, manifest: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    store = ResearchArtifactStore(root)
    for artifact in manifest["artifacts"]:
        errors.extend(store.validate_artifact(artifact))
        table = store.read_table(str(artifact["uri"]))
        if "season" in table.schema.names and any(int(value) >= 2025 for value in table["season"].to_pylist()):
            errors.append(f"2025 holdout found in {artifact['dataset']}")
        if "horizon" in table.schema.names and set(table["horizon"].to_pylist()) != {PRIMARY_HORIZON}:
            errors.append(f"non-morning rows found in {artifact['dataset']}")
    if manifest.get("provider_calls") != 0 or manifest.get("holdout_accessed") is not False:
        errors.append("provider/holdout invariant failed")
    config_keys = (
        "tournament_version",
        "probability_version",
        "blend_version",
        "primary_horizon",
        "development_seasons",
        "validation_season",
        "ridge_alpha",
        "football_finalists",
        "new_candidates",
        "blend_components",
        "seed",
    )
    expected = dataset_hash(manifest["artifacts"], {key: manifest[key] for key in config_keys})
    if expected != manifest["dataset_hash"]:
        errors.append("dataset hash mismatch")
    point = next(store.read_table(str(item["uri"])) for item in manifest["artifacts"] if item["dataset"] == "point_predictions")
    rows = point.to_pylist()
    for target in ("margin", "total"):
        market_ids = {row["canonical_event_id"] for row in rows if row["target"] == target and row["candidate"] == "market_consensus"}
        for candidate in {row["candidate"] for row in rows if row["target"] == target}:
            candidate_rows = [row for row in rows if row["target"] == target and row["candidate"] == candidate]
            if any(row["canonical_event_id"] not in market_ids for row in candidate_rows):
                errors.append(f"candidate outside market cohort: {target}/{candidate}")
            if candidate != "market_consensus" and any(
                row["training_cutoff"] is not None and int(row["training_cutoff"]) >= int(row["season"])
                for row in candidate_rows
            ):
                errors.append(f"non-OOF prediction: {target}/{candidate}")
        expected_market_ids = {
            row["canonical_event_id"]
            for row in rows
            if row["target"] == target and row["candidate"] == "market_consensus" and int(row["season"]) >= 2021
        }
        market_aware_candidates = {
            str(row["candidate"])
            for row in rows
            if row["target"] == target and row["architecture"] in {"market_residual", "market_as_feature", "oof_blend"}
        }
        for candidate in market_aware_candidates:
            candidate_ids = {
                row["canonical_event_id"]
                for row in rows
                if row["target"] == target and row["candidate"] == candidate
            }
            if candidate_ids != expected_market_ids:
                errors.append(f"common cohort mismatch: {target}/{candidate}")
    return errors


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def artifact_integrity(root: Path, manifest: Mapping[str, Any]) -> dict[str, Any]:
    store = ResearchArtifactStore(root)
    return {
        item["dataset"]: {
            "rows": store.read_table(str(item["uri"])).num_rows,
            "schema_hash": schema_hash(store.read_table(str(item["uri"])).schema),
            "content_hash": table_content_hash(store.read_table(str(item["uri"])),),
            "file_sha256": file_sha256(root / str(item["uri"])),
        }
        for item in manifest["artifacts"]
    }
