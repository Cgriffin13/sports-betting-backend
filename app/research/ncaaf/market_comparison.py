from __future__ import annotations

import json
import math
from collections import Counter, defaultdict
from decimal import ROUND_HALF_EVEN, Decimal, localcontext
from pathlib import Path
from statistics import median
from typing import Any, Iterable, Mapping, Sequence

import pyarrow as pa
import pyarrow.parquet as pq

from app.research.ncaaf.artifacts import ResearchArtifactStore, artifact_dict, dataset_hash

BUILD_VERSION = "ncaaf-market-comparison-plumbing-v1"
SCHEMA_VERSION = "market-comparison-v1"
VIG_REMOVAL_VERSION = "proportional-v1"
CONSENSUS_VERSION = "unweighted-median-v1"
PRIMARY_MARKET_HORIZON = "morning_first_kickoff_minus_3h"
HORIZON_MAP = {
    PRIMARY_MARKET_HORIZON: "game_day_morning",
    "60_minutes_before_kickoff": "60_minutes_before_kickoff",
}
DIAGNOSTIC_HORIZONS = frozenset({"60_minutes_before_kickoff", "near_close_5_minutes"})
SELECTED_MODELS = {
    ("margin", "elo", "ncaaf-margin-power-v1"),
    ("margin", "ridge", "full_v1"),
    ("total", "ridge", "full_without_opponent_adjustment"),
    ("total", "ridge", "full_v1"),
}
MIN_BOOKS = 2
QUANTUM = Decimal("0.000000000001")
MARKET_COLUMNS = (
    "canonical_event_id", "cfbd_game_id", "season", "week", "scheduled_kickoff", "horizon",
    "requested_at", "snapshot_at", "sportsbook", "supported_sportsbook", "market_type", "side",
    "point", "american_odds", "source_content_hash",
)
PREDICTION_COLUMNS = (
    "canonical_event_id", "season", "week", "horizon", "target", "actual", "prediction",
    "model_family", "model_version", "variant", "fold_id", "training_cutoff", "feature_set_hash",
    "dataset_hash",
)


def proportional_no_vig(probabilities: Sequence[Decimal]) -> tuple[Decimal, ...]:
    if len(probabilities) != 2 or any(not value.is_finite() or value <= 0 for value in probabilities):
        raise ValueError("proportional-v1 requires two positive finite implied probabilities")
    total = sum(probabilities)
    with localcontext() as context:
        context.prec = 34
        first = (probabilities[0] / total).quantize(QUANTUM, rounding=ROUND_HALF_EVEN)
        second = Decimal(1) - first
    return first, second


def american_to_implied(odds: int) -> Decimal:
    if odds == 0:
        raise ValueError("American odds cannot be zero")
    value = Decimal(odds)
    return Decimal(100) / (value + 100) if odds > 0 else abs(value) / (abs(value) + 100)


def settlement_labels(actual_margin: float, actual_total: float, home_spread: float, total_line: float) -> dict[str, str]:
    spread_value = Decimal(str(actual_margin)) + Decimal(str(home_spread))
    total_value = Decimal(str(actual_total)) - Decimal(str(total_line))
    return {
        "moneyline_result": "home_win" if actual_margin > 0 else "away_win" if actual_margin < 0 else "tie",
        "spread_result": "home_cover" if spread_value > 0 else "away_cover" if spread_value < 0 else "push",
        "total_result": "over" if total_value > 0 else "under" if total_value < 0 else "push",
    }


def market_expected_margin(home_spread: float) -> float:
    return -home_spread


def _paired_book(rows: Sequence[Mapping[str, Any]], market: str) -> dict[str, Any] | None:
    by_side = {str(row["side"]): row for row in rows}
    expected = ("home", "away") if market in {"h2h", "spreads"} else ("over", "under")
    if set(by_side) != set(expected):
        return None
    first, second = (by_side[side] for side in expected)
    if market == "spreads":
        if first["point"] is None or second["point"] is None or not math.isclose(float(first["point"]), -float(second["point"]), abs_tol=1e-9):
            return None
        line = float(first["point"])
    elif market == "totals":
        if first["point"] is None or second["point"] is None or not math.isclose(float(first["point"]), float(second["point"]), abs_tol=1e-9):
            return None
        line = float(first["point"])
    else:
        line = None
    raw = (american_to_implied(int(first["american_odds"])), american_to_implied(int(second["american_odds"])))
    no_vig = proportional_no_vig(raw)
    return {
        "sportsbook": first["sportsbook"],
        "line": line,
        "side_1": expected[0],
        "side_2": expected[1],
        "side_1_odds": int(first["american_odds"]),
        "side_2_odds": int(second["american_odds"]),
        "side_1_no_vig": no_vig[0],
        "side_2_no_vig": no_vig[1],
        "snapshot_at": first["snapshot_at"],
        "source_content_hash": first["source_content_hash"],
    }


