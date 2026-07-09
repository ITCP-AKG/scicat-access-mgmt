"""Expiry dashboard data (T040).

Surfaces memberships about to lapse, those that recently lapsed, and grants about to
lapse — within a caller-supplied window (default from settings). Read-only.
"""

from __future__ import annotations

from datetime import timedelta

from pydantic import BaseModel

from ..context import AppContext
from ..models.membership import Membership
from ..models.resource_grant import ResourceGrant


class ExpiryDashboard(BaseModel):
    expiringSoon: list[Membership] = []
    recentlyExpired: list[Membership] = []
    expiringGrants: list[ResourceGrant] = []


class ExpiryService:
    def __init__(self, ctx: AppContext) -> None:
        self.ctx = ctx

    async def dashboard(self, within_days: int) -> ExpiryDashboard:
        now = self.ctx.now()
        horizon = now + timedelta(days=within_days)
        past = now - timedelta(days=within_days)

        soon = self.ctx.app_db.memberships.find(
            {"status": "active", "expiresAt": {"$ne": None, "$gt": now, "$lte": horizon}},
            {"_id": 0},
        ).sort("expiresAt", 1)
        recent = self.ctx.app_db.memberships.find(
            {"status": "expired", "endedAt": {"$gte": past, "$lte": now}}, {"_id": 0}
        ).sort("endedAt", -1)
        grants = self.ctx.app_db.resource_grants.find(
            {"status": "active", "expiresAt": {"$ne": None, "$gt": now, "$lte": horizon}},
            {"_id": 0},
        ).sort("expiresAt", 1)

        return ExpiryDashboard(
            expiringSoon=[Membership(**doc) async for doc in soon],
            recentlyExpired=[Membership(**doc) async for doc in recent],
            expiringGrants=[ResourceGrant(**doc) async for doc in grants],
        )
