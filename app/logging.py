from __future__ import annotations

import json
import logging
from contextvars import ContextVar
from datetime import UTC, datetime

request_id_context: ContextVar[str] = ContextVar("request_id", default="-")


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "time_utc": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": request_id_context.get(),
        }
        for field in (
            "method",
            "path",
            "status_code",
            "provider",
            "sport",
            "storage",
            "observations_fetched",
            "snapshots_represented",
            "events_represented",
            "books_represented",
            "query_elapsed_ms",
            "calculation_elapsed_ms",
            "opportunities_returned",
        ):
            if hasattr(record, field):
                payload[field] = getattr(record, field)
        return json.dumps(payload, separators=(",", ":"))


def configure_logging() -> None:
    root = logging.getLogger()
    if any(getattr(handler, "_sports_backend_handler", False) for handler in root.handlers):
        return
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    handler._sports_backend_handler = True  # type: ignore[attr-defined]
    root.addHandler(handler)
    root.setLevel(logging.INFO)
