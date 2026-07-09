"""FastAPI auth dependencies (T008)."""

from __future__ import annotations

from fastapi import Depends, Header, HTTPException, Request, status

from ..context import AppContext
from .jwt import AuthError, CurrentUser, validate_token


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
        return await validate_token(token, ctx.scicat, ctx.settings)
    except AuthError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc


async def require_admin(
    user: CurrentUser = Depends(current_user),
    ctx: AppContext = Depends(get_ctx),
) -> CurrentUser:
    if not user.is_admin(ctx.settings.admin_groups):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="admin required")
    return user


async def require_group_manager(
    group_name: str,
    user: CurrentUser,
    ctx: AppContext,
) -> bool:
    """Allowed if the caller is an admin or a registered manager of the group."""
    if user.is_admin(ctx.settings.admin_groups):
        return True
    group = await ctx.app_db.groups.find_one({"name": group_name}, {"managers": 1})
    managers = (group or {}).get("managers", [])
    return user.userId in managers or user.username in managers
