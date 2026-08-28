import os
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

# Keep import-time prototype storage out of the repository.
os.environ["DATA_DIR"] = str(Path(tempfile.gettempdir()) / "sports-betting-backend-tests")
os.environ.pop("ODDS_API_KEY", None)

import main  # noqa: E402


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    main.DATA_DIR = tmp_path
    main.DB_FILE = tmp_path / "portfolio_db.json"
    main.DB = main._default_db()
    monkeypatch.setattr(main, "ODDS_API_KEY", None)
    return TestClient(main.app)
