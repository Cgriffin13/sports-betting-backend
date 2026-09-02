from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

PRIMARY_HORIZON_VERSION = "morning-first-kickoff-minus-3h-v1"
OFFICIAL_WINDOW_SECONDS = 15 * 60


def classify_recommendation_timing(as_of: datetime, first_kickoff: datetime) -> dict[str, Any]:
    cutoff = _utc(first_kickoff) - timedelta(hours=3)
    delta_seconds = int((_utc(as_of) - cutoff).total_seconds())
    if delta_seconds < 0:
        classification = "EARLY_LOOKAHEAD"
    elif delta_seconds <= OFFICIAL_WINDOW_SECONDS:
        classification = "OFFICIAL_PRIMARY_HORIZON"
    else:
        classification = "POST_HORIZON"
    return {
        "timing_classification": classification,
        "primary_horizon_at": cutoff,
        "horizon_delta_seconds": delta_seconds,
        "horizon_version": PRIMARY_HORIZON_VERSION,
    }


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
