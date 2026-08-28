from typing import Any

from fastapi import APIRouter, Request

from app.config import Settings
from app.db.session import normalize_database_url
from app.services.odds_service import OddsService
from app.time import utc_now_iso

router = APIRouter()


@router.get("/health")
def health(request: Request) -> dict[str, Any]:
    settings: Settings = request.app.state.settings
    odds_service: OddsService = request.app.state.odds_service
    return {
        "ok": True,
        "has_odds_key": odds_service.provider_configured,
        "db_file": None,
        "data_dir": str(settings.data_dir),
        "database_configured": bool(settings.database_url),
        "database_dialect": normalize_database_url(settings.database_url).split(":", 1)[0],
        "time_utc": utc_now_iso(),
    }
