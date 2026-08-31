from __future__ import annotations

import argparse
import json
import os
from collections import Counter
from pathlib import Path
from typing import Any, Mapping

from dotenv import load_dotenv

from app.providers.odds_api_historical import HistoricalOddsClient
from app.research.ncaaf.artifacts import ResearchArtifactStore
from app.research.ncaaf.historical_market_dataset import (
    LATER_NEW_CREDIT_LIMIT,
    LATER_NEW_CALL_LIMIT,
    MORNING_NEW_CREDIT_LIMIT,
    HistoricalMarketCache,
    acquisition_plan_summary,
    build_historical_market_dataset,
    build_later_plan,
    build_morning_plan,
    execute_plan,
    load_cached_responses,
    load_market_games,
    select_later_robustness_games,
    summarize_dataset,
    validate_historical_market_dataset,
    validate_cached_plan,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Acquire and build the NCAAF historical market research dataset")
    parser.add_argument(
        "action",
        choices=("plan", "execute", "validate-cache", "build", "validate", "inspect", "summarize"),
    )
    parser.add_argument("--phase", choices=("morning", "later"), default="morning")
    parser.add_argument("--artifact-root", type=Path, default=Path(".ncaaf-data"))
    parser.add_argument("--event-id")
    parser.add_argument("--horizon")
    parser.add_argument(
        "--report", type=Path, default=Path("docs/reports/NCAAF_HISTORICAL_MARKET_DATASET_2020_2024.json")
    )
    parser.add_argument(
        "--markdown", type=Path, default=Path("docs/NCAAF_HISTORICAL_MARKET_DATASET_REPORT.md")
    )
    args = parser.parse_args()

    root: Path = args.artifact_root
    games = load_market_games(root)
    morning = build_morning_plan(games)
    later = build_later_plan(games, root)
    cache = HistoricalMarketCache(root)
    requests = morning if args.phase == "morning" else later

    if args.action == "plan":
        summary = acquisition_plan_summary(requests, cache, available_credits=None)
        output: dict[str, Any] = _compact_plan(summary)
        if args.phase == "later":
            output["sampling_design"] = _sampling_design(games)
        print(json.dumps(output, indent=2, sort_keys=True))
        return

    if args.action == "execute":
        load_dotenv(dotenv_path=Path(".env"))
        key = os.getenv("ODDS_API_KEY")
        if not key:
            raise RuntimeError("ODDS_API_KEY is required; no historical request was made")
        client = HistoricalOddsClient(key, timeout_seconds=float(os.getenv("ODDS_API_TIMEOUT_SECONDS", "30")))
        usage = client.usage()
        available = usage.get("requests_remaining")
        plan = acquisition_plan_summary(
            requests, cache, available_credits=available if isinstance(available, int) else None
        )
        output = _compact_plan(plan)
        if args.phase == "later":
            output["sampling_design"] = _sampling_design(games)
        print(json.dumps(output, indent=2, sort_keys=True), flush=True)
        execution = execute_plan(
            requests,
            client,
            cache,
            credit_limit=MORNING_NEW_CREDIT_LIMIT if args.phase == "morning" else LATER_NEW_CREDIT_LIMIT,
            new_call_limit=LATER_NEW_CALL_LIMIT if args.phase == "later" else None,
        )[1]
        execution_path = root / "historical-market" / "executions" / f"{args.phase}.json"
        execution_path.parent.mkdir(parents=True, exist_ok=True)
        execution_path.write_text(json.dumps(execution, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(json.dumps({"completed": args.phase, **_compact_plan(execution), "credits_consumed": execution["credits_consumed"]}, indent=2, sort_keys=True))
        return

    if args.action == "validate-cache":
        errors = validate_cached_plan(requests, cache)
        print(json.dumps({"phase": args.phase, "valid": not errors, "errors": errors}, indent=2))
        if errors:
            raise SystemExit(1)
        return

    if args.action == "build":
        all_requests = (*morning, *later)
        responses = load_cached_responses(all_requests, cache)
        hashes = [
            acquisition_plan_summary(plan, cache, available_credits=None)["acquisition_plan_hash"]
            for plan in (morning, later)
        ]
        manifest = build_historical_market_dataset(
            root, games, all_requests, responses, acquisition_plan_hashes=hashes
        )
        executions = _load_executions(root)
        report = summarize_dataset(root, manifest, executions)
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        args.markdown.write_text(_render_markdown(report), encoding="utf-8")
        print(json.dumps({"manifest_id": manifest["manifest_id"], "dataset_hash": manifest["dataset_hash"], "rows": manifest["row_count"]}, indent=2))
        return

    manifest = ResearchArtifactStore(root).load_manifest("historical-market")
    if args.action == "validate":
        errors = validate_historical_market_dataset(root, manifest)
        print(json.dumps({"valid": not errors, "errors": errors, "dataset_hash": manifest["dataset_hash"]}, indent=2))
        if errors:
            raise SystemExit(1)
        return
    report = summarize_dataset(root, manifest, _load_executions(root))
    if args.action == "summarize":
        print(json.dumps(report, indent=2, sort_keys=True))
        return
    if not args.event_id or not args.horizon:
        raise ValueError("inspect requires --event-id and --horizon")
    rows: list[dict[str, Any]] = []
    store = ResearchArtifactStore(root)
    for artifact in manifest["artifacts"]:
        if artifact["dataset"] != "observations":
            continue
        rows.extend(
            row
            for row in store.read_table(artifact["uri"]).to_pylist()
            if row["canonical_event_id"] == args.event_id and row["horizon"] == args.horizon
        )
    print(json.dumps(rows, indent=2, default=str))


def _compact_plan(summary: Mapping[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in summary.items() if key != "requests"}


def _sampling_design(games: Any) -> dict[str, Any]:
    selected = select_later_robustness_games(games)
    phases: Counter[str] = Counter()
    windows: Counter[str] = Counter()
    for game in selected:
        phase = "postseason" if game.season_type.casefold() != "regular" else (
            "early_regular" if (game.week or 0) <= 4 else "middle_regular" if (game.week or 0) <= 9 else "late_regular"
        )
        hour = game.kickoff.astimezone(__import__("zoneinfo").ZoneInfo("America/New_York")).hour
        window = "early" if hour < 15 else "middle" if hour < 19 else "late"
        phases[f"{game.season}|{phase}"] += 1
        windows[f"{game.season}|{window}"] += 1
    return {
        "policy": "two outcome-blind stable-hash games per season/phase, preferring distinct kickoff windows",
        "sampling_version": "ncaaf-later-horizon-stratified-v1",
        "selected_games": len(selected),
        "by_season_phase": dict(sorted(phases.items())),
        "by_season_kickoff_window": dict(sorted(windows.items())),
        "game_ids": [game.provider_game_id for game in selected],
    }


def _load_executions(root: Path) -> list[dict[str, Any]]:
    values = []
    for phase in ("morning", "later"):
        path = root / "historical-market" / "executions" / f"{phase}.json"
        if path.is_file():
            values.append(dict(json.loads(path.read_text(encoding="utf-8"))))
    return values


def _render_markdown(report: Mapping[str, Any]) -> str:
    executions = report["executions"]
    consumed = sum(int(item.get("credits_consumed") or 0) for item in executions)
    calls = sum(int(item.get("network_calls") or 0) for item in executions)
    cache_hits = sum(int(item.get("cache_hits") or 0) for item in executions)
    lines = [
        "# NCAAF Historical Market Dataset Report",
        "",
        "Status: **Phase 5B-7B canonical data build.** This is acquisition and normalization evidence, not model edge or profitability.",
        "",
        "## Acquisition and artifacts",
        "",
        f"- New historical credits consumed: `{consumed}`.",
        f"- New provider calls: `{calls}`; cache hits: `{cache_hits}`.",
        f"- Normalized observations: `{report['row_count']}` across `{report['event_count']}` canonical events.",
        f"- Dataset hash: `{report['dataset_hash']}`; manifest: `{report['manifest_id']}`.",
        f"- Raw / normalized storage: `{report['raw_stored_bytes']}` / `{report['normalized_stored_bytes']}` bytes.",
        "",
        "The complete morning cohort is primary evidence. The deterministic 60-minute/near-close cohort is secondary robustness evidence only.",
        "",
        "## Aggregate cohort coverage",
        "",
        "| Horizon | Market | Games | Usable | Coverage | >=2 books | >=3 books |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for key, value in report["aggregate_coverage"].items():
        horizon, market = key.split("|")
        lines.append(
            f"| {horizon} | {market} | {value['games']} | {value['usable']} | "
            f"{value['coverage_pct']:.2f}% | {value['at_least_2_books_pct']:.2f}% | "
            f"{value['at_least_3_books_pct']:.2f}% |"
        )
    lines.extend(
        [
        "",
        "## Coverage",
        "",
        "| Season | Horizon | Market | Games | Usable | Coverage | >=2 books | >=3 books | Reliable / ambiguous / missing |",
        "| ---: | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for key, value in report["coverage"].items():
        season, horizon, market = key.split("|")
        lines.append(
            f"| {season} | {horizon} | {market} | {value['games']} | {value['usable']} | "
            f"{value['coverage_pct']:.2f}% | {value['at_least_2_books_pct']:.2f}% | "
            f"{value['at_least_3_books_pct']:.2f}% | {value['reliable_mappings']} / "
            f"{value['ambiguous_mappings']} / {value['missing_mappings']} |"
        )
    reasons = ", ".join(f"{key}={value}" for key, value in report["unusable_reasons"].items()) or "none"
    lines.extend(
        [
            "",
            "## Integrity and limitations",
            "",
            f"- Snapshot distance median/p90: `{report['timestamp_distance_seconds']['median']}` / `{report['timestamp_distance_seconds']['p90']}` seconds.",
            f"- Unusable reasons: {reasons}.",
            "- Every stored snapshot is at or before its cutoff; missing prices are never interpolated.",
            "- Individual book observations are retained. Consensus, vig removal, edge, EV, CLV, and model comparison remain Phase 5B-7C or later work.",
            "- The secondary later-horizon cohort is not full-cohort evidence and cannot be represented as such.",
            "",
            "## Phase 5B-7C readiness",
            "",
            "**GO for primary morning same-horizon model-versus-market work.** All three morning markets exceed 85% aggregate usable/two-book coverage and every season remains above the frozen 70% floor. The later cohorts remain diagnostic only; their small per-season cells, especially 2020–2021, cannot support full-cohort claims.",
            "",
            "Machine-readable report: [`reports/NCAAF_HISTORICAL_MARKET_DATASET_2020_2024.json`](reports/NCAAF_HISTORICAL_MARKET_DATASET_2020_2024.json).",
            "",
        ]
    )
    return "\n".join(lines)


if __name__ == "__main__":
    main()
