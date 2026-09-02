from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from app.api.dependencies import require_principal
from app.domain.identity import Principal
from app.schemas.dashboard import (
    DashboardSystemResponse,
    MarketHistoryResponse,
    MarketMovementResponse,
    MarketRefreshResponse,
)
from app.services.dashboard_service import DashboardService
from app.services.market_refresh_service import (
    MarketRefreshInProgressError,
    MarketRefreshService,
    MarketRefreshUnavailableError,
)

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


def _service(request: Request) -> DashboardService:
    service = getattr(request.app.state, "dashboard_service", None)
    if service is None:
        raise HTTPException(status_code=503, detail="Dashboard read service is unavailable")
    return service


def _refresh_service(request: Request) -> MarketRefreshService:
    service = getattr(request.app.state, "market_refresh_service", None)
    if service is None:
        raise HTTPException(status_code=503, detail="Market refresh is unavailable")
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


@router.get("/market-history", response_model=MarketHistoryResponse)
def market_history(
    request: Request,
    _principal: Annotated[Principal, Depends(require_principal)],
    event_id: UUID,
    market_type: str,
    selection_side: str,
    as_of: Annotated[datetime | None, Query()] = None,
) -> dict[str, Any]:
    cutoff = as_of or request.app.state.clock()
    if cutoff.tzinfo is None:
        raise HTTPException(status_code=422, detail="as_of must include a timezone")
    if market_type not in {"moneyline", "spread", "total"}:
        raise HTTPException(status_code=422, detail="unsupported market_type")
    return _service(request).history(event_id, market_type, selection_side, cutoff)


@router.post("/portfolio/{portfolio_id}/refresh-markets", response_model=MarketRefreshResponse)
def refresh_markets(
    portfolio_id: str,
    request: Request,
    principal: Annotated[Principal, Depends(require_principal)],
) -> dict[str, Any]:
    try:
        return _refresh_service(request).refresh(principal, portfolio_id=portfolio_id)
    except MarketRefreshInProgressError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    except MarketRefreshUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from None
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
