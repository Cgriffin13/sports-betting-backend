from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from typing import Any

from app.cli.ncaaf_common import research_runtime, service_for

AUDIT_REQUESTS: tuple[tuple[str, dict[str, Any]], ...] = (
    ("info", {}),
    ("calendar", {"year": 2014}),
    ("calendar", {"year": 2024}),
    ("teams/fbs", {"year": 2014}),
    ("teams/fbs", {"year": 2024}),
    ("conferences", {"year": 2014}),
    ("conferences", {"year": 2024}),
    ("venues", {}),
    ("games", {"year": 2014, "classification": "fbs"}),
    ("games", {"year": 2024, "classification": "fbs"}),
    ("plays", {"year": 2014, "week": 1, "seasonType": "regular", "classification": "fbs"}),
    ("drives", {"year": 2014, "week": 1, "seasonType": "regular", "classification": "fbs"}),
    ("games/teams", {"year": 2014, "week": 1, "seasonType": "regular", "classification": "fbs"}),
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the bounded credentialed CFBD source audit")
    parser.add_argument("--execute", action="store_true", help="perform bounded provider calls")
    args = parser.parse_args()
    if not args.execute:
        print(json.dumps({"mode": "plan", "expected_calls": len(AUDIT_REQUESTS) + 3, "requests": AUDIT_REQUESTS}, indent=2))
        return
    factory, client, store = research_runtime()
    results: list[dict[str, Any]] = []
    calls = 0
    with factory() as session:
        service = service_for(session, client, store)
        for endpoint, parameters in AUDIT_REQUESTS:
            result = service.ingest(endpoint, parameters)
            session.commit()
            calls += result.provider_calls
            results.append({"endpoint": endpoint, "parameters": parameters, **asdict(result)})
        # Exact same bounded response is fetched twice to test provider retrieval determinism.
        for _ in range(2):
            result = service.ingest("teams/fbs", {"year": 2024}, refresh=True)
            session.commit()
            calls += result.provider_calls
            results.append({"endpoint": "teams/fbs", "parameters": {"year": 2024}, **asdict(result)})
        result = service.ingest("info", {}, refresh=True)
        session.commit()
        calls += result.provider_calls
        results.append({"endpoint": "info", "parameters": {}, **asdict(result)})
    print(json.dumps({"mode": "executed", "provider_calls": calls, "results": results}, indent=2))


if __name__ == "__main__":
    main()
