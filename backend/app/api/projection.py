"""Projection / reconciliation API (T030)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from ..auth.deps import get_ctx, require_admin
from ..auth.jwt import CurrentUser
from ..context import AppContext
from ..services.projection import ProjectionService, SyncResult
from ..services.reconcile import ReconcileService
from pydantic import BaseModel

router = APIRouter(prefix="/projection", tags=["projection"])


class ProjectionRequest(BaseModel):
    userId: str | None = None
    groupName: str | None = None
    all: bool = False


@router.post("/run", response_model=SyncResult)
async def run_projection(
    payload: ProjectionRequest,
    ctx: AppContext = Depends(get_ctx),
    user: CurrentUser = Depends(require_admin),
):
    svc = ProjectionService(ctx)
    if payload.userId:
        return await svc.project_users([payload.userId], actor=user.userId)
    if payload.groupName:
        return await svc.project_group(payload.groupName, actor=user.userId)
    if payload.all:
        return await svc.project_all(actor=user.userId)
    raise HTTPException(status_code=400, detail="specify userId, groupName, or all=true")


@router.post("/reconcile", response_model=SyncResult)
async def reconcile(
    ctx: AppContext = Depends(get_ctx),
    user: CurrentUser = Depends(require_admin),
):
    return await ReconcileService(ctx).reconcile(actor=user.userId)


@router.get("/status", response_model=SyncResult)
async def projection_status(
    ctx: AppContext = Depends(get_ctx),
    _: CurrentUser = Depends(require_admin),
):
    return await ProjectionService(ctx).last_status()
