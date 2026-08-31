from __future__ import annotations

import argparse
import json
from collections.abc import Iterable
from dataclasses import asdict
from typing import Any

from app.cli.ncaaf_common import research_runtime, service_for
from app.domain.ncaaf import DEVELOPMENT_LAST_SEASON, validate_development_seasons


SEASON_ENDPOINTS: tuple[tuple[str, dict[str, Any]], ...] = (
    ("player/returning", {}),
    ("player/portal", {}),
    ("recruiting/teams", {}),
    ("talent", {}),
    ("roster", {"classification": "fbs"}),
    ("stats/player/season", {"category": "passing"}),
)


def build_plan(start_season: int, end_season: int) -> list[tuple[str, dict[str, Any]]]:
    plan: list[tuple[str, dict[str, Any]]] = [("info", {})]
    for season in range(start_season, end_season + 1):
        for endpoint, fixed in SEASON_ENDPOINTS:
            plan.append((endpoint, {"year": season, **fixed}))
    plan.extend((("coaches", {"minYear": start_season, "maxYear": end_season}), ("info", {})))
    return plan


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Plan or ingest bounded, immutable NCAAF preseason/personnel source products"
    )
    parser.add_argument("--start-season", type=int, default=2014)
    parser.add_argument("--end-season", type=int, default=DEVELOPMENT_LAST_SEASON)
    parser.add_argument("--execute", action="store_true", help="explicitly permit provider calls")
    parser.add_argument("--refresh", action="store_true", help="re-check cached requests for corrections")
    parser.add_argument(
        "--info-only",
        action="store_true",
        help="retrieve only CFBD usage metadata; useful for a bounded post-audit accounting check",
    )
    parser.add_argument("--allow-holdout-access", action="store_true")
    args = parser.parse_args()
    validate_development_seasons(
        args.start_season,
        args.end_season,
        allow_holdout=args.allow_holdout_access,
    )
    plan = [("info", {})] if args.info_only else build_plan(args.start_season, args.end_season)
    if not args.execute:
        print(
            json.dumps(
                {
                    "mode": "plan",
                    "start_season": args.start_season,
                    "end_season": args.end_season,
                    "maximum_provider_calls": len(plan),
                    "requests_by_endpoint": _counts(plan),
                    "execute_required": True,
                    "holdout_access": args.allow_holdout_access,
                },
                indent=2,
                sort_keys=True,
            )
        )
        return

    factory, client, store = research_runtime()
    results: list[dict[str, Any]] = []
    with factory() as session:
        service = service_for(session, client, store)
        for endpoint, parameters in plan:
            result = service.ingest(endpoint, parameters, refresh=args.refresh)
            session.commit()
            results.append({"endpoint": endpoint, "parameters": parameters, **asdict(result)})
    print(
        json.dumps(
            {
                "mode": "executed",
                "requests": len(results),
                "provider_calls": sum(int(item["provider_calls"]) for item in results),
                "cache_hits": sum(bool(item["cache_hit"]) for item in results),
                "rows": sum(int(item["row_count"]) for item in results),
                "response_bytes": sum(int(item["response_bytes"]) for item in results),
                "stored_bytes": sum(int(item["stored_bytes"]) for item in results),
                "by_endpoint": _result_summary(results),
            },
            indent=2,
            sort_keys=True,
        )
    )


def _counts(plan: Iterable[tuple[str, dict[str, Any]]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for endpoint, _ in plan:
        counts[endpoint] = counts.get(endpoint, 0) + 1
    return dict(sorted(counts.items()))


def _result_summary(results: Iterable[dict[str, Any]]) -> dict[str, dict[str, int]]:
    summary: dict[str, dict[str, int]] = {}
    for item in results:
        endpoint = str(item["endpoint"])
        current = summary.setdefault(endpoint, {"requests": 0, "provider_calls": 0, "rows": 0, "bytes": 0})
        current["requests"] += 1
        current["provider_calls"] += int(item["provider_calls"])
        current["rows"] += int(item["row_count"])
        current["bytes"] += int(item["response_bytes"])
    return dict(sorted(summary.items()))


if __name__ == "__main__":
    main()
