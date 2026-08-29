from __future__ import annotations

import argparse
import json
from collections.abc import Iterable
from dataclasses import asdict
from typing import Any

from app.cli.ncaaf_common import research_runtime, service_for
from app.domain.ncaaf import DEVELOPMENT_LAST_SEASON, validate_development_seasons


def build_plan(start_season: int, end_season: int) -> list[tuple[str, dict[str, Any]]]:
    plan: list[tuple[str, dict[str, Any]]] = [("venues", {})]
    for season in range(start_season, end_season + 1):
        plan.extend(
            (
                ("calendar", {"year": season}),
                ("teams", {"year": season}),
                ("games", {"year": season}),
                ("drives", {"year": season, "classification": "fbs"}),
            )
        )
        plan.extend(
            ("plays", {"year": season, "week": week, "seasonType": "regular", "classification": "fbs"})
            for week in range(1, 16)
        )
        plan.append(("plays", {"year": season, "week": 1, "seasonType": "postseason", "classification": "fbs"}))
        plan.extend(
            (
                "games/teams",
                {"year": season, "week": week, "seasonType": "regular", "classification": "fbs"},
            )
            for week in range(1, 16)
        )
        plan.append(
            ("games/teams", {"year": season, "week": 1, "seasonType": "postseason", "classification": "fbs"})
        )
    return plan


def main() -> None:
    parser = argparse.ArgumentParser(description="Plan or ingest the immutable 2014-2024 CFBD development corpus")
    parser.add_argument("--start-season", type=int, default=2014)
    parser.add_argument("--end-season", type=int, default=DEVELOPMENT_LAST_SEASON)
    parser.add_argument("--execute", action="store_true", help="explicitly permit provider calls")
    parser.add_argument("--refresh", action="store_true", help="re-check cached requests for provider corrections")
    parser.add_argument("--allow-holdout-access", action="store_true", help="explicitly unlock sealed 2025+ data")
    args = parser.parse_args()
    validate_development_seasons(
        args.start_season,
        args.end_season,
        allow_holdout=args.allow_holdout_access,
    )
    plan = build_plan(args.start_season, args.end_season)
    if not args.execute:
        print(
            json.dumps(
                {
                    "mode": "plan",
                    "start_season": args.start_season,
                    "end_season": args.end_season,
                    "maximum_provider_calls": len(plan),
                    "execute_required": True,
                },
                indent=2,
            )
        )
        return
    factory, client, store = research_runtime()
    results: list[dict[str, Any]] = []
    with factory() as session:
        service = service_for(session, client, store)
        for endpoint, parameters in _ordered(plan):
            result = service.ingest(endpoint, parameters, refresh=args.refresh)
            session.commit()
            results.append({"endpoint": endpoint, "parameters": parameters, **asdict(result)})
    print(
        json.dumps(
            {
                "mode": "executed",
                "requests": len(results),
                "provider_calls": sum(item["provider_calls"] for item in results),
                "cache_hits": sum(bool(item["cache_hit"]) for item in results),
                "rows": sum(int(item["row_count"]) for item in results),
                "response_bytes": sum(int(item["response_bytes"]) for item in results),
                "stored_bytes": sum(int(item["stored_bytes"]) for item in results),
            },
            indent=2,
        )
    )


def _ordered(plan: Iterable[tuple[str, dict[str, Any]]]) -> Iterable[tuple[str, dict[str, Any]]]:
    # Identity-bearing products precede games; games precede bulky context products.
    priority = {"venues": 0, "teams": 1, "calendar": 2, "games": 3, "drives": 4, "plays": 5, "games/teams": 6}
    return sorted(plan, key=lambda item: (int(item[1].get("year", 0)), priority.get(item[0], 5), item[0], str(item[1])))


if __name__ == "__main__":
    main()
