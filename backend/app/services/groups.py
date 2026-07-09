"""Group CRUD + validation (T017)."""

from __future__ import annotations

from typing import Any

from ..context import AppContext
from ..models.group import Group, GroupCreate, GroupDetail, GroupUpdate


class GroupError(Exception):
    """Base for expected group errors (mapped to HTTP by the router)."""


class ReservedNameError(GroupError):
    pass


class DuplicateGroupError(GroupError):
    pass


class GroupInUseError(GroupError):
    pass


class GroupNotFoundError(GroupError):
    pass


class GroupService:
    def __init__(self, ctx: AppContext) -> None:
        self.ctx = ctx
        self.col = ctx.app_db.groups

    async def _username_exists(self, name: str) -> bool:
        matches = await self.ctx.directory.search(name, limit=10)
        return any(u.username.lower() == name.strip().lower() for u in matches)

    async def create(self, payload: GroupCreate, actor: str) -> Group:
        name = payload.name.strip()
        if self.ctx.settings.is_reserved(name):
            raise ReservedNameError(f"'{name}' is a reserved SciCat group")
        if await self.col.find_one({"name": name}):
            raise DuplicateGroupError(f"group '{name}' already exists")
        if await self._username_exists(name):
            raise ReservedNameError(f"'{name}' collides with a per-user group")

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
            summary=f"created group {name}", after=group.model_dump(mode="json"),
        )
        return group

    async def list(
        self, q: str | None = None, category: str | None = None, status: str | None = None
    ) -> list[Group]:
        query: dict[str, Any] = {}
        if q:
            query["$or"] = [
                {"name": {"$regex": q, "$options": "i"}},
                {"description": {"$regex": q, "$options": "i"}},
            ]
        if category:
            query["category"] = category
        if status:
            query["status"] = status
        cursor = self.col.find(query, {"_id": 0}).sort("name", 1)
        return [Group(**doc) async for doc in cursor]

    async def get(self, name: str) -> GroupDetail:
        doc = await self.col.find_one({"name": name}, {"_id": 0})
        if not doc:
            raise GroupNotFoundError(name)
        member_count = await self.ctx.app_db.memberships.count_documents(
            {"groupName": name, "status": {"$in": ["active", "scheduled"]}}
        )
        grant_count = await self.ctx.app_db.resource_grants.count_documents(
            {"groupName": name, "status": {"$in": ["active", "scheduled"]}}
        )
        return GroupDetail(**doc, memberCount=member_count, grantCount=grant_count)

    async def update(self, name: str, payload: GroupUpdate, actor: str) -> Group:
        doc = await self.col.find_one({"name": name}, {"_id": 0})
        if not doc:
            raise GroupNotFoundError(name)
        changes = {k: v for k, v in payload.model_dump().items() if v is not None}
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
        return Group(**updated)

    async def delete(self, name: str, actor: str, cascade: bool = False) -> None:
        doc = await self.col.find_one({"name": name}, {"_id": 0})
        if not doc:
            raise GroupNotFoundError(name)
        active_members = await self.ctx.app_db.memberships.count_documents(
            {"groupName": name, "status": {"$in": ["active", "scheduled"]}}
        )
        active_grants = await self.ctx.app_db.resource_grants.count_documents(
            {"groupName": name, "status": {"$in": ["active", "scheduled"]}}
        )
        rule_refs = await self.ctx.app_db.transfer_rules.count_documents(
            {"$or": [{"match.groupName": name}, {"successorType": "group", "successor": name}]}
        )
        if (active_members or active_grants or rule_refs) and not cascade:
            raise GroupInUseError(
                f"group '{name}' has {active_members} member(s), {active_grants} grant(s) and "
                f"{rule_refs} transfer-rule reference(s); use cascade=true to delete"
            )
        if cascade:
            await self.ctx.app_db.memberships.update_many(
                {"groupName": name, "status": {"$in": ["active", "scheduled"]}},
                {"$set": {"status": "revoked", "endedAt": self.ctx.now(), "endedBy": actor}},
            )
            await self.ctx.app_db.resource_grants.update_many(
                {"groupName": name, "status": {"$in": ["active", "scheduled"]}},
                {"$set": {"status": "removed"}},
            )
            await self.ctx.app_db.transfer_rules.delete_many(
                {"$or": [{"match.groupName": name}, {"successorType": "group", "successor": name}]}
            )
        await self.col.delete_one({"name": name})
        await self.ctx.audit.record(
            actor=actor, action="group.delete", entity_type="group", entity_id=name,
            summary=f"deleted group {name} (cascade={cascade})", before=doc,
        )
