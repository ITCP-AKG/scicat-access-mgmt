"""Membership management (T023).

On every membership change the affected user's effective access is re-projected into
SciCat so authorization reflects the app state immediately (US3 integration).
"""

from __future__ import annotations

import logging
from typing import Any

from pymongo.errors import DuplicateKeyError

from ..context import AppContext
from ..models.membership import (
    Membership,
    MembershipCreate,
    MembershipUpdate,
    compute_status,
)
from ..util import window_error
from .projection import ProjectionService

logger = logging.getLogger(__name__)


class MembershipError(Exception):
    pass


class GroupMissingError(MembershipError):
    pass


class UserMissingError(MembershipError):
    pass


class DuplicateMembershipError(MembershipError):
    pass


class LastAdminError(MembershipError):
    pass


class MembershipNotFoundError(MembershipError):
    pass


class InvalidWindowError(MembershipError):
    pass


class MembershipEndedError(MembershipError):
    pass


async def reactivate(ctx: AppContext, user_id: str, actor: str, summary: str) -> bool:
    """Clear a departure: the user re-joined a group or became a manager."""
    if not await ctx.app_db.departed_users.find_one_and_delete({"_id": user_id}):
        return False
    await ctx.audit.record(
        actor=actor, action="user.reactivate", entity_type="user", entity_id=user_id,
        summary=summary,
    )
    return True


