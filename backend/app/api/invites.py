"""Group invitation API.

Managers (and admins) invite by e-mail and manage a group's invitations; the invitee
previews the invitation without logging in and accepts it signed in (catorga's
`#/invite/<token>` page).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from ..auth.deps import current_user, ensure_can_manage_group, get_ctx
from ..auth.jwt import CurrentUser
from ..context import AppContext
from ..models.invite import InviteAccepted, InviteCreate, InviteCreated, InviteOut, InvitePreview
from ..services.invites import (
    InvalidInviteError,
    InviteEmailMismatchError,
    InviteGoneError,
    InviteNotFoundError,
    InviteService,
)
from ..services.memberships import MembershipError

router = APIRouter(tags=["invites"])


def _public(invite) -> InviteOut:
    return InviteOut(**invite.model_dump(exclude={"tokenHash"}))


@router.post("/invites", response_model=InviteCreated, status_code=status.HTTP_201_CREATED)
async def create_invite(
    payload: InviteCreate,
    ctx: AppContext = Depends(get_ctx),
    user: CurrentUser = Depends(current_user),
):
    await ensure_can_manage_group(payload.groupName, user, ctx)
    try:
        return await InviteService(ctx).create(payload, actor=user.userId)
    except InvalidInviteError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/invites", response_model=list[InviteOut])
async def list_invites(
    groupName: str,
    ctx: AppContext = Depends(get_ctx),
    user: CurrentUser = Depends(current_user),
):
    await ensure_can_manage_group(groupName, user, ctx)
    return [_public(i) for i in await InviteService(ctx).list(groupName)]


@router.delete("/invites/{invite_id}", response_model=InviteOut)
async def revoke_invite(
    invite_id: str,
    ctx: AppContext = Depends(get_ctx),
    user: CurrentUser = Depends(current_user),
):
    svc = InviteService(ctx)
    try:
        invite = await svc.get(invite_id)
    except InviteNotFoundError as exc:
        raise HTTPException(status_code=404, detail="invitation not found") from exc
    await ensure_can_manage_group(invite.groupName, user, ctx)
    return _public(await svc.revoke(invite_id, actor=user.userId))


@router.get("/invites/by-token/{token}", response_model=InvitePreview)
async def preview_invite(token: str, ctx: AppContext = Depends(get_ctx)):
    """No login needed: the token is unguessable and meant for its holder."""
    try:
        return await InviteService(ctx).preview(token)
    except InviteNotFoundError as exc:
        raise HTTPException(status_code=404, detail="invitation not found") from exc


@router.post("/invites/by-token/{token}/accept", response_model=InviteAccepted)
async def accept_invite(
    token: str,
    ctx: AppContext = Depends(get_ctx),
    user: CurrentUser = Depends(current_user),
):
    try:
        accepted = await InviteService(ctx).accept(token, user)
    except InviteNotFoundError as exc:
        raise HTTPException(status_code=404, detail="invitation not found") from exc
    except InviteEmailMismatchError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except InviteGoneError as exc:
        raise HTTPException(status_code=410, detail=str(exc)) from exc
    except MembershipError as exc:  # e.g. the account has no SciCat identity
        raise HTTPException(status_code=422, detail=f"could not join: {exc}") from exc
    # the caller's groups changed: the next /me must not answer from the whoami cache
    ctx.whoami_cache.drop(user.token)
    return accepted
