"""Users / directory API + session /me (T011, T024)."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query, status

from ..auth.deps import current_user, get_ctx, managed_groups, require_admin, require_any_manager
from ..auth.jwt import AuthError, AuthUnavailable, CurrentUser, validate_token
from ..context import AppContext
from ..models.directory import DirectoryUser, DisplayNameLookup
from ..models.membership import Membership
from ..models.transfer import TransferBatchResult
from ..services.groups import GroupService
from ..services.memberships import MembershipService
from ..services.projection import ProjectionService
from ..services.transfers import TransferService

logger = logging.getLogger(__name__)

router = APIRouter(tags=["users"])


@router.get("/me")
async def me(
    ctx: AppContext = Depends(get_ctx),
    user: CurrentUser = Depends(current_user),
):
    # SciCat rewrites the caller's accessGroups at login and clients (catorga) call /me
    # right after logging in: re-project first so the groups returned — and SciCat's own
    # authorization from now on — already include the app-managed groups.
    try:
        res = await ProjectionService(ctx).project_user(user.userId)
    except Exception:  # noqa: BLE001 - /me must answer even if projection fails
        logger.exception("re-projection on /me failed for %s", user.userId)
        res = None
    if res and res[0]:
        ctx.whoami_cache.drop(user.token)
        try:
            user = await validate_token(user.token, ctx.scicat, ctx.settings, ctx.whoami_cache)
        except (AuthError, AuthUnavailable):
            logger.warning("whoami refresh after projection failed for %s", user.userId)
    is_admin = user.is_admin(ctx.settings.admin_groups)
    manager_of = await managed_groups(user, ctx)
    names = await ctx.directory.display_names([user.username])
    return {
        "userId": user.userId,
        "username": user.username,
        "displayName": names.get(user.username, user.username),
        "email": user.email,
        "currentGroups": user.currentGroups,
        "isAdmin": is_admin,
        "managerOf": manager_of,
    }


@router.post("/users/display-names", response_model=dict[str, str])
async def display_names(
    body: DisplayNameLookup,
    ctx: AppContext = Depends(get_ctx),
    _: CurrentUser = Depends(current_user),
):
    """Resolve usernames (owner / createdBy / personal ownerGroup values) to display names
    for any signed-in user. Only names are returned — no e-mail, no user id; unknown
    usernames (real groups, functional accounts) are left out."""
    wanted = list(dict.fromkeys(u.strip() for u in body.usernames if u and u.strip()))
    return await ctx.directory.display_names(wanted)


@router.get("/users", response_model=list[DirectoryUser])
async def search_users(
    q: str = "",
    limit: int = Query(default=25, ge=1, le=200),
    ctx: AppContext = Depends(get_ctx),
    _: CurrentUser = Depends(require_any_manager),
):
    users = await ctx.directory.search(q, limit=limit)
    departed = {
        doc["_id"]
        async for doc in ctx.app_db.departed_users.find(
            {"_id": {"$in": [u.userId for u in users]}}, {"_id": 1}
        )
    }
    return [u.model_copy(update={"active": False}) if u.userId in departed else u for u in users]


@router.get("/users/{user_id}", response_model=DirectoryUser)
async def get_user(
    user_id: str,
    ctx: AppContext = Depends(get_ctx),
    _: CurrentUser = Depends(require_any_manager),
):
    user = await ctx.directory.get(user_id)
    if not user:
        raise HTTPException(status_code=404, detail=f"user '{user_id}' not found")
    if await ctx.app_db.departed_users.find_one({"_id": user.userId}, {"_id": 1}):
        user = user.model_copy(update={"active": False})
    return user


@router.get("/users/{user_id}/groups", response_model=list[Membership])
async def user_groups(
    user_id: str,
    ctx: AppContext = Depends(get_ctx),
    _: CurrentUser = Depends(require_any_manager),
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
    """Record a departure: end the user's memberships (removing app-managed access in
    SciCat) and hand their personally owned resources to the matching rule's successor.

    SciCat login itself is not blocked by this app; disable the account in the identity
    provider (AD/LDAP) for that.
    """
    directory_user = await ctx.directory.get(user_id)
    known = directory_user or await ctx.app_db.memberships.find_one(
        {"userId": user_id}, {"_id": 1}
    )
    if not known:
        raise HTTPException(status_code=404, detail=f"user '{user_id}' not found")
    # managers have member access: end that too (end_all_for_user re-projects)
    managed = await GroupService(ctx).drop_manager(
        user_id, directory_user.username if directory_user else "", actor=admin.userId
    )
    groups = await MembershipService(ctx).end_all_for_user(user_id, actor=admin.userId)
    await ctx.app_db.departed_users.update_one(
        {"_id": user_id}, {"$set": {"departedAt": ctx.now(), "by": admin.userId}}, upsert=True
    )
    await ctx.audit.record(
        actor=admin.userId, action="user.deactivate", entity_type="user", entity_id=user_id,
        summary=f"deactivated {user_id}"
        + (f"; ended {', '.join(groups)}" if groups else "")
        + (f"; no longer manages {', '.join(managed)}" if managed else ""),
    )
    return await TransferService(ctx).transfer_for_user(
        user_id, reason="departure", actor=admin.userId, groups=groups
    )
