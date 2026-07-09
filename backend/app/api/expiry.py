"""Expiry dashboard API (T040)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from ..auth.deps import current_user, get_ctx
from ..auth.jwt import CurrentUser
from ..context import AppContext
from ..services.expiry import ExpiryDashboard, ExpiryService

router = APIRouter(tags=["expiry"])


@router.get("/expiry", response_model=ExpiryDashboard)
async def expiry_dashboard(
    withinDays: int = Query(default=30, ge=1, le=365),
    ctx: AppContext = Depends(get_ctx),
    _: CurrentUser = Depends(current_user),
):
    return await ExpiryService(ctx).dashboard(withinDays)
