"""Membership API (T024)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from ..auth.deps import current_user, ensure_can_manage_group, get_ctx, require_any_manager
from ..auth.jwt import CurrentUser
from ..context import AppContext
from ..models.membership import Membership, MembershipCreate, MembershipUpdate
from ..services.memberships import (
    DuplicateMembershipError,
    GroupMissingError,
    InvalidWindowError,
    LastAdminError,
    MembershipEndedError,
    MembershipNotFoundError,
    MembershipService,
    UserMissingError,
)

router = APIRouter(tags=["memberships"])


def _service(ctx: AppContext) -> MembershipService:
    return MembershipService(ctx)


@router.get("/groups/{name}/members", response_model=list[Membership])
async def list_members(
    name: str,
    ctx: AppContext = Depends(get_ctx),
    _: CurrentUser = Depends(require_any_manager),
):
    return await _service(ctx).list_for_group(name)


@router.post(
    "/groups/{name}/members", response_model=Membership, status_code=status.HTTP_201_CREATED
)
async def add_member(
    name: str,
    payload: MembershipCreate,
    ctx: AppContext = Depends(get_ctx),
    user: CurrentUser = Depends(current_user),
):
    await ensure_can_manage_group(name, user, ctx)
    try:
        return await _service(ctx).add(name, payload, actor=user.userId)
    except GroupMissingError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except UserMissingError as exc:
        raise HTTPException(status_code=404, detail=f"user '{payload.userId}' not found") from exc
    except DuplicateMembershipError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except InvalidWindowError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.patch("/memberships/{membership_id}", response_model=Membership)
async def update_membership(
    membership_id: str,
    payload: MembershipUpdate,
    ctx: AppContext = Depends(get_ctx),
    user: CurrentUser = Depends(current_user),
):
    svc = _service(ctx)
    try:
        membership = await svc.get(membership_id)
        await ensure_can_manage_group(membership.groupName, user, ctx)
        return await svc.update(membership_id, payload, actor=user.userId)
    except MembershipNotFoundError as exc:
        raise HTTPException(status_code=404, detail="membership not found") from exc
    except MembershipEndedError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except InvalidWindowError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.delete("/memberships/{membership_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_membership(
    membership_id: str,
    ctx: AppContext = Depends(get_ctx),
    user: CurrentUser = Depends(current_user),
):
    svc = _service(ctx)
    try:
        membership = await svc.get(membership_id)
        await ensure_can_manage_group(membership.groupName, user, ctx)
        await svc.revoke(membership_id, actor=user.userId)
    except MembershipNotFoundError as exc:
        raise HTTPException(status_code=404, detail="membership not found") from exc
    except LastAdminError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
