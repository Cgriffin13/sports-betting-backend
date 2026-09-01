from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any, Mapping

from app.domain.model_registry import (
    REGISTRY_VERSION,
    ArtifactRegistration,
    ModelRegistration,
    ModelStatus,
    canonical_hash,
)
from app.research.ncaaf.finalist_freeze import (
    BASELINE_RUN_HASH,
    FEATURE_DATASET_HASH,
    FEATURE_SET_HASH,
    FREEZE_VERSION,
    HISTORICAL_MARKET_HASH,
    MARKET_AWARE_DATASET_HASH,
    MARKET_AWARE_POINT_HASH,
    MARKET_AWARE_PROBABILITY_HASH,
    MARKET_COMPARISON_HASH,
    POWER_PREDICTIONS_HASH,
    TOTAL_RIDGE_ARTIFACT_HASH,
)

CONSENSUS_VERSION = "unweighted-median-v1"
VIG_VERSION = "proportional-v1"
CALIBRATION_VERSION = "chronological-empirical-market-aware-v1"
HOLDOUT_HASH = "e32e8102de3ac51d1a5690fd6cd3e680fa36d9424060784be645c80d8e526256"
FREEZE_HASH = "5aff62fe0faf9a246c49f2e1ad732b4b6bbb412aa084f9ccd1f635aacb498420"
HOLDOUT_FEATURE_HASH = "ce04f50bea76923ece336e18d384e5f0a8a607bc91c827ebc8501a5956bde4bb"
HOLDOUT_MARKET_HASH = "2aabb8f871906dbb4ea6608967a18c4fac3d4845bde7b7ca1d876fbc47724c48"
CODE_BUILD_VERSION = "phase-5b-10"


def registered_models() -> tuple[ModelRegistration, ...]:
    shared_sources = {
        "historical_market_dataset": HISTORICAL_MARKET_HASH,
        "market_comparison_dataset": MARKET_COMPARISON_HASH,
        "holdout_market_dataset": HOLDOUT_MARKET_HASH,
    }
    shared_runs = {"freeze": FREEZE_HASH, "holdout": HOLDOUT_HASH}
    consensus = tuple(
        ModelRegistration(
            model_id=f"ncaaf-market-consensus-{target}-v1",
            league="NCAAF",
            market_type=target,
            version="1.0.0",
            status=ModelStatus.RETAINED_BENCHMARK,
            model_family="market_consensus",
            feature_set_hash=None,
            source_dataset_hashes=shared_sources,
            research_run_hashes=shared_runs,
            calibration_version=CALIBRATION_VERSION,
            consensus_version=CONSENSUS_VERSION,
            vig_removal_version=VIG_VERSION,
            holdout_result="retained_after_2025",
            promotion_decision="retained_benchmark",
            artifact_locations=(
                {"kind": "freeze_manifest", "uri": "docs/reports/NCAAF_FINALIST_FREEZE_V1.json"},
                {"kind": "holdout_report", "uri": "docs/reports/NCAAF_2025_HOLDOUT_V1.json"},
            ),
            code_build_version=CODE_BUILD_VERSION,
        )
        for target in ("margin", "moneyline", "spread", "total")
    )
    diagnostic_power = ModelRegistration(
        model_id="ncaaf-football-power-margin-v1",
        league="NCAAF",
        market_type="margin",
        version="1.0.0",
        status=ModelStatus.DIAGNOSTIC,
        model_family="chronological_power_rating",
        feature_set_hash=FEATURE_SET_HASH,
        source_dataset_hashes={"feature_dataset": FEATURE_DATASET_HASH},
        research_run_hashes={"baseline_run": BASELINE_RUN_HASH, "predictions": POWER_PREDICTIONS_HASH},
        calibration_version="quality-aware-normal-margin-v1",
        consensus_version=None,
        vig_removal_version=None,
        holdout_result="diagnostic_only",
        promotion_decision="diagnostic_not_fair_value",
        artifact_locations=({"kind": "prediction_hash", "uri": f"sha256:{POWER_PREDICTIONS_HASH}"},),
        code_build_version=CODE_BUILD_VERSION,
    )
    ridge_total = ModelRegistration(
        model_id="ncaaf-ridge-total-no-opponent-adjustment-v1",
        league="NCAAF",
        market_type="total",
        version="1.0.0",
        status=ModelStatus.DIAGNOSTIC,
        model_family="ridge",
        feature_set_hash=FEATURE_SET_HASH,
        source_dataset_hashes={"feature_dataset": FEATURE_DATASET_HASH},
        research_run_hashes={"baseline_run": BASELINE_RUN_HASH},
        calibration_version=CALIBRATION_VERSION,
        consensus_version=None,
        vig_removal_version=None,
        holdout_result="component_of_rejected_blend",
        promotion_decision="diagnostic_not_fair_value",
        artifact_locations=({"kind": "model_artifact", "uri": f"sha256:{TOTAL_RIDGE_ARTIFACT_HASH}"},),
        code_build_version=CODE_BUILD_VERSION,
    )
    rejected_blend = ModelRegistration(
        model_id="ncaaf-market-ridge-total-blend-v1",
        league="NCAAF",
        market_type="total",
        version="1.0.0",
        status=ModelStatus.REJECTED,
        model_family="constrained_market_ridge_blend",
        feature_set_hash=FEATURE_SET_HASH,
        source_dataset_hashes={**shared_sources, "feature_dataset": FEATURE_DATASET_HASH},
        research_run_hashes={**shared_runs, "market_aware_dataset": MARKET_AWARE_DATASET_HASH},
        calibration_version=CALIBRATION_VERSION,
        consensus_version=CONSENSUS_VERSION,
        vig_removal_version=VIG_VERSION,
        holdout_result="FAIL",
        promotion_decision="rejected_after_locked_2025_holdout",
        artifact_locations=(
            {"kind": "point_predictions", "uri": f"sha256:{MARKET_AWARE_POINT_HASH}"},
            {"kind": "probabilities", "uri": f"sha256:{MARKET_AWARE_PROBABILITY_HASH}"},
        ),
        code_build_version=CODE_BUILD_VERSION,
    )
    return (*consensus, diagnostic_power, ridge_total, rejected_blend)


