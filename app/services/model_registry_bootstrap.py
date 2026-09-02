from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from app.domain.model_registry import (
    REGISTRY_VERSION,
    ArtifactRegistration,
    ModelRegistration,
    ModelStatus,
    canonical_hash,
)
from app.persistence.model_registry_repository import SqlAlchemyModelRegistryRepository

DEFAULT_REGISTRY_MANIFEST = Path(__file__).resolve().parents[2] / "docs/reports/NCAAF_MODEL_REGISTRY_V1.json"


def bootstrap_ncaaf_registry(
    repository: SqlAlchemyModelRegistryRepository,
    manifest_path: Path = DEFAULT_REGISTRY_MANIFEST,
) -> str:
    """Idempotently install the committed, validated Phase 5 registry manifest."""
    decoded: Any = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(decoded, dict):
        raise RuntimeError("Invalid NCAAF registry manifest schema")
    manifest: dict[str, Any] = decoded
    errors = _validate_registry_manifest(manifest)
    if errors:
        raise RuntimeError("Invalid NCAAF registry manifest: " + "; ".join(errors))
    models, artifacts = _registrations_from_manifest(manifest)
    repository.register_models(models)
    repository.register_artifacts(artifacts)
    return str(manifest["registry_hash"])


def _validate_registry_manifest(manifest: Mapping[str, Any]) -> list[str]:
    """Validate the committed registry without importing the offline research stack."""
    errors: list[str] = []
    body = {key: value for key, value in manifest.items() if key != "registry_hash"}
    if manifest.get("registry_hash") != canonical_hash(body):
        errors.append("registry hash mismatch")
    if manifest.get("registry_version") != REGISTRY_VERSION:
        errors.append("registry version mismatch")
    if manifest.get("league") != "NCAAF" or manifest.get("provider_calls") != 0:
        errors.append("registry scope/provider contract mismatch")

    models_value = manifest.get("models")
    artifacts_value = manifest.get("artifacts")
    if not isinstance(models_value, list) or not all(isinstance(item, Mapping) for item in models_value):
        errors.append("models must be a list of objects")
        models: list[Mapping[str, Any]] = []
    else:
        models = models_value
    if not isinstance(artifacts_value, list) or not all(isinstance(item, Mapping) for item in artifacts_value):
        errors.append("artifacts must be a list of objects")
        artifacts: list[Mapping[str, Any]] = []
    else:
        artifacts = artifacts_value

    model_keys = {(item.get("model_id"), item.get("version")) for item in models}
    artifact_keys = {(item.get("artifact_id"), item.get("version")) for item in artifacts}
    if len(models) != 7 or len(model_keys) != len(models):
        errors.append("registry must contain seven uniquely versioned models")
    if len(artifacts) != 4 or len(artifact_keys) != len(artifacts):
        errors.append("registry must contain four uniquely versioned artifacts")

    statuses = [item.get("status") for item in models]
    if statuses.count(ModelStatus.RETAINED_BENCHMARK.value) != 4:
        errors.append("registry must contain four retained benchmarks")
    if statuses.count(ModelStatus.DIAGNOSTIC.value) != 2:
        errors.append("registry must contain two diagnostic models")
    if statuses.count(ModelStatus.REJECTED.value) != 1:
        errors.append("registry must contain one rejected model")
    retained = [item for item in models if item.get("status") == ModelStatus.RETAINED_BENCHMARK.value]
    if {item.get("market_type") for item in retained} != {"margin", "moneyline", "spread", "total"}:
        errors.append("retained market-consensus target set mismatch")
    if any(item.get("model_family") != "market_consensus" for item in retained):
        errors.append("only market consensus may be retained")
    rejected = {item.get("model_id") for item in models if item.get("status") == ModelStatus.REJECTED.value}
    if rejected != {"ncaaf-market-ridge-total-blend-v1"}:
        errors.append("failed total blend must remain the sole rejected model")

    for item in models:
        entry = {key: value for key, value in item.items() if key != "registry_entry_hash"}
        if item.get("registry_entry_hash") != canonical_hash(entry):
            errors.append(f"model entry hash mismatch: {item.get('model_id')}")
    for item in artifacts:
        entry = {key: value for key, value in item.items() if key != "registry_entry_hash"}
        if item.get("registry_entry_hash") != canonical_hash(entry):
            errors.append(f"artifact entry hash mismatch: {item.get('artifact_id')}")
    return errors


def _registrations_from_manifest(
    manifest: Mapping[str, Any],
) -> tuple[tuple[ModelRegistration, ...], tuple[ArtifactRegistration, ...]]:
    try:
        models = tuple(
            ModelRegistration(
                **{
                    **{key: value for key, value in item.items() if key != "registry_entry_hash"},
                    "status": ModelStatus(item["status"]),
                    "artifact_locations": tuple(item["artifact_locations"]),
                }
            )
            for item in manifest["models"]
        )
        artifacts = tuple(
            ArtifactRegistration(
                **{
                    **{key: value for key, value in item.items() if key != "registry_entry_hash"},
                    "locations": tuple(item["locations"]),
                }
            )
            for item in manifest["artifacts"]
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise RuntimeError("Invalid NCAAF registry manifest schema") from exc
    return models, artifacts
