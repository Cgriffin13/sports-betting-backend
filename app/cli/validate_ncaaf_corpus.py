from __future__ import annotations

import argparse
import json
from collections import Counter
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from sqlalchemy import func, select

from app.cli.ncaaf_common import research_index_runtime
from app.db.ncaaf_models import FootballGameFact, ProviderProgramMapping, SourceArtifactIndex, SourceManifest
from app.domain.ncaaf import DEVELOPMENT_LAST_SEASON, validate_development_seasons


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate and reconcile the NCAAF development corpus")
    parser.add_argument("--start-season", type=int, default=2014)
    parser.add_argument("--end-season", type=int, default=DEVELOPMENT_LAST_SEASON)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    validate_development_seasons(args.start_season, args.end_season)
    factory, store = research_index_runtime()
    with factory() as session:
        all_game_versions = session.scalars(
            select(FootballGameFact).where(
                FootballGameFact.season.between(args.start_season, args.end_season)
            )
        ).all()
        latest_games = {
            game.provider_game_id: game
            for game in sorted(all_game_versions, key=lambda item: item.created_at)
        }
        games = list(latest_games.values())
        manifests = session.scalars(select(SourceManifest)).all()
        artifacts = session.scalars(
            select(SourceArtifactIndex).where(
                SourceArtifactIndex.season.between(args.start_season, args.end_season)
            )
        ).all()
        program_count = session.scalar(select(func.count()).select_from(ProviderProgramMapping)) or 0
    report = build_report(games, manifests, artifacts, int(program_count), store.root)
    encoded = json.dumps(report, indent=2, sort_keys=True)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded + "\n", encoding="utf-8")
        args.output.with_suffix(".md").write_text(_markdown(report), encoding="utf-8")
    print(encoded)


def build_report(
    games: Sequence[FootballGameFact],
    manifests: Sequence[SourceManifest],
    artifacts: Sequence[SourceArtifactIndex],
    program_count: int,
    artifact_root: Path,
) -> dict[str, Any]:
    by_season = Counter(game.season for game in games)
    fbs_fbs = Counter(game.season for game in games if game.home_classification == game.away_classification == "fbs")
    fbs_fcs = Counter(
        game.season
        for game in games
        if {game.home_classification, game.away_classification} == {"fbs", "fcs"}
    )
    exclusions = Counter(game.exclusion_reason or "eligible" for game in games)
    coverage = Counter(item.artifact_kind for item in artifacts if item.row_count > 0)
    fbs_participant_ids = {
        int(game.provider_game_id)
        for game in games
        if "fbs" in {game.home_classification, game.away_classification}
    }
    covered_ids: dict[str, set[int]] = {}
    for artifact in artifacts:
        covered_ids.setdefault(artifact.artifact_kind, set()).update(artifact.included_game_ids)

    def coverage_summary(kind: str, universe: set[int]) -> dict[str, float | int]:
        covered = len(universe & covered_ids.get(kind, set()))
        return {
            "games": covered,
            "total_games": len(universe),
            "percentage": round(100 * covered / len(universe), 2) if universe else 0.0,
        }
    calls = len(manifests)
    unique_requests = len({item.request_hash for item in manifests})
    return {
        "games_by_season": dict(sorted(by_season.items())),
        "fbs_vs_fbs_by_season": dict(sorted(fbs_fbs.items())),
        "fbs_vs_fcs_by_season": dict(sorted(fbs_fcs.items())),
        "artifact_partitions_with_rows": dict(sorted(coverage.items())),
        "pbp_rows": sum(item.row_count for item in artifacts if item.artifact_kind == "plays"),
        "drive_rows": sum(item.row_count for item in artifacts if item.artifact_kind == "drives"),
        "team_stat_rows": sum(item.row_count for item in artifacts if item.artifact_kind == "games_teams"),
        "pbp_fbs_participant_game_coverage": coverage_summary("plays", fbs_participant_ids),
        "drive_fbs_participant_game_coverage": coverage_summary("drives", fbs_participant_ids),
        "team_stat_fbs_participant_game_coverage": coverage_summary("games_teams", fbs_participant_ids),
        "canonical_program_mappings": program_count,
        "missing_identities": sum(1 for game in games if game.home_program_id is None or game.away_program_id is None),
        "missing_fbs_participant_identities": sum(
            1
            for game in games
            if int(game.provider_game_id) in fbs_participant_ids
            and (game.home_program_id is None or game.away_program_id is None)
        ),
        "ambiguous_mappings": sum(1 for game in games if game.exclusion_reason == "unresolved_program_identity"),
        "exclusions": dict(sorted(exclusions.items())),
        "source_calls_recorded": calls,
        "unique_requests": unique_requests,
        "cache_reuses_or_same_content": max(0, calls - unique_requests),
        "response_bytes": sum(item.response_bytes for item in manifests),
        "stored_bytes": sum(item.stored_bytes for item in manifests),
        "supersessions": sum(item.supersedes_manifest_id is not None for item in manifests),
        "actual_storage_footprint": sum(path.stat().st_size for path in artifact_root.rglob("*") if path.is_file()),
        "reconciliation_note": "Compare definitions, not exact equality, with the cfbfastR QA counts in NCAAF_SOURCE_AUDIT.md.",
    }


def _markdown(report: dict[str, Any]) -> str:
    lines = ["# NCAAF development corpus report", "", "Generated from source manifests and canonical game facts.", ""]
    for key, value in report.items():
        lines.append(f"- **{key.replace('_', ' ').title()}:** `{value}`")
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    main()
