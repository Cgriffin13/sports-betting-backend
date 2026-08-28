import argparse
import json
from pathlib import Path

from app.config import Settings
from app.db.session import create_database_engine, create_session_factory
from app.domain.identity import Principal
from app.migration.json_import import import_json_file


def main() -> None:
    parser = argparse.ArgumentParser(description="Import the prototype portfolio_db.json into the relational ledger")
    parser.add_argument("path", type=Path, help="Path to portfolio_db.json")
    args = parser.parse_args()
    settings = Settings.from_env()
    report = import_json_file(
        args.path,
        create_session_factory(create_database_engine(settings.database_url)),
        Principal(settings.app_owner_id, settings.app_owner_name),
        settings.starting_bankroll,
    )
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
