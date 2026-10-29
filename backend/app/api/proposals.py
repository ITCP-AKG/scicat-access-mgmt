"""Proposal create/update proxy.

SciCat v4.3.1 grants proposal create/update only to the `admin` and `proposalingestor`
groups, so group managers and owner-group members cannot write proposals directly. These
routes check the catorga rules and forward the write as the service account:
- create: admins, or managers of the requested ownerGroup;
- update: admins, members of the proposal's ownerGroup (the username counts as a personal
  group), or its managers; moving it to another ownerGroup needs manage rights there.
`accessGroups` is never forwarded — sharing goes through grants.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status

from ..auth.deps import can_manage_group, current_user, ensure_can_manage_group, get_ctx, is_admin
from ..auth.jwt import CurrentUser
from ..context import AppContext
from ..models.proposal import ProposalCreate, ProposalUpdate
from ..services.scicat_client import ScicatError, ScicatUnavailable

router = APIRouter(tags=["proposals"])

_PASSTHROUGH_STATUSES = {400, 404, 409, 422}


def _scicat_http_error(exc: ScicatError) -> HTTPException:
    if isinstance(exc, ScicatUnavailable):
        return HTTPException(status_code=503, detail=f"SciCat unavailable: {exc}")
    if exc.status in _PASSTHROUGH_STATUSES:
        return HTTPException(status_code=exc.status, detail=str(exc))
    return HTTPException(status_code=502, detail=f"SciCat error: {exc}")


async def _can_edit(proposal: dict[str, Any], user: CurrentUser, ctx: AppContext) -> bool:
    owner_group = proposal.get("ownerGroup") or ""
    if is_admin(user, ctx):
        return True
    if owner_group and (owner_group in user.currentGroups or owner_group == user.username):
        return True
    return bool(owner_group) and await can_manage_group(owner_group, user, ctx)


@router.post("/proposals", status_code=status.HTTP_201_CREATED)
async def create_proposal(
    payload: ProposalCreate,
    ctx: AppContext = Depends(get_ctx),
    user: CurrentUser = Depends(current_user),
):
    await ensure_can_manage_group(payload.ownerGroup, user, ctx)
    body = payload.model_dump(exclude={"accessGroups"})
    try:
        created = await ctx.scicat.create_resource("proposal", body)
    except ScicatError as exc:
        raise _scicat_http_error(exc) from exc
    await ctx.audit.record(
        actor=user.userId,
        action="proposal.create",
        entity_type="proposal",
        entity_id=payload.proposalId,
        summary=f"created proposal {payload.proposalId} in {payload.ownerGroup}",
        after=body,
    )
    return created


@router.patch("/proposals/{proposal_id}")
async def update_proposal(
    proposal_id: str,
    payload: ProposalUpdate,
    ctx: AppContext = Depends(get_ctx),
    user: CurrentUser = Depends(current_user),
):
    try:
        existing = await ctx.scicat.get_resource("proposal", proposal_id)
    except ScicatError as exc:
        if exc.status == 404:
            raise HTTPException(status_code=404, detail="proposal not found") from exc
        raise _scicat_http_error(exc) from exc
    if not await _can_edit(existing, user, ctx):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="owner-group membership, group manager or admin required",
        )
    body = payload.model_dump(exclude={"proposalId", "accessGroups"}, exclude_unset=True)
    new_owner = body.get("ownerGroup")
    if new_owner and new_owner != existing.get("ownerGroup"):
        await ensure_can_manage_group(new_owner, user, ctx)
    try:
        updated = await ctx.scicat.patch_resource("proposal", proposal_id, body)
    except ScicatError as exc:
        raise _scicat_http_error(exc) from exc
    await ctx.audit.record(
        actor=user.userId,
        action="proposal.update",
        entity_type="proposal",
        entity_id=proposal_id,
        summary=f"updated proposal {proposal_id}",
        before={k: existing.get(k) for k in body},
        after=body,
    )
    return updated
