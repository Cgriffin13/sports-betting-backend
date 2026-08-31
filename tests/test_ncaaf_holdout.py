from __future__ import annotations

import copy
from datetime import UTC, datetime

import pytest

from app.research.ncaaf.finalist_freeze import build_freeze_manifest
from app.research.ncaaf.holdout import create_unlock_record, load_unlock_record


def verified(_root, _manifest) -> list[str]:
    return []


def test_holdout_is_rejected_without_unlock(tmp_path) -> None:
    with pytest.raises(ValueError, match="sealed"):
        load_unlock_record(tmp_path)


def test_unlock_verifies_freeze_first_and_is_immutable(tmp_path) -> None:
    record = create_unlock_record(
        tmp_path,
        build_freeze_manifest(),
        code_commit="abc123",
        command_id="test-run",
        unlocked_at=datetime(2026, 9, 1, tzinfo=UTC),
        artifact_validator=verified,
    )
    assert record["freeze_verified_before_unlock"] is True
    assert record["holdout_season"] == 2025
    assert load_unlock_record(tmp_path) == record
    with pytest.raises(ValueError, match="second unlock"):
        create_unlock_record(
            tmp_path,
            build_freeze_manifest(),
            code_commit="abc123",
            command_id="test-run-2",
            artifact_validator=verified,
        )


def test_unlock_rejects_freeze_tampering_before_writing(tmp_path) -> None:
    freeze = copy.deepcopy(build_freeze_manifest())
    freeze["candidates"]["total"]["football_weight"] = 0.5
    with pytest.raises(ValueError, match="unexpected|verification"):
        create_unlock_record(
            tmp_path,
            freeze,
            code_commit="abc123",
            command_id="test-run",
            artifact_validator=verified,
        )
    assert not (tmp_path / "holdout-2025").exists()
