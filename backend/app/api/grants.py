"""Resource grant API (T035)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import JSONResponse

from ..auth.deps import (
    current_user,
    ensure_can_manage_group,
    get_ctx,
    is_admin,
    require_any_manager,
)
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
    GroupRetiredError,
    InvalidWindowError,
)
from ..services.scicat_client import ScicatError, ScicatUnavailable

router = APIRouter(tags=["grants"])


def _service(ctx: AppContext) -> GrantService:
    return GrantService(ctx)


@router.get("/grants", response_model=list[ResourceGrant])
async def list_grants(
    groupName: str | None = None,
    resourceType: ResourceType | None = None,
    ctx: AppContext = Depends(get_ctx),
    _: CurrentUser = Depends(require_any_manager),
):
    return await _service(ctx).list(groupName, resourceType)


@router.post("/grants", response_model=BulkResult, status_code=status.HTTP_207_MULTI_STATUS)
async def apply_grant(
    payload: GrantApply,
    ctx: AppContext = Depends(get_ctx),
    user: CurrentUser = Depends(current_user),
):
    await ensure_can_manage_group(payload.groupName, user, ctx)
    admin = is_admin(user, ctx)
    if payload.mode == "owner" and not admin:
        # ownerGroup changes run as the service account and could take over any resource
        raise HTTPException(status_code=403, detail="admin required for owner grants")
    try:
        return await _service(ctx).apply(
            payload,
            actor=user.userId,
            allowed_owner_groups=None if admin else set(user.currentGroups),
        )
    except GroupMissingError as exc:
        raise HTTPException(status_code=404, detail=f"group '{exc}' not found") from exc
    except GroupRetiredError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except InvalidWindowError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.delete(
    "/grants/{grant_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={202: {"model": ResourceGrant, "description": "SciCat refused; retried later"}},
)
async def remove_grant(
    grant_id: str,
    ctx: AppContext = Depends(get_ctx),
    user: CurrentUser = Depends(current_user),
):
    svc = _service(ctx)
    try:
        grant = await svc.get(grant_id)
        await ensure_can_manage_group(grant.groupName, user, ctx)
        if grant.mode == "owner" and not is_admin(user, ctx):
            raise HTTPException(status_code=403, detail="admin required for owner grants")
        ended = await svc.remove(grant_id, actor=user.userId)
    except GrantNotFoundError as exc:
        raise HTTPException(status_code=404, detail="grant not found") from exc
    if ended.pendingRemoval:
        # still effective in SciCat; the sweep keeps retrying the withdrawal
        return JSONResponse(status_code=202, content=ended.model_dump(mode="json"))
    return None


@router.get("/resources/{resource_type}", response_model=ResourcePage)
async def browse_resources(
    resource_type: ResourceType,
    q: str | None = None,
    ownerGroup: str | None = None,
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
    ctx: AppContext = Depends(get_ctx),
    user: CurrentUser = Depends(require_any_manager),
):
    restrict = None if is_admin(user, ctx) else list(user.currentGroups)
    try:
        return await _service(ctx).browse(
            resource_type, q, ownerGroup, skip, limit, restrict_owner_groups=restrict
        )
    except ScicatUnavailable as exc:
        raise HTTPException(status_code=503, detail=f"SciCat unavailable: {exc}") from exc
    except ScicatError as exc:
        raise HTTPException(status_code=502, detail=f"SciCat error: {exc}") from exc
