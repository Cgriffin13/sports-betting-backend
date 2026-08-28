import json
import logging

from app.logging import JsonFormatter, request_id_context


def test_structured_formatter_includes_request_and_safe_context() -> None:
    record = logging.LogRecord("app.test", logging.INFO, __file__, 1, "request_completed", (), None)
    setattr(record, "method", "GET")
    setattr(record, "path", "/health")
    setattr(record, "status_code", 200)
    token = request_id_context.set("request-123")
    try:
        payload = json.loads(JsonFormatter().format(record))
    finally:
        request_id_context.reset(token)
    assert payload == {
        "time_utc": payload["time_utc"],
        "level": "INFO",
        "logger": "app.test",
        "message": "request_completed",
        "request_id": "request-123",
        "method": "GET",
        "path": "/health",
        "status_code": 200,
    }
