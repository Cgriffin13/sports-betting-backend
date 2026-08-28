from typing import Any

from fastapi import APIRouter, Request

from app.config import Settings
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
        "db_file": str(settings.data_dir / "portfolio_db.json"),
        "data_dir": str(settings.data_dir),
        "time_utc": utc_now_iso(),
    }
