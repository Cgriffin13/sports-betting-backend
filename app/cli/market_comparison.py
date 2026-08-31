from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.research.ncaaf.artifacts import ResearchArtifactStore
from app.research.ncaaf.market_comparison import (
    build_market_comparison_dataset,
    render_market_comparison_report,
    summarize_market_comparison,
    validate_market_comparison_dataset,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Offline NCAAF market-comparison plumbing")
    parser.add_argument("action", choices=("build", "consensus", "join", "residuals", "features", "validate", "inspect", "summarize"))
    parser.add_argument("--artifact-root", type=Path, default=Path(".ncaaf-data"))
    parser.add_argument("--event-id")
    parser.add_argument("--report", type=Path, default=Path("docs/reports/NCAAF_MARKET_COMPARISON_DATASET_2020_2024.json"))
    parser.add_argument("--markdown", type=Path, default=Path("docs/NCAAF_MARKET_COMPARISON_DATASET_REPORT.md"))
    args = parser.parse_args()
    root = args.artifact_root
    if args.action in {"build", "consensus", "join", "residuals", "features"}:
        manifest = build_market_comparison_dataset(root)
    else:
        manifest = ResearchArtifactStore(root).load_manifest("market-comparison")
    if args.action == "validate":
        errors = validate_market_comparison_dataset(root, manifest)
        print(json.dumps({"valid": not errors, "errors": errors, "dataset_hash": manifest["dataset_hash"]}, indent=2))
        if errors:
            raise SystemExit(1)
        return
    report = summarize_market_comparison(root, manifest)
    if args.action == "inspect":
        if not args.event_id:
            raise ValueError("inspect requires --event-id")
        store = ResearchArtifactStore(root)
        rows: list[dict[str, object]] = []
        for artifact in manifest["artifacts"]:
            rows.extend({"dataset": artifact["dataset"], **row} for row in store.read_table(artifact["uri"]).to_pylist() if row.get("canonical_event_id") == args.event_id)
        print(json.dumps(rows, indent=2, default=str))
        return
    if args.action in {"build", "summarize"}:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        args.markdown.write_text(render_market_comparison_report(report), encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
