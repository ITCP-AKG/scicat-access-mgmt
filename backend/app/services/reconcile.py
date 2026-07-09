"""Reconciliation: detect + fix drift between app state and SciCat (T029)."""

from __future__ import annotations

from ..context import AppContext
from .projection import DriftItem, ProjectionService, SyncResult


class ReconcileService:
    def __init__(self, ctx: AppContext) -> None:
        self.ctx = ctx
        self.projection = ProjectionService(ctx)

    async def reconcile(self, *, apply: bool = True, actor: str = "system") -> SyncResult:
        """Compare intended vs actual accessGroups for every user with memberships.

        Reports drift; when apply=True, writes the corrected target. Safe if SciCat is
        unreachable — the intended (app) state is never mutated, so a later run recovers.
        """
        result = SyncResult(ranAt=self.ctx.now())
        cursor = self.ctx.app_db.memberships.find({}, {"userId": 1, "_id": 0})
        user_ids = list({doc["userId"] async for doc in cursor})

        for uid in user_ids:
            identity = await self.projection.identities.find_one(
                {"$or": [{"userId": uid}, {"profile.id": uid}]}
            )
            if not identity:
                result.errors.append(f"{uid}: no SciCat identity")
                continue
            current = list((identity.get("profile") or {}).get("accessGroups") or [])
            app_owned = await self.projection._app_owned_names()
            active = await self.projection._active_groups_for_user(uid)
            target = self.projection._compute_target(current, app_owned, active)
            if set(target) != set(current):
                result.drift.append(DriftItem(userId=uid, expected=target, actual=current))
                if apply:
                    res = await self.projection.project_user(uid, actor=actor)
                    if res and res[0]:
                        result.usersUpdated += 1

        await self.ctx.app_db.sync_state.update_one(
            {"_id": "reconcile"},
            {"$set": {"lastRunAt": result.ranAt, "lastResult": result.model_dump(mode="json")}},
            upsert=True,
        )
        return result
