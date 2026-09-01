from __future__ import annotations

import argparse
import json
import os
import subprocess
from pathlib import Path
from typing import Sequence

from dotenv import load_dotenv

from app.providers.odds_api_historical import HistoricalOddsClient
from app.research.ncaaf.historical_market_dataset import (
    HistoricalMarketCache,
    acquisition_plan_summary,
    build_historical_market_dataset,
    build_morning_plan,
    execute_plan,
    load_cached_responses,
    load_market_games,
)

from app.research.ncaaf.holdout import (
    HOLDOUT_MARKET_CALLS,
    HOLDOUT_MARKET_CREDIT_LIMIT,
    HOLDOUT_MARKET_PLAN_HASH,
    assemble_normalized_holdout_manifest,
    create_unlock_record,
    load_unlock_record,
)
from app.research.ncaaf.holdout_evaluation import run_holdout_evaluation, validate_holdout_report


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description="Operate the one-time Phase 5B-9 NCAAF holdout boundary")
    result.add_argument(
        "command",
        choices=(
            "unlock",
            "verify-unlock",
            "assemble-normalized",
            "market-preflight",
            "acquire-market",
            "build-market",
            "evaluate",
            "validate-evaluation",
        ),
    )
    result.add_argument("--artifact-root", type=Path, default=Path(".ncaaf-data"))
    result.add_argument("--freeze", type=Path, default=Path("docs/reports/NCAAF_FINALIST_FREEZE_V1.json"))
    result.add_argument("--command-id", default="phase-5b-9-locked-holdout")
    result.add_argument("--development-manifest")
    result.add_argument("--holdout-manifest")
    result.add_argument("--normalized-manifest")
    result.add_argument("--feature-manifest")
    result.add_argument("--market-manifest")
    result.add_argument("--report", type=Path, default=Path("docs/reports/NCAAF_2025_HOLDOUT_V1.json"))
    return result


