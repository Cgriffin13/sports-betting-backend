from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from app.api.dependencies import require_principal
from app.domain.identity import Principal
from app.schemas.dashboard import DashboardSystemResponse, MarketMovementResponse
from app.services.dashboard_service import DashboardService

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


def _service(request: Request) -> DashboardService:
    service = getattr(request.app.state, "dashboard_service", None)
    if service is None:
        raise HTTPException(status_code=503, detail="Dashboard read service is unavailable")
    return service


@router.get("/system", response_model=DashboardSystemResponse)
def dashboard_system(
    request: Request,
    _principal: Annotated[Principal, Depends(require_principal)],
) -> dict[str, Any]:
    return _service(request).system(request.app.state.clock())


@router.get("/market-movement", response_model=MarketMovementResponse)
def market_movement(
    request: Request,
    _principal: Annotated[Principal, Depends(require_principal)],
    slate_date: date,
    as_of: Annotated[datetime | None, Query()] = None,
) -> dict[str, Any]:
    cutoff = as_of or request.app.state.clock()
    if cutoff.tzinfo is None:
        raise HTTPException(status_code=422, detail="as_of must include a timezone")
    return _service(request).movement(slate_date, cutoff)
