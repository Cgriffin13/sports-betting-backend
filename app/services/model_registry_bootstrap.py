from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.domain.model_registry import canonical_hash
from app.persistence.model_registry_repository import SqlAlchemyModelRegistryRepository
from app.research.ncaaf.model_registry import registrations_from_manifest, validate_registry_manifest

DEFAULT_REGISTRY_MANIFEST = Path(__file__).resolve().parents[2] / "docs/reports/NCAAF_MODEL_REGISTRY_V1.json"


def bootstrap_ncaaf_registry(
    repository: SqlAlchemyModelRegistryRepository,
    manifest_path: Path = DEFAULT_REGISTRY_MANIFEST,
) -> str:
    """Idempotently install the committed, validated Phase 5 registry manifest."""
    manifest: dict[str, Any] = json.loads(manifest_path.read_text(encoding="utf-8"))
    errors = validate_registry_manifest(manifest)
    if errors:
        raise RuntimeError("Invalid NCAAF registry manifest: " + "; ".join(errors))
    body = {key: value for key, value in manifest.items() if key != "registry_hash"}
    if manifest["registry_hash"] != canonical_hash(body):
        raise RuntimeError("Invalid NCAAF registry manifest hash")
    models, artifacts = registrations_from_manifest(manifest)
    repository.register_models(models)
    repository.register_artifacts(artifacts)
    return str(manifest["registry_hash"])
