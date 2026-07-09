"""Resource grant API (T035)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status

from ..auth.deps import current_user, get_ctx, require_group_manager
from ..auth.jwt import CurrentUser
from ..context import AppContext
from ..models.resource_grant import (
    BulkResult,
    GrantApply,
    ResourceGrant,
    ResourcePage,
    ResourceType,
)
from ..services.grants import (
    GrantNotFoundError,
    GrantService,
    GroupMissingError,
)
from ..services.scicat_client import ScicatError

router = APIRouter(tags=["grants"])


def _service(ctx: AppContext) -> GrantService:
    return GrantService(ctx)


@router.get("/grants", response_model=list[ResourceGrant])
async def list_grants(
    groupName: str | None = None,
    resourceType: ResourceType | None = None,
    ctx: AppContext = Depends(get_ctx),
    _: CurrentUser = Depends(current_user),
):
    return await _service(ctx).list(groupName, resourceType)


@router.post("/grants", response_model=BulkResult, status_code=status.HTTP_207_MULTI_STATUS)
async def apply_grant(
    payload: GrantApply,
    ctx: AppContext = Depends(get_ctx),
    user: CurrentUser = Depends(current_user),
):
    if not await require_group_manager(payload.groupName, user, ctx):
        raise HTTPException(status_code=403, detail="admin or group manager required")
    try:
        return await _service(ctx).apply(payload, actor=user.userId)
    except GroupMissingError as exc:
        raise HTTPException(status_code=404, detail=f"group '{exc}' not found") from exc


@router.delete("/grants/{grant_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_grant(
    grant_id: str,
    ctx: AppContext = Depends(get_ctx),
    user: CurrentUser = Depends(current_user),
):
    try:
        await _service(ctx).remove(grant_id, actor=user.userId)
    except GrantNotFoundError as exc:
        raise HTTPException(status_code=404, detail="grant not found") from exc


@router.get("/resources/{resource_type}", response_model=ResourcePage)
async def browse_resources(
    resource_type: ResourceType,
    q: str | None = None,
    ownerGroup: str | None = None,
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=500),
    ctx: AppContext = Depends(get_ctx),
    _: CurrentUser = Depends(current_user),
):
    try:
        return await _service(ctx).browse(resource_type, q, ownerGroup, skip, limit)
    except ScicatError as exc:
        raise HTTPException(status_code=502, detail=f"SciCat unreachable: {exc}") from exc
