"""Users / directory API + session /me (T011, T024)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, status

from ..auth.deps import current_user, get_ctx, require_admin
from ..auth.jwt import CurrentUser
from ..context import AppContext
from ..models.directory import DirectoryUser
from ..models.membership import Membership
from ..models.transfer import TransferBatchResult
from ..services.memberships import MembershipService
from ..services.transfers import TransferService

router = APIRouter(tags=["users"])


@router.get("/me")
async def me(
    ctx: AppContext = Depends(get_ctx),
    user: CurrentUser = Depends(current_user),
):
    is_admin = user.is_admin(ctx.settings.admin_groups)
    manager_cursor = ctx.app_db.groups.find(
        {"managers": {"$in": [user.userId, user.username]}}, {"name": 1, "_id": 0}
    )
    manager_of = [doc["name"] async for doc in manager_cursor]
    return {
        "userId": user.userId,
        "username": user.username,
        "currentGroups": user.currentGroups,
        "isAdmin": is_admin,
        "managerOf": manager_of,
    }


@router.get("/users", response_model=list[DirectoryUser])
async def search_users(
    q: str = "",
    limit: int = 25,
    ctx: AppContext = Depends(get_ctx),
    _: CurrentUser = Depends(current_user),
):
    return await ctx.directory.search(q, limit=limit)


@router.get("/users/{user_id}/groups", response_model=list[Membership])
async def user_groups(
    user_id: str,
    ctx: AppContext = Depends(get_ctx),
    _: CurrentUser = Depends(current_user),
):
    return await MembershipService(ctx).list_for_user(user_id)


@router.post(
    "/users/{user_id}/deactivate",
    response_model=TransferBatchResult,
    status_code=status.HTTP_202_ACCEPTED,
)
async def deactivate_user(
    user_id: str,
    ctx: AppContext = Depends(get_ctx),
    admin: CurrentUser = Depends(require_admin),
):
    """Mark a user as departed and reassign their owned resources per transfer rules."""
    await ctx.scicat_db[ctx.settings.scicat_identity_collection].update_one(
        {"$or": [{"userId": user_id}, {"profile.id": user_id}]},
        {"$set": {"deactivated": True}},
    )
    await ctx.audit.record(
        actor=admin.userId, action="user.deactivate", entity_type="user",
        entity_id=user_id, summary=f"deactivated {user_id}",
    )
    return await TransferService(ctx).transfer_for_user(
        user_id, reason="departure", actor=admin.userId
    )
