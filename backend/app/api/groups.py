"""Groups API (T018)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status

from ..auth.deps import current_user, ensure_can_manage_group, get_ctx, is_admin, require_admin
from ..auth.jwt import CurrentUser
from ..context import AppContext
from ..models.group import Group, GroupCreate, GroupDetail, GroupUpdate
from ..services.groups import (
    DuplicateGroupError,
    GroupInUseError,
    GroupNotFoundError,
    GroupService,
    HoldersExistError,
    InvalidGroupError,
    ReservedNameError,
)

router = APIRouter(prefix="/groups", tags=["groups"])


def _service(ctx: AppContext) -> GroupService:
    return GroupService(ctx)


@router.get("", response_model=list[Group])
async def list_groups(
    q: str | None = None,
    category: str | None = None,
    status_: str | None = Query(default=None, alias="status"),
    ctx: AppContext = Depends(get_ctx),
    _: CurrentUser = Depends(current_user),
):
    return await _service(ctx).list(q=q, category=category, status=status_)


@router.post("", response_model=Group, status_code=status.HTTP_201_CREATED)
async def create_group(
    payload: GroupCreate,
    ctx: AppContext = Depends(get_ctx),
    user: CurrentUser = Depends(current_user),
):
    if not user.is_admin(ctx.settings.admin_groups):
        raise HTTPException(status_code=403, detail="admin required to create groups")
    try:
        return await _service(ctx).create(payload, actor=user.userId)
    except ReservedNameError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except (DuplicateGroupError, HoldersExistError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except InvalidGroupError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/-/name-check")
async def name_check(
    name: str,
    ctx: AppContext = Depends(get_ctx),
    _: CurrentUser = Depends(require_admin),
):
    """Preflight for group creation: validity, collisions and existing SciCat holders."""
    return await _service(ctx).name_check(name)


@router.get("/{name}", response_model=GroupDetail)
async def get_group(
    name: str,
    ctx: AppContext = Depends(get_ctx),
    _: CurrentUser = Depends(current_user),
):
    try:
        return await _service(ctx).get(name)
    except GroupNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"group '{name}' not found") from exc


@router.patch("/{name}", response_model=Group)
async def update_group(
    name: str,
    payload: GroupUpdate,
    ctx: AppContext = Depends(get_ctx),
    user: CurrentUser = Depends(current_user),
):
    await ensure_can_manage_group(name, user, ctx)
    if not is_admin(user, ctx):
        admin_only = payload.model_fields_set & {"category", "managers", "status"}
        if admin_only:
            raise HTTPException(
                status_code=403,
                detail=f"admin required to change {', '.join(sorted(admin_only))}",
            )
    try:
        return await _service(ctx).update(name, payload, actor=user.userId)
    except GroupNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"group '{name}' not found") from exc
    except InvalidGroupError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.delete("/{name}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_group(
    name: str,
    cascade: bool = False,
    ctx: AppContext = Depends(get_ctx),
    user: CurrentUser = Depends(current_user),
):
    if not user.is_admin(ctx.settings.admin_groups):
        raise HTTPException(status_code=403, detail="admin required to delete groups")
    try:
        await _service(ctx).delete(name, actor=user.userId, cascade=cascade)
    except GroupNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"group '{name}' not found") from exc
    except GroupInUseError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
