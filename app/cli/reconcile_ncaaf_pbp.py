from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from app.research.ncaaf.artifacts import ResearchArtifactStore
from app.research.ncaaf.reconciliation import reconcile_pbp


def main() -> None:
    parser = argparse.ArgumentParser(description="Reconcile normalized CFBD plays with cached cfbfastR QA game counts")
    parser.add_argument("--qa-counts", type=Path, required=True)
    parser.add_argument("--normalized-manifest")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    store = ResearchArtifactStore(Path(os.getenv("NCAAF_RESEARCH_ARTIFACT_DIR", ".ncaaf-data")))
    manifest = store.load_manifest("normalized", args.normalized_manifest)
    games: list[dict[str, object]] = []
    plays: list[dict[str, object]] = []
    for artifact in manifest["artifacts"]:
        if artifact["dataset"] == "games":
            games.extend(store.read_table(artifact["uri"]).to_pylist())
        elif artifact["dataset"] == "plays":
            plays.extend(store.read_table(artifact["uri"], columns=["provider_game_id"]).to_pylist())
    report = reconcile_pbp(plays, games, json.loads(args.qa_counts.read_text(encoding="utf-8")))
    text = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
    print(
        json.dumps(
            {
                key: report[key]
                for key in (
                    "common_season_cfbd_rows",
                    "common_season_cfbfastR_rows",
                    "common_season_difference",
                    "assessment",
                )
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
