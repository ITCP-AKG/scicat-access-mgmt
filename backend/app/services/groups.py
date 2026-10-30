"""Group CRUD + validation (T017)."""

from __future__ import annotations

import re
from typing import Any

from ..context import AppContext
from ..models.group import Group, GroupCreate, GroupDetail, GroupUpdate
from ..models.membership import MembershipCreate
from .grants import GrantService
from .memberships import MembershipService, reactivate
from .projection import ProjectionService

# Group names travel as URL path segments and SciCat group strings: keep them simple.
NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@+-]{0,63}$")
_OPEN = {"$in": ["active", "scheduled"]}


class GroupError(Exception):
    """Base for expected group errors (mapped to HTTP by the router)."""


class ReservedNameError(GroupError):
    pass


class InvalidGroupError(GroupError):
    """Malformed name or unknown manager (HTTP 422)."""


class DuplicateGroupError(GroupError):
    pass


class HoldersExistError(GroupError):
    """SciCat identities already carry the name; the admin must decide what happens."""


class GroupInUseError(GroupError):
    pass


class GroupNotFoundError(GroupError):
    pass


class GroupService:
    def __init__(self, ctx: AppContext) -> None:
        self.ctx = ctx
        self.col = ctx.app_db.groups
        self.projection = ProjectionService(ctx)

    async def _validate_managers(self, managers: list[str]) -> None:
        unknown = [m for m in managers if not await self.ctx.directory.get(m)]
        if unknown:
            raise InvalidGroupError(f"unknown manager user id(s): {', '.join(unknown)}")

    async def name_check(self, name: str) -> dict[str, Any]:
        """Preflight for the create dialog."""
        name = name.strip()
        return {
            "name": name,
            "valid": bool(NAME_RE.match(name)),
            "reserved": self.ctx.settings.is_reserved(name),
            "exists": await self.col.find_one({"name": name}, {"_id": 1}) is not None,
            "collidesWithUser": bool(name) and await self.ctx.directory.username_exists(name),
            "holders": len(await self.projection.holders(name)) if name else 0,
        }

    async def create(self, payload: GroupCreate, actor: str) -> Group:
        name = payload.name.strip()
        if self.ctx.settings.is_reserved(name):
            raise ReservedNameError(f"'{name}' is a reserved SciCat group")
        if not NAME_RE.match(name):
            raise InvalidGroupError(
                "group names must start with a letter or digit and contain only letters, "
                "digits and . _ : @ + - (max 64 characters)"
            )
        if await self.col.find_one({"name": name}):
            raise DuplicateGroupError(f"group '{name}' already exists")
        if await self.ctx.directory.username_exists(name):
            raise ReservedNameError(f"'{name}' collides with a per-user group")
        await self._validate_managers(payload.managers)

        # Once registered, the name is app-managed: projection removes it from everyone who
        # is not a member. Never let that happen silently to existing holders.
        holders = await self.projection.holders(name)
        if holders and payload.importHolders is None:
            raise HoldersExistError(
                f"{len(holders)} user(s) already carry '{name}' in SciCat; set "
                "importHolders=true to adopt them as members, or false to remove it from them"
            )

        group = Group(
            name=name,
            description=payload.description,
            category=payload.category,
            managers=payload.managers,
            createdBy=actor,
            modifiedBy=actor,
        )
        await self.col.insert_one(group.model_dump())
        await self.ctx.audit.record(
            actor=actor, action="group.create", entity_type="group", entity_id=name,
            summary=f"created group {name}" + (
                f" (importHolders={payload.importHolders}, {len(holders)} holder(s))"
                if holders else ""
            ),
            after=group.model_dump(mode="json"),
        )
        if holders:
            if payload.importHolders:
                memberships = MembershipService(self.ctx)
                for uid in holders:
                    await memberships.add(name, MembershipCreate(userId=uid), actor=actor)
            else:
                await self.projection.project_users(holders, actor=actor)
        if payload.managers:
            # managers get member access (and a departed user made manager is back)
            for m in payload.managers:
                await reactivate(self.ctx, m, actor, f"{m} re-joined as manager of {name}")
            await self.projection.project_users(payload.managers, actor=actor)
        return group

    async def list(
        self, q: str | None = None, category: str | None = None, status: str | None = None
    ) -> list[Group]:
        query: dict[str, Any] = {}
        if q:
            rx = {"$regex": re.escape(q), "$options": "i"}
            query["$or"] = [{"name": rx}, {"description": rx}]
        if category:
            query["category"] = category
        if status:
            query["status"] = status
        cursor = self.col.find(query, {"_id": 0}).sort("name", 1)
        return [Group(**doc) async for doc in cursor]

    def _rule_refs(self, name: str) -> dict[str, Any]:
        return {"$or": [{"match.groupName": name}, {"successorType": "group", "successor": name}]}

    async def get(self, name: str) -> GroupDetail:
        doc = await self.col.find_one({"name": name}, {"_id": 0})
        if not doc:
            raise GroupNotFoundError(name)
        app_db = self.ctx.app_db
        return GroupDetail(
            **doc,
            memberCount=await app_db.memberships.count_documents(
                {"groupName": name, "status": _OPEN}
            ),
            grantCount=await app_db.resource_grants.count_documents(
                {"groupName": name, "status": _OPEN, "parentGrantId": None}
            ),
            transferRuleCount=await app_db.transfer_rules.count_documents(self._rule_refs(name)),
        )

    async def update(self, name: str, payload: GroupUpdate, actor: str) -> Group:
        doc = await self.col.find_one({"name": name}, {"_id": 0})
        if not doc:
            raise GroupNotFoundError(name)
        changes = {k: v for k, v in payload.model_dump().items() if v is not None}
        if "managers" in changes:
            await self._validate_managers(changes["managers"])
        status_changed = "status" in changes and changes["status"] != doc.get("status", "active")
        if changes:
            changes["modifiedBy"] = actor
            changes["modifiedAt"] = self.ctx.now()
            await self.col.update_one({"name": name}, {"$set": changes})
        updated = await self.col.find_one({"name": name}, {"_id": 0})
        await self.ctx.audit.record(
            actor=actor, action="group.update", entity_type="group", entity_id=name,
            summary=f"updated group {name}", before=Group(**doc).model_dump(mode="json"),
            after=Group(**updated).model_dump(mode="json"),
        )
        if status_changed:
            # retired groups confer nothing; re-activation restores members' access
            # (users_for_group covers the current managers)
            await self.projection.project_group(name, actor=actor)
        if "managers" in changes:
            # managers get member access: grant it to new ones, withdraw it from removed ones
            previous = set(doc.get("managers") or [])
            for m in sorted(set(changes["managers"]) - previous):
                await reactivate(self.ctx, m, actor, f"{m} re-joined as manager of {name}")
            changed = previous ^ set(changes["managers"])
            if changed:
                await self.projection.project_users(changed, actor=actor)
        return Group(**updated)

    async def drop_manager(self, user_id: str, username: str, actor: str) -> list[str]:
        """Remove a user from every group's managers (departure); returns those groups.
        The caller re-projects the user."""
        ids = [i for i in (user_id, username) if i]
        names = [
            doc["name"]
            async for doc in self.col.find({"managers": {"$in": ids}}, {"name": 1, "_id": 0})
        ]
        for name in names:
            doc = await self.col.find_one({"name": name}, {"_id": 0})
            managers = [m for m in doc.get("managers") or [] if m not in ids]
            await self.col.update_one(
                {"name": name},
                {"$set": {"managers": managers, "modifiedBy": actor, "modifiedAt": self.ctx.now()}},
            )
            await self.ctx.audit.record(
                actor=actor, action="group.update", entity_type="group", entity_id=name,
                summary=f"removed departing manager {user_id} from {name}",
                before={"managers": doc.get("managers") or []}, after={"managers": managers},
            )
        return names

    async def delete(self, name: str, actor: str, cascade: bool = False) -> None:
        doc = await self.col.find_one({"name": name}, {"_id": 0})
        if not doc:
            raise GroupNotFoundError(name)
        app_db = self.ctx.app_db
        active_members = await app_db.memberships.count_documents(
            {"groupName": name, "status": _OPEN}
        )
        # top-level grants: removing a project grant ends its children
        open_grants = [
            g["id"]
            async for g in app_db.resource_grants.find(
                {"groupName": name, "status": _OPEN, "parentGrantId": None}, {"id": 1, "_id": 0}
            )
        ]
        rule_refs = await app_db.transfer_rules.count_documents(self._rule_refs(name))
        if (active_members or open_grants or rule_refs) and not cascade:
            raise GroupInUseError(
                f"group '{name}' has {active_members} member(s), {len(open_grants)} grant(s) and "
                f"{rule_refs} transfer-rule reference(s); use cascade=true to delete"
            )
        if cascade:
            # withdraw the group from SciCat resources (failures stay pending for the sweep)
            grants = GrantService(self.ctx)
            for grant_id in open_grants:
                await grants.remove(grant_id, actor=actor)
            await app_db.memberships.update_many(
                {"groupName": name, "status": _OPEN},
                {"$set": {"status": "revoked", "endedAt": self.ctx.now(), "endedBy": actor}},
            )
            await app_db.transfer_rules.delete_many(self._rule_refs(name))

        # Re-project while the name is still registered (hence removable) so it leaves
        # every identity, including holders the app never projected onto. Managers are
        # collected first and then cleared, so they lose their member access too.
        users = await self.projection.users_for_group(name)
        await self.col.update_one({"name": name}, {"$set": {"managers": []}})
        result = await self.projection.project_users(users, actor=actor)
        await self.col.delete_one({"name": name})
        await self.ctx.audit.record(
            actor=actor, action="group.delete", entity_type="group", entity_id=name,
            summary=(
                f"deleted group {name} (cascade={cascade}); {result.usersUpdated} user(s) "
                f"re-projected"
                + (f", {len(result.errors)} projection error(s)" if result.errors else "")
            ),
            before=doc,
        )
