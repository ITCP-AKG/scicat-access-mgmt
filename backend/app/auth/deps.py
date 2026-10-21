"""FastAPI auth dependencies (T008).

Roles:
- admin: the caller's SciCat currentGroups intersect `ADMIN_GROUPS`;
- group manager: the caller's userId (or, for older records, username) is listed in a
  group's `managers`. Managers act only on their own groups.
All SciCat resource calls run as the service account, so these checks are the only thing
standing between a caller and SciCat — every mutating route must use one of them.
"""

from __future__ import annotations

from fastapi import Depends, Header, HTTPException, Request, status

from ..context import AppContext
from .jwt import AuthError, AuthUnavailable, CurrentUser, validate_token


def get_ctx(request: Request) -> AppContext:
    ctx = getattr(request.app.state, "ctx", None)
    if ctx is None:  # pragma: no cover - misconfiguration
        raise HTTPException(status_code=500, detail="app context not initialised")
    return ctx


async def current_user(
    authorization: str = Header(default=""),
    ctx: AppContext = Depends(get_ctx),
) -> CurrentUser:
    token = authorization[7:] if authorization.lower().startswith("bearer ") else authorization
    try:
        return await validate_token(token.strip(), ctx.scicat, ctx.settings, ctx.whoami_cache)
    except AuthError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc
    except AuthUnavailable as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc


def is_admin(user: CurrentUser, ctx: AppContext) -> bool:
    return user.is_admin(ctx.settings.admin_groups)


async def managed_groups(user: CurrentUser, ctx: AppContext) -> list[str]:
    """Names of the groups the caller manages (ignores admin rights)."""
    ids = [i for i in (user.userId, user.username) if i]
    cursor = ctx.app_db.groups.find({"managers": {"$in": ids}}, {"name": 1, "_id": 0})
    return [doc["name"] async for doc in cursor]


async def can_manage_group(group_name: str, user: CurrentUser, ctx: AppContext) -> bool:
    """Allowed if the caller is an admin or a registered manager of the group."""
    if is_admin(user, ctx):
        return True
    group = await ctx.app_db.groups.find_one({"name": group_name}, {"managers": 1})
    managers = (group or {}).get("managers", [])
    return bool(user.userId and user.userId in managers) or bool(
        user.username and user.username in managers
    )


async def ensure_can_manage_group(group_name: str, user: CurrentUser, ctx: AppContext) -> None:
    if not await can_manage_group(group_name, user, ctx):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="admin or group manager required"
        )


async def require_admin(
    user: CurrentUser = Depends(current_user),
    ctx: AppContext = Depends(get_ctx),
) -> CurrentUser:
    if not is_admin(user, ctx):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="admin required")
    return user


async def require_any_manager(
    user: CurrentUser = Depends(current_user),
    ctx: AppContext = Depends(get_ctx),
) -> CurrentUser:
    """Admins, or callers that manage at least one group (directory/grant/expiry views)."""
    if is_admin(user, ctx) or await managed_groups(user, ctx):
        return user
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN, detail="admin or group manager required"
    )
