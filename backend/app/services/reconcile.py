"""Reconciliation: detect + fix drift between app state and SciCat (T029)."""

from __future__ import annotations

from ..context import AppContext
from .grants import GrantService
from .projection import DriftItem, ProjectionService, SyncResult


class ReconcileService:
    def __init__(self, ctx: AppContext) -> None:
        self.ctx = ctx
        self.projection = ProjectionService(ctx)

    async def reconcile(self, *, apply: bool = True, actor: str = "system") -> SyncResult:
        """Compare intended vs actual state: users' accessGroups and applied grants.

        Covers members, users the app has projected onto (so names of deleted groups get
        cleaned up) and any identity carrying a registered group name. Reports drift; when
        apply=True, writes the corrected target. Safe if SciCat is unreachable — the
        intended (app) state is never mutated, so a later run recovers.
        """
        result = SyncResult(ranAt=self.ctx.now())
        registry = await self.projection.registry()
        open_members = {
            doc["userId"]
            async for doc in self.ctx.app_db.memberships.find(
                {"status": {"$in": ["active", "scheduled"]}}, {"userId": 1, "_id": 0}
            )
        }

        for uid in sorted(await self.projection.managed_user_ids(registry)):
            try:
                plan = await self.projection.plan_user(uid, registry)
                if plan is None:
                    if uid in open_members:
                        result.errors.append(f"{uid}: no SciCat identity")
                    continue
                if plan.changed:
                    result.drift.append(
                        DriftItem(userId=uid, expected=plan.target, actual=plan.current)
                    )
                if apply:
                    res = await self.projection.project_user(uid, actor=actor, registry=registry)
                    if res and res[0]:
                        result.usersUpdated += 1
            except Exception as exc:  # noqa: BLE001 - record and continue
                result.errors.append(f"{uid}: {exc}")

        grant_drift, grant_errors = await GrantService(self.ctx).check_drift(
            apply=apply, actor=actor
        )
        result.grantDrift = grant_drift
        result.errors.extend(grant_errors)

        await self.ctx.app_db.sync_state.update_one(
            {"_id": "reconcile"},
            {"$set": {"lastRunAt": result.ranAt, "lastResult": result.model_dump(mode="json")}},
            upsert=True,
        )
        return result
