"""Projection engine (T028).

Computes each user's effective access groups — the union of their currently-active
memberships in *active* (not retired) groups — and writes them into SciCat's
UserIdentity.profile.accessGroups.

Ownership invariant: the app only removes names it manages, i.e. every group in the
registry (any status) plus whatever it last projected onto that user
(`projection_state.lastProjected`, which keeps names of deleted groups removable). All
other strings (SciCat static values, roles, IdP-provided groups) are PRESERVED; divergence
is surfaced as drift, never silently deleted (research.md R2).

SciCat rewrites profile.accessGroups on every login (local/LDAP/OIDC strategies), so the
scheduler's login watcher and GET /me re-project. Writes are compare-and-set on the array
that was read, so a concurrent SciCat login write is never clobbered; we retry instead.
SciCat's `modified` timestamp is deliberately left alone: the login watcher keys on it.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from pydantic import BaseModel

from ..context import AppContext
from ..models.membership import compute_status
from ..models.resource_grant import GrantDriftItem


class DriftItem(BaseModel):
    userId: str
    expected: list[str]
    actual: list[str]


class SyncResult(BaseModel):
    ranAt: datetime
    usersUpdated: int = 0
    drift: list[DriftItem] = []
    grantDrift: list[GrantDriftItem] = []  # reconcile only
    errors: list[str] = []


class ProjectionConflict(RuntimeError):
    """The identity kept changing underneath us (e.g. repeated concurrent logins)."""


@dataclass
class Registry:
    """Snapshot of the group registry used for one projection pass."""

    names: set[str]  # every registered group, whatever its status
    active: set[str]  # groups that currently confer access


@dataclass
class UserPlan:
    identity_id: Any
    raw: list[str] | None  # profile.accessGroups exactly as stored (compare-and-set key)
    current: list[str]
    target: list[str]
    active: set[str]

    @property
    def changed(self) -> bool:
        return set(self.target) != set(self.current)


def identity_user_id(doc: dict[str, Any]) -> str:
    """The user key the app uses for a SciCat identity (matches DirectoryUser.userId)."""
    profile = doc.get("profile") or {}
    return str(doc.get("userId") or profile.get("id") or doc.get("_id"))


class ProjectionService:
    MAX_ATTEMPTS = 3

    def __init__(self, ctx: AppContext) -> None:
        self.ctx = ctx
        self.identities = ctx.scicat_db[ctx.settings.scicat_identity_collection]
        self.state = ctx.app_db.projection_state

    # ---- inputs ----

    async def registry(self) -> Registry:
        names: set[str] = set()
        active: set[str] = set()
        async for doc in self.ctx.app_db.groups.find({}, {"name": 1, "status": 1, "_id": 0}):
            names.add(doc["name"])
            if doc.get("status", "active") == "active":
                active.add(doc["name"])
        return Registry(names=names, active=active)

    async def _find_identity(self, user_id: str) -> dict[str, Any] | None:
        return await self.identities.find_one(
            {"$or": [{"userId": user_id}, {"profile.id": user_id}]}
        )

    async def _active_groups_for_user(self, user_id: str, registry: Registry) -> set[str]:
        now = self.ctx.now()
        active: set[str] = set()
        cursor = self.ctx.app_db.memberships.find({"userId": user_id}, {"_id": 0})
        async for doc in cursor:
            if doc["groupName"] not in registry.active:
                continue
            status = compute_status(
                doc.get("effectiveFrom"), doc.get("expiresAt"), now,
                ended=doc.get("status") == "revoked",
            )
            if status == "active":
                active.add(doc["groupName"])
        return active

    async def _last_projected(self, user_id: str) -> set[str]:
        doc = await self.state.find_one({"_id": user_id})
        return set((doc or {}).get("lastProjected") or [])

    async def _remember(self, user_id: str, active: set[str]) -> None:
        # Only users the app has ever projected onto need state; an empty set merely
        # clears existing state (avoids a document per user who ever logged in).
        await self.state.update_one(
            {"_id": user_id},
            {"$set": {"lastProjected": sorted(active), "at": self.ctx.now()}},
            upsert=bool(active),
        )

    @staticmethod
    def compute_target(current: list[str], removable: set[str], active: set[str]) -> list[str]:
        # keep everything the app does not manage, then add the user's active groups
        preserved = [g for g in current if g not in removable]
        return list(dict.fromkeys(preserved + sorted(active)))

    # ---- single user ----

    async def plan_user(self, user_id: str, registry: Registry | None = None) -> UserPlan | None:
        """What projecting this user would write (None if SciCat has no identity)."""
        registry = registry or await self.registry()
        doc = await self._find_identity(user_id)
        if not doc:
            return None
        raw = (doc.get("profile") or {}).get("accessGroups")
        current = list(raw or [])
        active = await self._active_groups_for_user(user_id, registry)
        removable = registry.names | await self._last_projected(user_id)
        target = self.compute_target(current, removable, active)
        return UserPlan(
            identity_id=doc["_id"], raw=raw, current=current, target=target, active=active
        )

    async def project_user(
        self,
        user_id: str,
        *,
        actor: str = "system",
        apply: bool = True,
        registry: Registry | None = None,
    ) -> tuple[bool, list[str]] | None:
        """Project one user; returns (changed, target) or None if no identity exists."""
        registry = registry or await self.registry()
        for _ in range(self.MAX_ATTEMPTS):
            plan = await self.plan_user(user_id, registry)
            if plan is None:
                return None
            if not plan.changed:
                if apply:
                    await self._remember(user_id, plan.active)
                return False, plan.current
            if not apply:
                return True, plan.target
            res = await self.identities.update_one(
                {"_id": plan.identity_id, "profile.accessGroups": plan.raw},
                {"$set": {"profile.accessGroups": plan.target}},
            )
            if not res.matched_count:
                continue  # SciCat (or another projection) wrote in between: re-plan
            await self._remember(user_id, plan.active)
            added = sorted(set(plan.target) - set(plan.current))
            removed = sorted(set(plan.current) - set(plan.target))
            await self.ctx.audit.record(
                actor=actor, action="projection.run", entity_type="user",
                entity_id=user_id, actor_kind="system" if actor == "system" else "user",
                summary=(
                    f"projected accessGroups for {user_id}"
                    + (f" +{','.join(added)}" if added else "")
                    + (f" -{','.join(removed)}" if removed else "")
                ),
                before={"accessGroups": plan.current}, after={"accessGroups": plan.target},
            )
            return True, plan.target
        raise ProjectionConflict(f"{user_id}: identity changed concurrently, retry later")

    # ---- many users ----

    async def project_users(
        self, user_ids: list[str] | set[str], *, actor: str = "system", save_state: bool = True
    ) -> SyncResult:
        result = SyncResult(ranAt=self.ctx.now())
        registry = await self.registry()
        for uid in sorted(set(user_ids)):
            try:
                res = await self.project_user(uid, actor=actor, registry=registry)
                if res and res[0]:
                    result.usersUpdated += 1
            except Exception as exc:  # noqa: BLE001 - record and continue
                result.errors.append(f"{uid}: {exc}")
        if save_state:
            await self._save_state("projection", result)
        return result

    async def holders(self, group_name: str) -> list[str]:
        """Users whose SciCat identity currently carries this group string."""
        cursor = self.identities.find(
            {"profile.accessGroups": group_name}, {"userId": 1, "profile.id": 1}
        )
        return sorted({identity_user_id(doc) async for doc in cursor})

    async def users_for_group(self, group_name: str) -> set[str]:
        """Everyone whose projection may involve this group: members in any state, users it
        was last projected onto, and current holders of the string."""
        users = {
            doc["userId"]
            async for doc in self.ctx.app_db.memberships.find(
                {"groupName": group_name}, {"userId": 1, "_id": 0}
            )
        }
        users |= {
            doc["_id"] async for doc in self.state.find({"lastProjected": group_name}, {"_id": 1})
        }
        users |= set(await self.holders(group_name))
        return users

    async def managed_user_ids(self, registry: Registry | None = None) -> set[str]:
        """Every user the app may need to correct: anyone with memberships, anyone it has
        projected onto, and any identity carrying a registered group name."""
        registry = registry or await self.registry()
        users = {
            doc["userId"]
            async for doc in self.ctx.app_db.memberships.find({}, {"userId": 1, "_id": 0})
        }
        users |= {doc["_id"] async for doc in self.state.find({}, {"_id": 1})}
        if registry.names:
            cursor = self.identities.find(
                {"profile.accessGroups": {"$in": sorted(registry.names)}},
                {"userId": 1, "profile.id": 1},
            )
            users |= {identity_user_id(doc) async for doc in cursor}
        return users

    async def project_group(self, group_name: str, *, actor: str = "system") -> SyncResult:
        return await self.project_users(await self.users_for_group(group_name), actor=actor)

    async def project_all(self, *, actor: str = "system") -> SyncResult:
        return await self.project_users(await self.managed_user_ids(), actor=actor)

    # ---- status ----

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
