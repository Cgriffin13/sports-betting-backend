from datetime import UTC, date, datetime
from typing import Any


def utc_now() -> datetime:
    return datetime.now(UTC)


def utc_now_iso() -> str:
    return utc_now().isoformat()


def commence_date_utc(commence_time: Any) -> date | None:
    """Return the UTC calendar date for a timezone-aware provider timestamp."""
    if not isinstance(commence_time, str):
        return None
    try:
        parsed = datetime.fromisoformat(commence_time.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(UTC).date()
