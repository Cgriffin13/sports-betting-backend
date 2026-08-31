from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable, Mapping

from app.research.ncaaf.contracts import stable_hash
from app.research.ncaaf.finalist_freeze import validate_freeze_manifest, validate_local_artifacts

HOLDOUT_SEASON = 2025
UNLOCK_VERSION = "ncaaf-2025-one-time-holdout-unlock-v1"
EXPECTED_FREEZE_HASH = "5aff62fe0faf9a246c49f2e1ad732b4b6bbb412aa084f9ccd1f635aacb498420"


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


def _atomic_write(path: Path, payload: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.parent / f".{os.getpid()}.{path.name}.tmp"
    temporary.write_text(payload, encoding="utf-8", newline="\n")
    os.replace(temporary, path)
