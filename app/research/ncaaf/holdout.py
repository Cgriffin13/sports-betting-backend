from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable, Mapping

from app.research.ncaaf.artifacts import ResearchArtifactStore, dataset_hash
from app.research.ncaaf.contracts import stable_hash
from app.research.ncaaf.finalist_freeze import validate_freeze_manifest, validate_local_artifacts

HOLDOUT_SEASON = 2025
UNLOCK_VERSION = "ncaaf-2025-one-time-holdout-unlock-v1"
EXPECTED_FREEZE_HASH = "5aff62fe0faf9a246c49f2e1ad732b4b6bbb412aa084f9ccd1f635aacb498420"
HOLDOUT_MARKET_PLAN_HASH = "6e5dfe394c2da1e1b11deacbaa850336d54ee1f1c552c04aa329bf740ff07c6a"
HOLDOUT_MARKET_CALLS = 79
HOLDOUT_MARKET_CREDIT_LIMIT = 2_370


def unlock_body(
    freeze_manifest: Mapping[str, Any],
    *,
    code_commit: str,
    command_id: str,
    unlocked_at: datetime,
) -> dict[str, Any]:
    if unlocked_at.tzinfo is None:
        raise ValueError("unlock timestamp must be timezone-aware")
    if freeze_manifest.get("freeze_hash") != EXPECTED_FREEZE_HASH:
        raise ValueError("unexpected Phase 5B-8 freeze hash")
    errors = validate_freeze_manifest(freeze_manifest)
    if errors:
        raise ValueError(f"freeze verification failed: {errors}")
    if not code_commit or not command_id:
        raise ValueError("code commit and command id are required")
    return {
        "unlock_version": UNLOCK_VERSION,
        "holdout_season": HOLDOUT_SEASON,
        "unlocked_at": unlocked_at.astimezone(UTC).isoformat(),
        "code_commit": code_commit,
        "command_id": command_id,
        "freeze_hash": freeze_manifest["freeze_hash"],
        "frozen_artifact_hashes": dict(freeze_manifest["frozen_hashes"]),
        "freeze_verified_before_unlock": True,
        "first_access": True,
        "purpose": "Phase 5B-9 locked evaluation only",
    }


def create_unlock_record(
    root: Path,
    freeze_manifest: Mapping[str, Any],
    *,
    code_commit: str,
    command_id: str,
    unlocked_at: datetime | None = None,
    artifact_validator: Callable[[Path, Mapping[str, Any]], list[str]] = validate_local_artifacts,
) -> dict[str, Any]:
    namespace = root / "holdout-2025"
    pointer = namespace / "current.json"
    if pointer.exists():
        raise ValueError("2025 holdout was already unlocked; a second unlock is prohibited")
    errors = artifact_validator(root, freeze_manifest)
    if errors:
        raise ValueError(f"artifact verification failed before holdout unlock: {errors}")
    body = unlock_body(
        freeze_manifest,
        code_commit=code_commit,
        command_id=command_id,
        unlocked_at=unlocked_at or datetime.now(UTC),
    )
    record = {**body, "unlock_id": stable_hash(body)}
    destination = namespace / "unlocks" / f"{record['unlock_id']}.json"
    _atomic_write(destination, json.dumps(record, indent=2, sort_keys=True) + "\n")
    _atomic_write(
        pointer,
        json.dumps(
            {
                "unlock_id": record["unlock_id"],
                "uri": destination.relative_to(root).as_posix(),
            },
            sort_keys=True,
        )
        + "\n",
    )
    return record


def load_unlock_record(root: Path) -> dict[str, Any]:
    pointer_path = root / "holdout-2025" / "current.json"
    if not pointer_path.is_file():
        raise ValueError("2025 holdout is sealed; explicit one-time unlock is required")
    pointer = json.loads(pointer_path.read_text(encoding="utf-8"))
    record_path = (root / str(pointer["uri"])).resolve()
    if not record_path.is_relative_to(root.resolve()) or not record_path.is_file():
        raise ValueError("holdout unlock record is unavailable")
    record = dict(json.loads(record_path.read_text(encoding="utf-8")))
    body = {key: value for key, value in record.items() if key != "unlock_id"}
    if record.get("unlock_id") != stable_hash(body) or pointer.get("unlock_id") != record.get("unlock_id"):
        raise ValueError("holdout unlock record hash mismatch")
    if record.get("holdout_season") != HOLDOUT_SEASON or record.get("freeze_hash") != EXPECTED_FREEZE_HASH:
        raise ValueError("holdout unlock record contract mismatch")
    return record


def assemble_normalized_holdout_manifest(
    root: Path,
    *,
    development_manifest_id: str,
    holdout_manifest_id: str,
) -> dict[str, Any]:
    """Join immutable development and 2025 partitions without rebuilding history."""
    store = ResearchArtifactStore(root)
    development = store.load_manifest("normalized", development_manifest_id)
    holdout = store.load_manifest("normalized", holdout_manifest_id)
    if (development.get("start_season"), development.get("end_season")) != (2014, 2024):
        raise ValueError("development normalized manifest must cover exactly 2014-2024")
    if (holdout.get("start_season"), holdout.get("end_season")) != (2025, 2025):
        raise ValueError("holdout normalized manifest must cover exactly 2025")
    version_keys = (
        "league",
        "schema_version",
        "transformation_version",
        "availability_policy_version",
    )
    if any(development.get(key) != holdout.get(key) for key in version_keys):
        raise ValueError("normalized manifest contracts do not match")
    artifacts = [*development["artifacts"], *holdout["artifacts"]]
    seasons = [int(item["season"]) for item in artifacts if item.get("season") is not None]
    if not seasons or min(seasons) != 2014 or max(seasons) != 2025:
        raise ValueError("combined normalized artifacts do not span 2014-2025")
    configuration = {
        "league": development["league"],
        "start_season": 2014,
        "end_season": 2025,
        "schema_version": development["schema_version"],
        "transformation_version": development["transformation_version"],
        "availability_policy_version": development["availability_policy_version"],
        "source_manifest_fingerprint": stable_hash(
            [development["source_manifest_fingerprint"], holdout["source_manifest_fingerprint"]]
        ),
    }
    manifest: dict[str, Any] = {
        **configuration,
        "artifacts": artifacts,
        "dataset_hash": dataset_hash(artifacts, configuration),
        "source_manifest_count": int(development["source_manifest_count"])
        + int(holdout["source_manifest_count"]),
        "network_calls": 0,
        "assembled_for_holdout": True,
        "input_manifest_ids": [development_manifest_id, holdout_manifest_id],
    }
    manifest_id, _ = store.write_manifest("normalized", manifest)
    manifest["manifest_id"] = manifest_id
    return manifest


def _atomic_write(path: Path, payload: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.parent / f".{os.getpid()}.{path.name}.tmp"
    temporary.write_text(payload, encoding="utf-8", newline="\n")
    os.replace(temporary, path)
