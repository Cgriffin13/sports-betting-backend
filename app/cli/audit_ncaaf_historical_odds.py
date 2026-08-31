from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from dotenv import load_dotenv

from app.providers.odds_api_historical import HistoricalOddsClient
from app.research.ncaaf.historical_odds_audit import (
    HistoricalAuditStore,
    analyze_audit,
    build_audit_plan,
    execute_audit,
    load_audit_games,
    plan_summary,
    render_markdown_report,
    report_for_commit,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the bounded NCAAF historical odds coverage audit")
    parser.add_argument("--execute", action="store_true", help="perform only the frozen bounded provider plan")
    parser.add_argument("--artifact-root", type=Path, default=Path(".ncaaf-data"))
    parser.add_argument("--report", type=Path, default=Path("docs/reports/NCAAF_HISTORICAL_ODDS_AUDIT_2020_2024.json"))
    parser.add_argument("--markdown", type=Path, default=Path("docs/NCAAF_HISTORICAL_ODDS_AUDIT.md"))
    args = parser.parse_args()

    games = load_audit_games(args.artifact_root)
    requests = build_audit_plan(games)
    plan = plan_summary(requests)
    print(json.dumps(plan, indent=2, sort_keys=True), flush=True)
    if not args.execute:
        return

    load_dotenv()
    api_key = os.getenv("ODDS_API_KEY")
    if not api_key:
        raise RuntimeError("ODDS_API_KEY is required; no historical request was made")
    client = HistoricalOddsClient(api_key, timeout_seconds=float(os.getenv("ODDS_API_TIMEOUT_SECONDS", "30")))
    store = HistoricalAuditStore(args.artifact_root)
    responses, execution = execute_audit(requests, client, store)
    report = analyze_audit(requests, games, responses, execution)
    aggregate = report_for_commit(report)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(aggregate, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    args.markdown.write_text(render_markdown_report(report), encoding="utf-8", newline="\n")
    print(
        json.dumps(
            {
                "mode": "executed",
                "historical_network_requests": execution["historical_network_requests"],
                "credits_consumed": execution["credits_consumed"],
                "report_hash": report["report_hash"],
                "decision": report["decision"],
                "report": str(args.report),
                "markdown": str(args.markdown),
            },
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
