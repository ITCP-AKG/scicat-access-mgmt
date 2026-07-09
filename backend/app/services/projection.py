"""Projection engine (T028).

Computes each user's effective access groups (union of currently-active memberships)
and writes them into SciCat's UserIdentity.profile.accessGroups. CRITICAL INVARIANT:
only group names the app owns (present in the `groups` registry) are added/removed;
all other strings (globalaccess, per-user groups, roles, unknown access groups) are
PRESERVED — divergence is surfaced as drift, never silently deleted (research.md R2).
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel

from ..context import AppContext
from ..models.membership import compute_status


class DriftItem(BaseModel):
    userId: str
    expected: list[str]
    actual: list[str]


class SyncResult(BaseModel):
    ranAt: datetime
    usersUpdated: int = 0
    drift: list[DriftItem] = []
    errors: list[str] = []


class ProjectionService:
    def __init__(self, ctx: AppContext) -> None:
        self.ctx = ctx
        self.identities = ctx.scicat_db[ctx.settings.scicat_identity_collection]

    async def _app_owned_names(self) -> set[str]:
        cursor = self.ctx.app_db.groups.find({}, {"name": 1, "_id": 0})
        return {doc["name"] async for doc in cursor}

    async def _active_groups_for_user(self, user_id: str) -> set[str]:
        now = self.ctx.now()
        cursor = self.ctx.app_db.memberships.find({"userId": user_id}, {"_id": 0})
        active: set[str] = set()
        async for doc in cursor:
            status = compute_status(
                doc.get("effectiveFrom"), doc.get("expiresAt"), now,
                ended=doc.get("status") == "revoked",
            )
            if status == "active":
                active.add(doc["groupName"])
        return active

    def _compute_target(
        self, current: list[str], app_owned: set[str], active: set[str]
    ) -> list[str]:
        # keep everything the app does not manage, then add the user's active app-owned groups
        preserved = [g for g in current if g not in app_owned]
        result = list(dict.fromkeys(preserved + sorted(active)))
        return result

    async def project_user(self, user_id: str, *, actor: str = "system", apply: bool = True):
        """Project one user; returns (changed: bool, target: list[str]) or None if no identity."""
        doc = await self.identities.find_one(
            {"$or": [{"userId": user_id}, {"profile.id": user_id}]}
        )
        if not doc:
            return None
        profile = doc.get("profile") or {}
        current = list(profile.get("accessGroups") or [])
        app_owned = await self._app_owned_names()
        active = await self._active_groups_for_user(user_id)
        target = self._compute_target(current, app_owned, active)
        changed = set(target) != set(current)
        if changed and apply:
            await self.identities.update_one(
                {"_id": doc["_id"]},
                {"$set": {"profile.accessGroups": target, "modified": self.ctx.now()}},
            )
            await self.ctx.audit.record(
                actor=actor, action="projection.run", entity_type="user",
                entity_id=user_id, actor_kind="system" if actor == "system" else "user",
                summary=f"projected accessGroups for {user_id}",
                before={"accessGroups": current}, after={"accessGroups": target},
            )
        return changed, target

    async def project_users(self, user_ids: list[str], *, actor: str = "system") -> SyncResult:
        result = SyncResult(ranAt=self.ctx.now())
        for uid in user_ids:
            try:
                res = await self.project_user(uid, actor=actor)
                if res and res[0]:
                    result.usersUpdated += 1
            except Exception as exc:  # noqa: BLE001 - record and continue
                result.errors.append(f"{uid}: {exc}")
        await self._save_state("projection", result)
        return result

    async def project_group(self, group_name: str, *, actor: str = "system") -> SyncResult:
        cursor = self.ctx.app_db.memberships.find(
            {"groupName": group_name}, {"userId": 1, "_id": 0}
        )
        user_ids = list({doc["userId"] async for doc in cursor})
        return await self.project_users(user_ids, actor=actor)

    async def project_all(self, *, actor: str = "system") -> SyncResult:
        cursor = self.ctx.app_db.memberships.find({}, {"userId": 1, "_id": 0})
        user_ids = list({doc["userId"] async for doc in cursor})
        return await self.project_users(user_ids, actor=actor)

    async def _save_state(self, key: str, result: SyncResult) -> None:
        await self.ctx.app_db.sync_state.update_one(
            {"_id": key},
            {"$set": {"lastRunAt": result.ranAt, "lastResult": result.model_dump(mode="json")}},
            upsert=True,
        )

    async def last_status(self) -> SyncResult:
        doc = await self.ctx.app_db.sync_state.find_one({"_id": "projection"})
        if not doc:
            return SyncResult(ranAt=self.ctx.now())
        return SyncResult(**doc["lastResult"])