def main(argv: Sequence[str] | None = None) -> int:
    arguments = parser().parse_args(argv)
    if arguments.command == "unlock":
        freeze = json.loads(arguments.freeze.read_text(encoding="utf-8"))
        commit = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        record = create_unlock_record(
            arguments.artifact_root,
            freeze,
            code_commit=commit,
            command_id=arguments.command_id,
        )
    elif arguments.command == "verify-unlock":
        record = load_unlock_record(arguments.artifact_root)
    elif arguments.command == "assemble-normalized":
        load_unlock_record(arguments.artifact_root)
        if not arguments.development_manifest or not arguments.holdout_manifest:
            raise ValueError("assemble-normalized requires both manifest IDs")
        manifest = assemble_normalized_holdout_manifest(
            arguments.artifact_root,
            development_manifest_id=arguments.development_manifest,
            holdout_manifest_id=arguments.holdout_manifest,
        )
        print(
            json.dumps(
                {
                    "manifest_id": manifest["manifest_id"],
                    "dataset_hash": manifest["dataset_hash"],
                    "artifacts": len(manifest["artifacts"]),
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0
    elif arguments.command == "evaluate":
        if not arguments.feature_manifest or not arguments.market_manifest:
            raise ValueError("evaluate requires feature and market manifest IDs")
        freeze = json.loads(arguments.freeze.read_text(encoding="utf-8"))
        commit = subprocess.run(
            ["git", "rev-parse", "HEAD"], check=True, capture_output=True, text=True
        ).stdout.strip()
        report = run_holdout_evaluation(
            arguments.artifact_root,
            freeze,
            feature_manifest_id=arguments.feature_manifest,
            market_manifest_id=arguments.market_manifest,
            code_commit=commit,
        )
        arguments.report.parent.mkdir(parents=True, exist_ok=True)
        arguments.report.write_text(
            json.dumps(report, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8"
        )
        print(
            json.dumps(
                {
                    "status": report["status"],
                    "decision": report["decision"],
                    "holdout_run_hash": report["holdout_run_hash"],
                    "total_common_cohort": report["coverage"]["total_common_cohort"],
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0
    elif arguments.command == "validate-evaluation":
        report = json.loads(arguments.report.read_text(encoding="utf-8"))
        errors = validate_holdout_report(arguments.artifact_root, report)
        print(json.dumps({"valid": not errors, "errors": errors}, indent=2, sort_keys=True))
        return 1 if errors else 0
    else:
        load_unlock_record(arguments.artifact_root)
        if not arguments.normalized_manifest:
            raise ValueError("market-preflight requires --normalized-manifest")
        games = load_market_games(
            arguments.artifact_root,
            start_season=2025,
            end_season=2025,
            allow_holdout_access=True,
            normalized_manifest_id=arguments.normalized_manifest,
        )
        requests = build_morning_plan(games)
        key: str | None = None
        available: int | None = None
        if arguments.command != "build-market":
            load_dotenv(dotenv_path=Path(".env"))
            key = os.getenv("ODDS_API_KEY")
            if not key:
                raise RuntimeError("ODDS_API_KEY is required; no historical request was made")
            usage = HistoricalOddsClient(key).usage()
            raw_available = usage.get("requests_remaining")
            available = raw_available if isinstance(raw_available, int) else None
        summary = acquisition_plan_summary(
            requests,
            HistoricalMarketCache(arguments.artifact_root),
            available_credits=available,
        )
        if summary["acquisition_plan_hash"] != HOLDOUT_MARKET_PLAN_HASH:
            raise RuntimeError("2025 market plan does not match the frozen preflight")
        if int(summary["logical_requests"]) != HOLDOUT_MARKET_CALLS:
            raise RuntimeError("2025 market plan request count changed after preflight")
        compact = {
            key: summary[key]
            for key in (
                "logical_requests",
                "unique_provider_requests",
                "cache_hits",
                "expected_new_credits",
                "available_credits",
                "expected_remaining_credits",
                "acquisition_plan_hash",
            )
        }
        print(
            json.dumps(compact, indent=2, sort_keys=True),
            flush=True,
        )
        if arguments.command == "acquire-market":
            assert key is not None
            _, execution = execute_plan(
                requests,
                HistoricalOddsClient(key),
                HistoricalMarketCache(arguments.artifact_root),
                credit_limit=HOLDOUT_MARKET_CREDIT_LIMIT,
                new_call_limit=HOLDOUT_MARKET_CALLS,
            )
            path = arguments.artifact_root / "holdout-2025" / "market-acquisition.json"
            path.write_text(json.dumps(execution, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            print(
                json.dumps(
                    {
                        "network_calls": execution["network_calls"],
                        "credits_consumed": execution["credits_consumed"],
                        "remaining_credits": execution["usage_after"].get("requests_remaining"),
                    },
                    indent=2,
                    sort_keys=True,
                )
            )
        elif arguments.command == "build-market":
            responses = load_cached_responses(requests, HistoricalMarketCache(arguments.artifact_root))
            manifest = build_historical_market_dataset(
                arguments.artifact_root,
                games,
                requests,
                responses,
                acquisition_plan_hashes=[HOLDOUT_MARKET_PLAN_HASH],
                holdout=True,
            )
            print(
                json.dumps(
                    {
                        "manifest_id": manifest["manifest_id"],
                        "dataset_hash": manifest["dataset_hash"],
                        "events": manifest["event_count"],
                        "groups": manifest["group_count"],
                        "observations": manifest["row_count"],
                    },
                    indent=2,
                    sort_keys=True,
                )
            )
        return 0
    print(
        json.dumps(
            {
                "unlock_id": record["unlock_id"],
                "unlocked_at": record["unlocked_at"],
                "holdout_season": record["holdout_season"],
                "code_commit": record["code_commit"],
                "freeze_hash": record["freeze_hash"],
                "freeze_verified_before_unlock": record["freeze_verified_before_unlock"],
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
