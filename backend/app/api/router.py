"""Aggregate all API routers under /api/v1 (T011)."""

from __future__ import annotations

from fastapi import APIRouter

from . import audit, expiry, grants, groups, memberships, projection, transfers, users

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(users.router)
api_router.include_router(groups.router)
api_router.include_router(memberships.router)
api_router.include_router(projection.router)
api_router.include_router(grants.router)
api_router.include_router(expiry.router)
api_router.include_router(transfers.router)
api_router.include_router(audit.router)
