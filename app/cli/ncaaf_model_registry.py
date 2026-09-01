from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

from app.db.session import create_database_engine, create_session_factory
from app.persistence.model_registry_repository import SqlAlchemyModelRegistryRepository
from app.research.ncaaf.model_registry import (
    registrations_from_manifest,
    validate_registry_manifest,
    verify_authoritative_reports,
    write_registry_manifest,
)

DEFAULT_MANIFEST = Path("docs/reports/NCAAF_MODEL_REGISTRY_V1.json")


def main() -> None:
    parser = argparse.ArgumentParser(description="NCAAF model/artifact registry")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("build", "validate", "sync", "list"):
        command = sub.add_parser(name)
        command.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    inspect = sub.add_parser("inspect")
    inspect.add_argument("model_id")
    inspect.add_argument("version")
    args = parser.parse_args()

    if args.command == "build":
        manifest = write_registry_manifest(args.manifest)
        print(json.dumps({"registry_hash": manifest["registry_hash"], "models": len(manifest["models"])}))
        return
    if args.command == "validate":
        manifest = _read(args.manifest)
        errors = [*validate_registry_manifest(manifest), *verify_authoritative_reports(Path.cwd())]
        if errors:
            raise SystemExit("; ".join(errors))
        print(json.dumps({"valid": True, "registry_hash": manifest["registry_hash"]}))
        return
    repository = _repository()
    if args.command == "sync":
        manifest = _read(args.manifest)
        errors = validate_registry_manifest(manifest)
        if errors:
            raise SystemExit("; ".join(errors))
        models, artifacts = registrations_from_manifest(manifest)
        repository.register_models(models)
        repository.register_artifacts(artifacts)
        print(json.dumps({"models": len(models), "artifacts": len(artifacts), "registry_hash": manifest["registry_hash"]}))
        return
    if args.command == "list":
        print(json.dumps([_model_dict(item) for item in repository.list_models(league="NCAAF")], indent=2))
        return
    model = repository.get_model(args.model_id, args.version)
    if model is None:
        raise SystemExit("model/version not found")
    print(json.dumps(_model_dict(model), indent=2))


def _repository() -> SqlAlchemyModelRegistryRepository:
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise SystemExit("DATABASE_URL is required")
    return SqlAlchemyModelRegistryRepository(create_session_factory(create_database_engine(database_url)))


def _model_dict(item: Any) -> dict[str, Any]:
    return {
        "model_id": item.model_id,
        "version": item.version,
        "league": item.league,
        "market_type": item.market_type,
        "status": item.status,
        "model_family": item.model_family,
        "registry_entry_hash": item.registry_entry_hash,
    }


def _read(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    main()