def registered_artifacts() -> tuple[ArtifactRegistration, ...]:
    return (
        ArtifactRegistration(
            artifact_id="ncaaf-phase5b8-finalist-freeze",
            artifact_type="governance_manifest",
            version=FREEZE_VERSION,
            status="evidence",
            content_hash=FREEZE_HASH,
            source_hashes={"market_aware_dataset": MARKET_AWARE_DATASET_HASH},
            locations=({"kind": "repository", "uri": "docs/reports/NCAAF_FINALIST_FREEZE_V1.json"},),
            code_build_version=CODE_BUILD_VERSION,
            metadata={"holdout_accessed": False},
        ),
        ArtifactRegistration(
            artifact_id="ncaaf-phase5b9-locked-holdout",
            artifact_type="holdout_report",
            version="ncaaf-2025-locked-holdout-v1",
            status="evidence",
            content_hash=HOLDOUT_HASH,
            source_hashes={"feature_dataset": HOLDOUT_FEATURE_HASH, "market_dataset": HOLDOUT_MARKET_HASH},
            locations=({"kind": "repository", "uri": "docs/reports/NCAAF_2025_HOLDOUT_V1.json"},),
            code_build_version=CODE_BUILD_VERSION,
            metadata={"status": "FAIL", "fallback": "market_consensus"},
        ),
        ArtifactRegistration(
            artifact_id="ncaaf-total-ridge-2024-fold",
            artifact_type="model_artifact",
            version="d41797ed-v1",
            status="diagnostic",
            content_hash=TOTAL_RIDGE_ARTIFACT_HASH,
            source_hashes={"feature_dataset": FEATURE_DATASET_HASH, "feature_set": FEATURE_SET_HASH},
            locations=({"kind": "local_ignored", "uri": ".ncaaf-data/models/baseline-v1/fold_models.json"},),
            code_build_version=CODE_BUILD_VERSION,
            metadata={"family": "ridge", "target": "total", "alpha": 100.0},
        ),
        ArtifactRegistration(
            artifact_id="ncaaf-market-aware-probabilities-v1",
            artifact_type="probability_artifact",
            version=CALIBRATION_VERSION,
            status="rejected",
            content_hash=MARKET_AWARE_PROBABILITY_HASH,
            source_hashes={"market_aware_dataset": MARKET_AWARE_DATASET_HASH},
            locations=({"kind": "local_ignored", "uri": ".ncaaf-data/market-aware-v1/"},),
            code_build_version=CODE_BUILD_VERSION,
            metadata={"push_version": "integer-lattice-settlement-v1", "promotion": "rejected"},
        ),
    )


