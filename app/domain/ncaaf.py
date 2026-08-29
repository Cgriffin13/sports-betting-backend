from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Mapping

CFBD_PROVIDER = "cfbd"
NCAAF_LEAGUE = "NCAAF"
DEVELOPMENT_FIRST_SEASON = 2014
DEVELOPMENT_LAST_SEASON = 2024
LOCKED_HOLDOUT_SEASON = 2025
SOURCE_SCHEMA_VERSION = "cfbd-source-v1"
ARTIFACT_FORMAT = "raw-json-gzip-v1"


def canonical_request_parameters(parameters: Mapping[str, Any]) -> dict[str, Any]:
    """Return a deterministic, credential-free request description."""
    forbidden = {"authorization", "api_key", "apikey", "key", "token"}
    return dict(
        sorted(
            (str(name), value)
            for name, value in parameters.items()
            if name.lower() not in forbidden and value is not None
        )
    )


def canonical_request_hash(provider: str, endpoint: str, parameters: Mapping[str, Any]) -> str:
    body = {
        "endpoint": endpoint.strip("/"),
        "parameters": canonical_request_parameters(parameters),
        "provider": provider.lower(),
    }
    encoded = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    return hashlib.sha256(encoded).hexdigest()


def content_hash(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def validate_development_seasons(
    start_season: int,
    end_season: int,
    *,
    allow_holdout: bool = False,
) -> None:
    if start_season > end_season:
        raise ValueError("start season cannot exceed end season")
    if start_season < DEVELOPMENT_FIRST_SEASON:
        raise ValueError(f"development ingestion begins at {DEVELOPMENT_FIRST_SEASON}")
    if end_season >= LOCKED_HOLDOUT_SEASON and not allow_holdout:
        raise ValueError(
            f"season {LOCKED_HOLDOUT_SEASON} outcomes are sealed; an explicit holdout-access flag is required"
        )


@dataclass(frozen=True, slots=True)
class GameEligibility:
    eligible: bool
    exclusion_reason: str | None
    margin: int | None
    total: int | None


def build_game_eligibility(game: Mapping[str, Any]) -> GameEligibility:
    """Build final-game targets while preserving an explicit reason for every exclusion."""
    if game.get("id") is None:
        return GameEligibility(False, "missing_provider_game_id", None, None)
    if str(game.get("homeClassification") or "").lower() != "fbs" or str(
        game.get("awayClassification") or ""
    ).lower() != "fbs":
        return GameEligibility(False, "not_fbs_vs_fbs", None, None)
    if game.get("homeId") is None or game.get("awayId") is None:
        return GameEligibility(False, "unresolved_program_identity", None, None)
    status = str(game.get("status") or "").lower()
    completed_value = game.get("completed")
    completed = completed_value is True if completed_value is not None else status in {"completed", "final"}
    if not completed:
        reason = "cancelled" if "cancel" in status else "postponed" if "postpon" in status else "not_final"
        return GameEligibility(False, reason, None, None)
    if game.get("homePoints") is None or game.get("awayPoints") is None:
        return GameEligibility(False, "missing_final_score", None, None)
    if game.get("forfeit") or game.get("vacated") or game.get("disputed"):
        return GameEligibility(False, "manual_result_review", None, None)
    home_points = int(game["homePoints"])
    away_points = int(game["awayPoints"])
    return GameEligibility(True, None, home_points - away_points, home_points + away_points)
