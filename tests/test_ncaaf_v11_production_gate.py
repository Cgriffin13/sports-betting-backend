from __future__ import annotations

import json
from pathlib import Path
from typing import Any


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
REPORTS = REPOSITORY_ROOT / "docs" / "reports"


def _load(name: str) -> dict[str, Any]:
    return json.loads((REPORTS / name).read_text(encoding="utf-8"))


def test_v11_gate_matches_immutable_holdout_and_registry_evidence() -> None:
    gate = _load("NCAAF_V11_PRODUCTION_SCORING_GATE.json")
    holdout = _load("NCAAF_2025_HOLDOUT_V1.json")
    registry = _load("NCAAF_MODEL_REGISTRY_V1.json")

    locked = gate["existing_evidence"]["locked_2025_holdout"]
    assert gate["status"] == "BLOCKED"
    assert gate["recommendation"] == "DO_NOT_MERGE"
    assert locked["first_access"] is holdout["first_access"]["first_access"] is True
    assert locked["status"] == holdout["status"] == "FAIL"
    assert locked["freeze_hash"] == holdout["freeze_hash"]
    assert locked["holdout_run_hash"] == holdout["holdout_run_hash"]
    assert locked["unlocked_at"] == holdout["first_access"]["unlocked_at"]
    assert gate["existing_evidence"]["registry"]["registry_hash"] == registry["registry_hash"]


def test_v11_gate_preserves_registry_statuses_and_performs_no_live_work() -> None:
    gate = _load("NCAAF_V11_PRODUCTION_SCORING_GATE.json")
    registry = _load("NCAAF_MODEL_REGISTRY_V1.json")
    statuses = [model["status"] for model in registry["models"]]

    assert statuses.count("retained_benchmark") == 4
    assert statuses.count("diagnostic") == 2
    assert statuses.count("rejected") == 1
    assert gate["actions"] == {
        "live_board_generated": False,
        "live_feature_acquisition": False,
        "model_training_or_tuning": False,
        "production_registry_changed": False,
        "provider_calls": 0,
        "provider_credits": 0,
    }
    assert set(gate["blocked_outputs"].values()) == {"NOT_RUN"}
    assert gate["gate_results"]["locked_2025_holdout_available_for_new_model_selection"] == "FAIL"
    assert gate["gate_results"]["untouched_completed_evaluation_season_available"] == "FAIL"