def build_registry_manifest() -> dict[str, Any]:
    body = {
        "registry_version": REGISTRY_VERSION,
        "league": "NCAAF",
        "phase": "5B-10",
        "phase_5_status": "complete",
        "provider_calls": 0,
        "retained_fair_value_source": "market_consensus",
        "models": [_serialize(asdict(item)) | {"registry_entry_hash": item.entry_hash} for item in registered_models()],
        "artifacts": [
            _serialize(asdict(item)) | {"registry_entry_hash": item.entry_hash} for item in registered_artifacts()
        ],
        "versions": {
            "consensus": CONSENSUS_VERSION,
            "vig_removal": VIG_VERSION,
            "calibration": CALIBRATION_VERSION,
            "horizon": "morning_first_kickoff_minus_3h",
            "shadow_schema": "ncaaf-shadow-prediction-v1",
        },
    }
    return {**body, "registry_hash": canonical_hash(body)}


def validate_registry_manifest(manifest: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    body = {key: value for key, value in manifest.items() if key != "registry_hash"}
    if manifest.get("registry_hash") != canonical_hash(body):
        errors.append("registry hash mismatch")
    if manifest.get("provider_calls") != 0:
        errors.append("registry build must not call providers")
    models = list(manifest.get("models", []))
    retained = [item for item in models if item.get("status") == "retained_benchmark"]
    if {item.get("market_type") for item in retained} != {"margin", "moneyline", "spread", "total"}:
        errors.append("retained market-consensus target set mismatch")
    if any(item.get("model_family") != "market_consensus" for item in retained):
        errors.append("only market consensus may be retained")
    rejected = {item.get("model_id") for item in models if item.get("status") == "rejected"}
    if "ncaaf-market-ridge-total-blend-v1" not in rejected:
        errors.append("failed total blend must remain rejected")
    for item in models:
        entry = {key: value for key, value in item.items() if key != "registry_entry_hash"}
        if item.get("registry_entry_hash") != canonical_hash(entry):
            errors.append(f"model entry hash mismatch: {item.get('model_id')}")
    for item in manifest.get("artifacts", []):
        entry = {key: value for key, value in item.items() if key != "registry_entry_hash"}
        if item.get("registry_entry_hash") != canonical_hash(entry):
            errors.append(f"artifact entry hash mismatch: {item.get('artifact_id')}")
    return errors


def verify_authoritative_reports(repo_root: Path) -> list[str]:
    errors: list[str] = []
    freeze = _read(repo_root / "docs/reports/NCAAF_FINALIST_FREEZE_V1.json")
    holdout = _read(repo_root / "docs/reports/NCAAF_2025_HOLDOUT_V1.json")
    if freeze.get("freeze_hash") != FREEZE_HASH:
        errors.append("authoritative freeze hash mismatch")
    if holdout.get("holdout_run_hash") != HOLDOUT_HASH:
        errors.append("authoritative holdout hash mismatch")
    if holdout.get("decision") != "fallback_to_market_consensus" or holdout.get("status") != "FAIL":
        errors.append("authoritative holdout decision mismatch")
    return errors


def write_registry_manifest(path: Path) -> dict[str, Any]:
    manifest = build_registry_manifest()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return manifest


def registrations_from_manifest(manifest: Mapping[str, Any]) -> tuple[tuple[ModelRegistration, ...], tuple[ArtifactRegistration, ...]]:
    models = tuple(
        ModelRegistration(
            **{**{key: value for key, value in item.items() if key != "registry_entry_hash"}, "status": ModelStatus(item["status"]), "artifact_locations": tuple(item["artifact_locations"])}
        )
        for item in manifest["models"]
    )
    artifacts = tuple(
        ArtifactRegistration(
            **{**{key: value for key, value in item.items() if key != "registry_entry_hash"}, "locations": tuple(item["locations"])}
        )
        for item in manifest["artifacts"]
    )
    return models, artifacts


def _serialize(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _serialize(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_serialize(item) for item in value]
    if isinstance(value, ModelStatus):
        return value.value
    return value


def _read(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))