class MembershipService:
    def __init__(self, ctx: AppContext) -> None:
        self.ctx = ctx
        self.col = ctx.app_db.memberships
        self.projection = ProjectionService(ctx)

    def _refresh_status(self, doc: dict) -> dict:
        doc = dict(doc)
        doc["status"] = compute_status(
            doc.get("effectiveFrom"), doc.get("expiresAt"), self.ctx.now(),
            ended=doc.get("status") == "revoked",
        )
        return doc

    async def add(self, group_name: str, payload: MembershipCreate, actor: str) -> Membership:
        group = await self.ctx.app_db.groups.find_one({"name": group_name})
        if not group:
            raise GroupMissingError(group_name)
        if group.get("status") == "retired":
            raise GroupMissingError(f"group '{group_name}' is retired")

        user = await self.ctx.directory.get(payload.userId)
        if not user:
            raise UserMissingError(payload.userId)

        now = self.ctx.now()
        error = window_error(payload.effectiveFrom, payload.expiresAt, now)
        if error:
            raise InvalidWindowError(error)

        # An open membership blocks a new one — unless it has lapsed and the sweep has not
        # materialised that yet, in which case record the expiry now.
        cursor = self.col.find(
            {"groupName": group_name, "userId": payload.userId,
             "status": {"$in": ["active", "scheduled"]}},
            {"_id": 0},
        )
        async for existing in cursor:
            state = compute_status(existing.get("effectiveFrom"), existing.get("expiresAt"), now)
            if state != "expired":
                raise DuplicateMembershipError(
                    f"{payload.userId} already a member of {group_name}"
                )
            await self.col.update_one(
                {"id": existing["id"]},
                {"$set": {"status": "expired", "endedAt": now, "endedBy": "system"}},
            )

        status = compute_status(payload.effectiveFrom, payload.expiresAt, now)
        membership = Membership(
            groupName=group_name,
            userId=payload.userId,
            userDisplay=user.displayName,
            effectiveFrom=payload.effectiveFrom,
            expiresAt=payload.expiresAt,
            status=status,
            addedBy=actor,
        )
        try:
            await self.col.insert_one(membership.model_dump())
        except DuplicateKeyError as exc:  # concurrent add of the same user
            raise DuplicateMembershipError(
                f"{payload.userId} already a member of {group_name}"
            ) from exc
        await self.ctx.audit.record(
            actor=actor, action="membership.add", entity_type="membership",
            entity_id=membership.id,
            summary=f"added {payload.userId} to {group_name}",
            after=membership.model_dump(mode="json"),
        )
        await reactivate(
            self.ctx, payload.userId, actor, f"{payload.userId} re-joined via {group_name}"
        )
        await self.projection.project_user(payload.userId, actor=actor)
        return membership

    async def get(self, membership_id: str) -> Membership:
        doc = await self.col.find_one({"id": membership_id}, {"_id": 0})
        if not doc:
            raise MembershipNotFoundError(membership_id)
        return Membership(**self._refresh_status(doc))

    async def list_for_group(self, group_name: str) -> list[Membership]:
        cursor = self.col.find({"groupName": group_name}, {"_id": 0})
        return [Membership(**self._refresh_status(doc)) async for doc in cursor]

    async def list_for_user(self, user_id: str) -> list[Membership]:
        cursor = self.col.find({"userId": user_id}, {"_id": 0})
        return [Membership(**self._refresh_status(doc)) async for doc in cursor]

    async def update(self, membership_id: str, payload: MembershipUpdate, actor: str) -> Membership:
        doc = await self.col.find_one({"id": membership_id}, {"_id": 0})
        if not doc:
            raise MembershipNotFoundError(membership_id)
        now = self.ctx.now()
        current = self._refresh_status(doc)["status"]
        if current in ("revoked", "expired"):
            raise MembershipEndedError(
                f"membership {membership_id} has ended ({current}); add the user again instead"
            )
        changes = payload.model_dump(exclude_unset=True)
        merged = {**doc, **changes}
        error = window_error(merged.get("effectiveFrom"), merged.get("expiresAt"), now)
        if error:
            raise InvalidWindowError(error)
        merged["status"] = compute_status(merged.get("effectiveFrom"), merged.get("expiresAt"), now)
        await self.col.update_one(
            {"id": membership_id}, {"$set": {**changes, "status": merged["status"]}}
        )
        await self.ctx.audit.record(
            actor=actor, action="membership.update", entity_type="membership",
            entity_id=membership_id, summary=f"updated membership {membership_id}",
            before=doc, after=merged,
        )
        await self.projection.project_user(doc["userId"], actor=actor)
        return Membership(**merged)

    async def revoke(self, membership_id: str, actor: str) -> None:
        doc = await self.col.find_one({"id": membership_id}, {"_id": 0})
        if not doc:
            raise MembershipNotFoundError(membership_id)
        await self._guard_last_admin(doc)
        await self.col.update_one(
            {"id": membership_id},
            {"$set": {"status": "revoked", "endedAt": self.ctx.now(), "endedBy": actor}},
        )
        await self.ctx.audit.record(
            actor=actor, action="membership.revoke", entity_type="membership",
            entity_id=membership_id,
            summary=f"revoked {doc['userId']} from {doc['groupName']}", before=doc,
        )
        await self.projection.project_user(doc["userId"], actor=actor)

    async def sweep(self, actor: str = "system") -> dict[str, Any]:
        """Materialise membership temporal transitions and re-project (US5).

        scheduled→active and active→expired are applied to the stored status, then
        every affected user is re-projected so SciCat reflects the change. Idempotent:
        only memberships whose computed status differs from their stored status change.
        """
        now = self.ctx.now()
        activated = expired = 0
        affected: set[str] = set()
        expired_groups: dict[str, set[str]] = {}
        cursor = self.col.find({"status": {"$in": ["active", "scheduled"]}}, {"_id": 0})
        docs = [doc async for doc in cursor]
        for doc in docs:
            new_status = compute_status(doc.get("effectiveFrom"), doc.get("expiresAt"), now)
            if new_status == doc["status"]:
                continue
            if doc["status"] == "scheduled" and new_status == "active":
                await self.col.update_one({"id": doc["id"]}, {"$set": {"status": "active"}})
                await self.ctx.audit.record(
                    actor=actor, action="membership.activate", entity_type="membership",
                    entity_id=doc["id"], actor_kind="system",
                    summary=f"activated {doc['userId']} in {doc['groupName']}",
                )
                affected.add(doc["userId"])
                activated += 1
            elif new_status == "expired":
                await self.col.update_one(
                    {"id": doc["id"]},
                    {"$set": {"status": "expired", "endedAt": now, "endedBy": actor}},
                )
                await self.ctx.audit.record(
                    actor=actor, action="membership.expire", entity_type="membership",
                    entity_id=doc["id"], actor_kind="system",
                    summary=f"expired {doc['userId']} from {doc['groupName']}",
                )
                affected.add(doc["userId"])
                expired_groups.setdefault(doc["userId"], set()).add(doc["groupName"])
                expired += 1
        projected = await self.projection.project_users(affected, actor=actor, save_state=False)
        return {
            "membershipsActivated": activated,
            "membershipsExpired": expired,
            "usersReprojected": len(affected),
            "projectionErrors": projected.errors,
            # for expiry-triggered transfers: which groups each user just lost
            "expiredGroupsByUser": {u: sorted(g) for u, g in expired_groups.items()},
        }

    async def end_all_for_user(self, user_id: str, actor: str) -> list[str]:
        """End every open membership of a departing user and re-project them.

        Returns the groups they belonged to (transfer rules are matched against these).
        """
        now = self.ctx.now()
        groups: set[str] = set()
        cursor = self.col.find({"userId": user_id, "status": {"$in": ["active", "scheduled"]}},
                               {"_id": 0})
        for doc in [d async for d in cursor]:
            await self.col.update_one(
                {"id": doc["id"]},
                {"$set": {"status": "revoked", "endedAt": now, "endedBy": actor}},
            )
            await self.ctx.audit.record(
                actor=actor, action="membership.revoke", entity_type="membership",
                entity_id=doc["id"],
                summary=f"revoked {user_id} from {doc['groupName']} (departure)", before=doc,
            )
            groups.add(doc["groupName"])
        try:
            await self.projection.project_user(user_id, actor=actor)
        except Exception:  # noqa: BLE001 - memberships are ended; login watch/reconcile fix it
            logger.exception("projection after departure of %s failed", user_id)
        return sorted(groups)

    async def _guard_last_admin(self, doc: dict) -> None:
        """Prevent removing the last active member of a configured admin group (FR-026)."""
        if doc["groupName"] not in self.ctx.settings.admin_groups:
            return
        active = await self.col.count_documents(
            {"groupName": doc["groupName"], "status": {"$in": ["active", "scheduled"]}}
        )
        if active <= 1:
            raise LastAdminError(
                f"cannot remove the last member of admin group '{doc['groupName']}'"
            )