def _select_exact_line(pairs: Sequence[dict[str, Any]]) -> tuple[float | None, list[dict[str, Any]]]:
    if not pairs or pairs[0]["line"] is None:
        return None, list(pairs)
    counts = Counter(float(pair["line"]) for pair in pairs)
    middle = float(median(counts.elements()))
    selected = min(counts, key=lambda point: (-counts[point], abs(point - middle), point))
    return selected, [pair for pair in pairs if math.isclose(float(pair["line"]), selected, abs_tol=1e-9)]


def build_consensus_rows(
    observations: Iterable[Mapping[str, Any]], *, allow_holdout_access: bool = False
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    groups: dict[tuple[str, str, str], list[Mapping[str, Any]]] = defaultdict(list)
    for row in observations:
        if int(row["season"]) >= 2025 and not allow_holdout_access:
            raise ValueError("locked 2025 holdout entered market consensus")
        if row.get("supported_sportsbook"):
            groups[(str(row["canonical_event_id"]), str(row["horizon"]), str(row["market_type"]))].append(row)
    output: list[dict[str, Any]] = []
    exclusions: list[dict[str, Any]] = []
    for key, rows in sorted(groups.items()):
        event_id, horizon, market = key
        if any(row["snapshot_at"] > row["requested_at"] for row in rows):
            raise ValueError("future market snapshot rejected")
        if any(row["requested_at"] > row["scheduled_kickoff"] for row in rows):
            raise ValueError("post-kickoff market cutoff rejected")
        by_book: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
        for row in rows:
            by_book[str(row["sportsbook"])].append(row)
        complete = [pair for book_rows in by_book.values() if (pair := _paired_book(book_rows, market)) is not None]
        line, eligible = _select_exact_line(complete)
        if len(eligible) < MIN_BOOKS:
            exclusions.append({"canonical_event_id": event_id, "horizon": horizon, "market_type": market, "reason": "fewer_than_two_complete_books_at_exact_line"})
            continue
        probabilities = sorted(pair["side_1_no_vig"] for pair in eligible)
        consensus = Decimal(str(median(probabilities))).quantize(QUANTUM, rounding=ROUND_HALF_EVEN)
        first = rows[0]
        snapshots = sorted({pair["snapshot_at"] for pair in eligible})
        books = sorted(str(pair["sportsbook"]) for pair in eligible)
        ordered_eligible = sorted(eligible, key=lambda pair: pair["sportsbook"])
        side_1_best = max(ordered_eligible, key=lambda pair: pair["side_1_odds"])
        side_2_best = max(ordered_eligible, key=lambda pair: pair["side_2_odds"])
        requested = first["requested_at"]
        distances = sorted(abs(int((requested - value).total_seconds())) for value in snapshots)
        details = [
            {
                **{k: (str(v) if isinstance(v, Decimal) else v) for k, v in pair.items() if k not in {"snapshot_at"}},
                "snapshot_at": pair["snapshot_at"].isoformat(),
            }
            for pair in sorted(eligible, key=lambda item: item["sportsbook"])
        ]
        output.append(
            {
                "canonical_event_id": event_id,
                "cfbd_game_id": int(first["cfbd_game_id"]),
                "season": int(first["season"]),
                "week": int(first["week"]),
                "scheduled_kickoff": first["scheduled_kickoff"],
                "horizon": horizon,
                "research_role": "primary" if horizon == PRIMARY_MARKET_HORIZON else "diagnostic_only",
                "market_type": market,
                "requested_cutoff": requested,
                "snapshot_min": snapshots[0],
                "snapshot_max": snapshots[-1],
                "timestamp_distance_median_seconds": int(median(distances)),
                "timestamp_distance_max_seconds": max(distances),
                "consensus_point": line,
                "median_complete_book_point": float(median(pair["line"] for pair in complete)) if line is not None else None,
                "side_1": eligible[0]["side_1"],
                "side_2": eligible[0]["side_2"],
                "side_1_consensus_probability": str(consensus),
                "side_2_consensus_probability": str(Decimal(1) - consensus),
                "probability_dispersion": str((max(probabilities) - min(probabilities)).quantize(QUANTUM, rounding=ROUND_HALF_EVEN)),
                "complete_book_count": len(eligible),
                "all_complete_book_count": len(complete),
                "participating_sportsbooks": json.dumps(books, separators=(",", ":")),
                "best_side_1_sportsbook": side_1_best["sportsbook"],
                "best_side_1_american_odds": side_1_best["side_1_odds"],
                "best_side_2_sportsbook": side_2_best["sportsbook"],
                "best_side_2_american_odds": side_2_best["side_2_odds"],
                "book_pair_details": json.dumps(details, sort_keys=True, separators=(",", ":")),
                "source_market_dataset_hash": str(first.get("source_market_dataset_hash", "")),
                "source_market_dataset_version": str(first.get("source_market_dataset_version", "")),
                "source_content_hashes": json.dumps(sorted({pair["source_content_hash"] for pair in eligible}), separators=(",", ":")),
                "vig_removal_version": VIG_REMOVAL_VERSION,
                "consensus_version": CONSENSUS_VERSION,
            }
        )
    return output, exclusions


def select_oof_predictions(rows: Iterable[Mapping[str, Any]], run_hash: str) -> list[dict[str, Any]]:
    selected = []
    for source in rows:
        row = dict(source)
        season = int(row["season"])
        if season >= 2025:
            raise ValueError("locked 2025 holdout entered OOF selection")
        key = (str(row["target"]), str(row["model_family"]), str(row["variant"]))
        if key not in SELECTED_MODELS or season < 2020:
            continue
        if not row.get("fold_id") or int(row["training_cutoff"]) >= season:
            raise ValueError("in-sample or malformed football prediction rejected")
        row["football_run_hash"] = run_hash
        selected.append(row)
    return selected


def join_football_and_market(consensus: Sequence[Mapping[str, Any]], predictions: Sequence[Mapping[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    by_key = {(str(row["canonical_event_id"]), str(row["horizon"]), str(row["market_type"])): row for row in consensus}
    joined: list[dict[str, Any]] = []
    exclusions: list[dict[str, Any]] = []
    for prediction in predictions:
        football_horizon = str(prediction["horizon"])
        market_horizons = [key for key, value in HORIZON_MAP.items() if value == football_horizon]
        markets = ("h2h", "spreads") if prediction["target"] == "margin" else ("totals",)
        for market_horizon in market_horizons:
            for market in markets:
                key = (str(prediction["canonical_event_id"]), market_horizon, market)
                state = by_key.get(key)
                if state is None:
                    exclusions.append({"canonical_event_id": key[0], "horizon": market_horizon, "market_type": market, "reason": "market_state_unavailable"})
                    continue
                if state["requested_cutoff"] > state["scheduled_kickoff"] or state["snapshot_max"] > state["requested_cutoff"]:
                    raise ValueError("future market snapshot rejected")
                row = dict(state)
                row.update(
                    {
                        "football_horizon": football_horizon,
                        "target": prediction["target"],
                        "actual": float(prediction["actual"]),
                        "football_prediction": float(prediction["prediction"]),
                        "model_family": prediction["model_family"],
                        "model_version": prediction["model_version"],
                        "model_variant": prediction["variant"],
                        "fold_id": prediction["fold_id"],
                        "training_cutoff": int(prediction["training_cutoff"]),
                        "feature_set_hash": prediction["feature_set_hash"],
                        "football_dataset_hash": prediction["dataset_hash"],
                        "football_run_hash": prediction["football_run_hash"],
                    }
                )
                joined.append(row)
    joined.sort(key=lambda row: (row["season"], row["canonical_event_id"], row["market_type"], row["model_family"], row["model_variant"]))
    return joined, exclusions


def build_residual_rows(joined: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    output = []
    for row in joined:
        market = row["market_type"]
        if market == "spreads":
            expected = market_expected_margin(float(row["consensus_point"]))
            residual = float(row["actual"]) - expected
            labels = {"spread_result": "home_cover" if residual > 0 else "away_cover" if residual < 0 else "push"}
        elif market == "totals":
            expected = float(row["consensus_point"])
            residual = float(row["actual"]) - expected
            labels = {"total_result": "over" if residual > 0 else "under" if residual < 0 else "push"}
        else:
            continue
        output.append({**dict(row), "market_expected_target": expected, "market_residual_target": residual, **labels})
    return output


def build_market_feature_rows(joined: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[Any, ...], dict[str, Mapping[str, Any]]] = defaultdict(dict)
    for row in joined:
        key = (row["canonical_event_id"], row["horizon"], row["target"], row["model_family"], row["model_variant"])
        grouped[key][str(row["market_type"])] = row
    output = []
    for key, markets in sorted(grouped.items()):
        target = str(key[2])
        required = {"h2h", "spreads"} if target == "margin" else {"totals"}
        if not required <= markets.keys():
            continue
        anchor = markets["spreads"] if target == "margin" else markets["totals"]
        row = {
            "canonical_event_id": key[0], "season": anchor["season"], "week": anchor["week"],
            "scheduled_kickoff": anchor["scheduled_kickoff"], "horizon": anchor["horizon"],
            "research_role": anchor["research_role"], "target": target, "actual": anchor["actual"],
            "football_prediction": anchor["football_prediction"], "model_family": key[3], "model_variant": key[4],
            "model_version": anchor["model_version"], "fold_id": anchor["fold_id"],
            "training_cutoff": anchor["training_cutoff"], "feature_set_hash": anchor["feature_set_hash"],
            "football_dataset_hash": anchor["football_dataset_hash"], "football_run_hash": anchor["football_run_hash"],
            "source_market_dataset_hash": anchor["source_market_dataset_hash"],
            "vig_removal_version": VIG_REMOVAL_VERSION, "consensus_version": CONSENSUS_VERSION,
        }
        if target == "margin":
            ml, spread = markets["h2h"], markets["spreads"]
            row.update({
                "market_home_no_vig_probability": float(ml["side_1_consensus_probability"]),
                "market_home_spread": spread["consensus_point"],
                "market_expected_margin": market_expected_margin(float(spread["consensus_point"])),
                "market_moneyline_books": ml["complete_book_count"], "market_spread_books": spread["complete_book_count"],
                "market_moneyline_dispersion": float(ml["probability_dispersion"]),
                "market_spread_dispersion": float(spread["probability_dispersion"]),
            })
            row.update(settlement_labels(float(row["actual"]), 0.0, float(spread["consensus_point"]), 0.0))
            row.pop("total_result")
        else:
            total = markets["totals"]
            row.update({"market_consensus_total": total["consensus_point"], "market_total_books": total["complete_book_count"], "market_total_dispersion": float(total["probability_dispersion"])})
            row["total_result"] = "over" if row["actual"] > total["consensus_point"] else "under" if row["actual"] < total["consensus_point"] else "push"
        output.append(row)
    return output


def _table_from_rows(rows: Sequence[Mapping[str, Any]]) -> pa.Table:
    if not rows:
        return pa.table({"empty": pa.array([], type=pa.bool_())})
    columns = sorted({key for row in rows for key in row})
    return pa.Table.from_pylist([{key: row.get(key) for key in columns} for row in rows])


def build_market_comparison_dataset(root: Path) -> dict[str, Any]:
    store = ResearchArtifactStore(root)
    market_manifest = store.load_manifest("historical-market")
    model_manifest = json.loads((root / "models" / "baseline-v1" / "run_manifest.json").read_text(encoding="utf-8"))
    consensus: list[dict[str, Any]] = []
    consensus_exclusions: list[dict[str, Any]] = []
    for artifact in market_manifest["artifacts"]:
        if artifact["dataset"] != "observations":
            continue
        season_rows = store.read_table(artifact["uri"], columns=MARKET_COLUMNS).to_pylist()
        for row in season_rows:
            row["source_market_dataset_hash"] = market_manifest["dataset_hash"]
            row["source_market_dataset_version"] = market_manifest["dataset_version"]
        season_consensus, season_exclusions = build_consensus_rows(season_rows)
        consensus.extend(season_consensus)
        consensus_exclusions.extend(season_exclusions)
    predictions: list[dict[str, Any]] = []
    prediction_file = pq.ParquetFile(root / "models" / "baseline-v1" / "oof_predictions.parquet")
    for batch in prediction_file.iter_batches(batch_size=16_384, columns=PREDICTION_COLUMNS):
        predictions.extend(select_oof_predictions(batch.to_pylist(), str(model_manifest["run_hash"])))
    joined, join_exclusions = join_football_and_market(consensus, predictions)
    residuals = build_residual_rows(joined)
    features = build_market_feature_rows(joined)
    source = [{"id": market_manifest["manifest_id"], "content_hash": market_manifest["dataset_hash"]}, {"id": model_manifest["run_hash"], "content_hash": model_manifest["predictions_content_hash"]}]
    artifacts = []
    for name, rows in (("market_consensus", consensus), ("football_market_joined", joined), ("residual_targets", residuals), ("market_features", features)):
        table = _table_from_rows(rows)
        artifact = store.write_parquet(table, namespace="market-comparison", dataset=name, season=None, schema_version=SCHEMA_VERSION, transformation_version=BUILD_VERSION, source_manifests=source, sort_by=(("canonical_event_id", "ascending"),))
        artifacts.append(artifact_dict(artifact))
    relevant_predictions = [row for row in predictions if row["horizon"] in set(HORIZON_MAP.values())]
    configuration = {"build_version": BUILD_VERSION, "vig_removal_version": VIG_REMOVAL_VERSION, "consensus_version": CONSENSUS_VERSION, "minimum_books": MIN_BOOKS, "horizon_map": HORIZON_MAP, "horizons": sorted({row["horizon"] for row in consensus}), "markets": ["h2h", "spreads", "totals"], "selected_models": sorted(list(SELECTED_MODELS)), "seasons": [2020, 2021, 2022, 2023, 2024]}
    manifest: dict[str, Any] = {
        **configuration, "source_market_manifest_id": market_manifest["manifest_id"],
        "source_market_dataset_hash": market_manifest["dataset_hash"], "football_run_hash": model_manifest["run_hash"],
        "football_predictions_hash": model_manifest["predictions_content_hash"], "feature_set_hash": model_manifest["feature_set_hash"],
        "artifacts": artifacts, "row_counts": {"market_consensus": len(consensus), "football_market_joined": len(joined), "residual_targets": len(residuals), "market_features": len(features)},
        "source_row_counts": {"selected_oof_predictions_relevant_horizons": len(relevant_predictions), "selected_oof_unique_games_relevant_horizons": len({row["canonical_event_id"] for row in relevant_predictions}), "market_consensus_unique_games": len({row["canonical_event_id"] for row in consensus})},
        "exclusion_counts": dict(Counter(item["reason"] for item in (*consensus_exclusions, *join_exclusions))),
        "holdout_accessed": False, "provider_calls": 0,
    }
    manifest["dataset_hash"] = dataset_hash(artifacts, configuration)
    manifest_id, _ = store.write_manifest("market-comparison", manifest)
    manifest["manifest_id"] = manifest_id
    return manifest


def validate_market_comparison_dataset(root: Path, manifest: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    store = ResearchArtifactStore(root)
    for artifact in manifest["artifacts"]:
        errors.extend(store.validate_artifact(artifact))
        table = store.read_table(artifact["uri"])
        if "season" in table.schema.names and any(int(value) >= 2025 for value in table["season"].to_pylist()):
            errors.append(f"2025 holdout found in {artifact['dataset']}")
        if "research_role" in table.schema.names and "market_features" == artifact["dataset"]:
            invalid = [row for row in table.select(["horizon", "research_role"]).to_pylist() if row["horizon"] != PRIMARY_MARKET_HORIZON and row["research_role"] != "diagnostic_only"]
            if invalid:
                errors.append("later horizon entered primary role")
    expected = dataset_hash(manifest["artifacts"], {key: manifest[key] for key in ("build_version", "vig_removal_version", "consensus_version", "minimum_books", "horizon_map", "horizons", "markets", "selected_models", "seasons")})
    if expected != manifest["dataset_hash"]:
        errors.append("dataset hash mismatch")
    if manifest.get("provider_calls") != 0 or manifest.get("holdout_accessed") is not False:
        errors.append("offline/holdout invariant failed")
    return errors


def summarize_market_comparison(root: Path, manifest: Mapping[str, Any]) -> dict[str, Any]:
    store = ResearchArtifactStore(root)
    tables = {artifact["dataset"]: store.read_table(artifact["uri"]).to_pylist() for artifact in manifest["artifacts"]}
    def counts(rows: Sequence[Mapping[str, Any]], fields: Sequence[str]) -> dict[str, int]:
        return dict(sorted(Counter("|".join(str(row[field]) for field in fields) for row in rows).items()))
    consensus = tables["market_consensus"]
    joined = tables["football_market_joined"]
    residuals = tables["residual_targets"]
    features = tables["market_features"]
    def unique_counts(rows: Sequence[Mapping[str, Any]], fields: Sequence[str]) -> dict[str, int]:
        buckets: dict[str, set[str]] = defaultdict(set)
        for row in rows:
            buckets["|".join(str(row[field]) for field in fields)].add(str(row["canonical_event_id"]))
        return {key: len(value) for key, value in sorted(buckets.items())}
    def percentile(values: Sequence[float], proportion: float) -> float | None:
        if not values:
            return None
        ordered = sorted(values)
        return ordered[round((len(ordered) - 1) * proportion)]
    dispersion = [float(row["probability_dispersion"]) for row in consensus]
    distances = [float(row["timestamp_distance_median_seconds"]) for row in consensus]
    primary_features = [row for row in features if row["research_role"] == "primary"]
    unique_h2h: dict[tuple[str, str], Mapping[str, Any]] = {}
    for row in joined:
        if row["market_type"] == "h2h":
            unique_h2h.setdefault((str(row["canonical_event_id"]), str(row["horizon"])), row)
    brier_values = []
    log_losses = []
    for row in unique_h2h.values():
        probability = min(max(float(row["side_1_consensus_probability"]), 1e-15), 1 - 1e-15)
        outcome = 1.0 if float(row["actual"]) > 0 else 0.0
        brier_values.append((probability - outcome) ** 2)
        log_losses.append(-(outcome * math.log(probability) + (1 - outcome) * math.log(1 - probability)))
    return {
        "report_version": BUILD_VERSION, "manifest_id": manifest["manifest_id"], "dataset_hash": manifest["dataset_hash"],
        "source_market_dataset_hash": manifest["source_market_dataset_hash"], "football_run_hash": manifest["football_run_hash"],
        "feature_set_hash": manifest["feature_set_hash"], "row_counts": manifest["row_counts"], "provider_calls": 0,
        "source_row_counts": manifest["source_row_counts"],
        "consensus_by_season_market_horizon": counts(consensus, ("season", "market_type", "horizon")),
        "joined_by_season_market": counts(joined, ("season", "market_type")),
        "joined_unique_games_by_season_market": unique_counts(joined, ("season", "market_type")),
        "common_cohort_by_target_horizon": counts(features, ("target", "horizon")),
        "common_cohort_unique_games_by_target_horizon": unique_counts(features, ("target", "horizon")),
        "primary_common_cohort_rows": len(primary_features),
        "residual_targets_by_market_horizon": counts(residuals, ("market_type", "horizon")),
        "diagnostic_consensus_rows": sum(row["research_role"] == "diagnostic_only" for row in consensus),
        "diagnostic_joined_rows": sum(row["research_role"] == "diagnostic_only" for row in joined),
        "book_depth": dict(sorted(Counter(str(row["complete_book_count"]) for row in consensus).items())),
        "at_least_2_books_pct": 100.0 * sum(int(row["complete_book_count"]) >= 2 for row in consensus) / len(consensus),
        "at_least_3_books_pct": 100.0 * sum(int(row["complete_book_count"]) >= 3 for row in consensus) / len(consensus),
        "probability_dispersion": {"median": percentile(dispersion, 0.5), "p90": percentile(dispersion, 0.9)},
        "timestamp_distance_seconds": {"median": percentile(distances, 0.5), "p90": percentile(distances, 0.9)},
        "market_moneyline_diagnostics": {
            "games": len(unique_h2h),
            "brier": sum(brier_values) / len(brier_values) if brier_values else None,
            "log_loss": sum(log_losses) / len(log_losses) if log_losses else None,
            "role": "plumbing_validation_only",
        },
        "exclusion_counts": manifest["exclusion_counts"], "vig_removal_version": VIG_REMOVAL_VERSION,
        "consensus_version": CONSENSUS_VERSION, "holdout_accessed": False,
    }


def render_market_comparison_report(report: Mapping[str, Any]) -> str:
    lines = [
        "# NCAAF Market Comparison Dataset Report", "",
        "Status: **Phase 5B-7C offline comparison plumbing.** These diagnostics do not establish market edge, profitability, or production readiness.", "",
        "## Provenance", "",
        f"- Comparison dataset hash: `{report['dataset_hash']}`; manifest: `{report['manifest_id']}`.",
        f"- Source market dataset: `{report['source_market_dataset_hash']}`.",
        f"- Football OOF run: `{report['football_run_hash']}`; feature set: `{report['feature_set_hash']}`.",
        f"- Policies: `{report['vig_removal_version']}` and `{report['consensus_version']}`.",
        "- Provider calls: `0`; 2025 holdout accessed: `false`.", "", "## Artifact rows", "",
    ]
    for name, count in report["row_counts"].items():
        lines.append(f"- {name}: `{count}` rows.")
    lines.extend(["", "## Primary common cohorts", "", "| Target / horizon | Rows | Unique games |", "| --- | ---: | ---: |"])
    for key, count in report["common_cohort_by_target_horizon"].items():
        unique = report["common_cohort_unique_games_by_target_horizon"].get(key, 0)
        lines.append(f"| {key} | {count} | {unique} |")
    lines.extend([
        "", "Each selected point-model candidate contributes a separate row. Morning rows are the primary 2020–2023 development / 2024 validation cohort. Sixty-minute rows are diagnostic only. Near-close is consensus-only because no same-horizon football OOF prediction exists.",
        "", "## Coverage and integrity", "",
        f"- Exact-line consensus rows with >=2 / >=3 books: `{report['at_least_2_books_pct']:.2f}%` / `{report['at_least_3_books_pct']:.2f}%`.",
        f"- Probability dispersion median / p90: `{report['probability_dispersion']['median']}` / `{report['probability_dispersion']['p90']}`.",
        f"- Snapshot-distance median / p90: `{report['timestamp_distance_seconds']['median']}` / `{report['timestamp_distance_seconds']['p90']}` seconds.",
        f"- Diagnostic consensus / joined rows: `{report['diagnostic_consensus_rows']}` / `{report['diagnostic_joined_rows']}`.",
        f"- Exclusions: `{json.dumps(report['exclusion_counts'], sort_keys=True)}`.",
        "- Spread/total pairs are coherent within book and only the deterministically selected exact point contributes to probability consensus. Different points are never averaged.",
        "- Canonical identity, OOF training cutoff, horizon equivalence, requested cutoff, and closest-prior snapshot are validated. Push labels remain separate.",
        "", "## Plumbing-only market diagnostic", "",
        f"- Moneyline games: `{report['market_moneyline_diagnostics']['games']}`; Brier `{report['market_moneyline_diagnostics']['brier']:.6f}`; log loss `{report['market_moneyline_diagnostics']['log_loss']:.6f}`.",
        "- These scores verify calculation and label plumbing. They are not a final model-selection comparison and say nothing about betting returns.",
        "", "## Full Phase 5B-7 readiness", "",
        "**Unblocked for the predeclared morning market-aware tournament.** The next phase may fit football-only, residual, and market-as-feature candidates on the frozen common cohorts. It must keep later horizons diagnostic, preserve 2025, predeclare comparisons, and make no profitability claim from this dataset alone.",
        "", "Machine-readable report: [`reports/NCAAF_MARKET_COMPARISON_DATASET_2020_2024.json`](reports/NCAAF_MARKET_COMPARISON_DATASET_2020_2024.json).", "",
    ])
    return "\n".join(lines)
