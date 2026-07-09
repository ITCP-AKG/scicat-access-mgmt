"""Automatic ownership transfer (T044).

When a user departs (manual deactivation or expiry), their owned SciCat resources are
reassigned to a successor per the highest-priority matching TransferRule, and each
reassignment is logged as an idempotent TransferRecord. With no matching rule the
resources are flagged `pending_manual` rather than silently orphaned (FR-018–021,
SC-004). Idempotency: records are unique on (batchId, resourceType, resourceId); the
batchId is deterministic per (reason, user) so a re-run never double-applies.
"""

from __future__ import annotations

from typing import Any

from ..context import AppContext
from ..models.directory import DirectoryUser
from ..models.transfer import (
    TransferBatchResult,
    TransferRecord,
    TransferRule,
    TransferRuleCreate,
)
from ..services.scicat_client import RESOURCE_MAP, ScicatError

# Resource types that carry an ownerGroup worth transferring.
OWNED_RESOURCE_TYPES = ["dataset", "origdatablock", "proposal", "sample"]


class TransferError(Exception):
    pass


class TransferRuleNotFoundError(TransferError):
    pass


class TransferService:
    def __init__(self, ctx: AppContext) -> None:
        self.ctx = ctx
        self.rules = ctx.app_db.transfer_rules
        self.records = ctx.app_db.transfer_records

    # ---- Rule CRUD ----

    async def create_rule(self, payload: TransferRuleCreate, actor: str) -> TransferRule:
        rule = TransferRule(**payload.model_dump(), createdBy=actor)
        await self.rules.insert_one(rule.model_dump())
        await self.ctx.audit.record(
            actor=actor, action="transfer_rule.create", entity_type="transfer",
            entity_id=rule.id, summary=f"created transfer rule {rule.name}",
            after=rule.model_dump(mode="json"),
        )
        return rule

    async def list_rules(self) -> list[TransferRule]:
        cursor = self.rules.find({}, {"_id": 0}).sort("priority", 1)
        return [TransferRule(**doc) async for doc in cursor]

    async def update_rule(
        self, rule_id: str, payload: TransferRuleCreate, actor: str
    ) -> TransferRule:
        doc = await self.rules.find_one({"id": rule_id}, {"_id": 0})
        if not doc:
            raise TransferRuleNotFoundError(rule_id)
        changes = payload.model_dump()
        await self.rules.update_one({"id": rule_id}, {"$set": changes})
        merged = {**doc, **changes}
        await self.ctx.audit.record(
            actor=actor, action="transfer_rule.update", entity_type="transfer",
            entity_id=rule_id, summary=f"updated transfer rule {merged.get('name')}",
            before=doc, after=merged,
        )
        return TransferRule(**merged)

    async def delete_rule(self, rule_id: str, actor: str) -> None:
        doc = await self.rules.find_one({"id": rule_id}, {"_id": 0})
        if not doc:
            raise TransferRuleNotFoundError(rule_id)
        await self.rules.delete_one({"id": rule_id})
        await self.ctx.audit.record(
            actor=actor, action="transfer_rule.delete", entity_type="transfer",
            entity_id=rule_id, summary=f"deleted transfer rule {doc.get('name')}", before=doc,
        )

    async def list_records(
        self, from_user_id: str | None = None, outcome: str | None = None
    ) -> list[TransferRecord]:
        query: dict[str, Any] = {}
        if from_user_id:
            query["fromUserId"] = from_user_id
        if outcome:
            query["outcome"] = outcome
        cursor = self.records.find(query, {"_id": 0}).sort("at", -1)
        return [TransferRecord(**doc) async for doc in cursor]

    # ---- Rule matching ----

    async def _match_rule(self, user: DirectoryUser) -> TransferRule | None:
        rules = await self.list_rules()  # already priority-ordered
        for rule in rules:
            if not rule.enabled:
                continue
            m = rule.match
            if m.userId and m.userId != user.userId:
                continue
            if m.groupName and m.groupName not in user.accessGroups:
                continue
            if m.category and not await self._user_in_category(user, m.category):
                continue
            return rule
        return None

    async def _user_in_category(self, user: DirectoryUser, category: str) -> bool:
        names = await self._app_owned_names()
        member = self.ctx.app_db.groups.find(
            {"category": category, "name": {"$in": list(names & set(user.accessGroups))}},
            {"name": 1, "_id": 0},
        )
        async for _ in member:
            return True
        return False

    async def _app_owned_names(self) -> set[str]:
        cursor = self.ctx.app_db.groups.find({}, {"name": 1, "_id": 0})
        return {doc["name"] async for doc in cursor}

    async def _personal_groups(self, user: DirectoryUser) -> list[str]:
        """The user's own (non app-managed, non-reserved) access groups — the strings a
        SciCat resource uses as ownerGroup for that individual."""
        app_owned = await self._app_owned_names()
        return [
            g
            for g in user.accessGroups
            if g not in app_owned and not self.ctx.settings.is_reserved(g)
        ]

    # ---- Enumeration + reassignment ----

    async def _owned_resources(self, user: DirectoryUser) -> list[tuple[str, dict]]:
        """Resources owned by the user, keyed by ownerGroup (personal groups) or
        ownerEmail. De-duplicated on (resourceType, resourceId)."""
        seen: set[tuple[str, str]] = set()
        found: list[tuple[str, dict]] = []
        filters: list[dict[str, Any]] = [{"ownerGroup": g} for g in await self._personal_groups(user)]
        if user.email:
            filters.append({"ownerEmail": user.email})
        for resource_type in OWNED_RESOURCE_TYPES:
            id_field = RESOURCE_MAP[resource_type][1]
            for filter_ in filters:
                try:
                    docs = await self.ctx.scicat.list_resources(resource_type, filter_, limit=500)
                except ScicatError:
                    continue
                for doc in docs:
                    rid = str(doc.get(id_field, ""))
                    key = (resource_type, rid)
                    if rid and key not in seen:
                        seen.add(key)
                        found.append((resource_type, doc))
        return found

    async def _resolve_new_owner(self, rule: TransferRule) -> tuple[str, str | None, str | None]:
        """Return (newOwnerGroup, newOwner, newOwnerEmail) for the rule's successor."""
        if rule.successorType == "group":
            return rule.successor, None, None
        successor = await self.ctx.directory.get(rule.successor)
        if not successor:
            return rule.successor, None, None
        personal = await self._personal_groups(successor)
        owner_group = personal[0] if personal else successor.username or rule.successor
        owner = successor.username if rule.transferOwner else None
        owner_email = successor.email if rule.transferOwner else None
        return owner_group, owner, owner_email

    async def transfer_for_user(
        self, user_id: str, *, reason: str = "departure", actor: str = "system"
    ) -> TransferBatchResult:
        user = await self.ctx.directory.get(user_id)
        if not user:
            user = DirectoryUser(userId=user_id)
        batch_id = f"{reason}:{user_id}"
        rule = await self._match_rule(user)
        new_group = new_owner = new_email = None
        if rule:
            new_group, new_owner, new_email = await self._resolve_new_owner(rule)

        result = TransferBatchResult(batchId=batch_id)
        for resource_type, doc in await self._owned_resources(user):
            id_field = RESOURCE_MAP[resource_type][1]
            resource_id = str(doc.get(id_field, ""))
            # Idempotency guard: skip a (batch, resource) already recorded.
            if await self.records.find_one(
                {"batchId": batch_id, "resourceType": resource_type, "resourceId": resource_id}
            ):
                continue
            record = await self._reassign_one(
                user, batch_id, reason, actor, resource_type, resource_id, doc,
                rule, new_group, new_owner, new_email,
            )
            result.records.append(record)
        return result

    async def _reassign_one(
        self, user, batch_id, reason, actor, resource_type, resource_id, doc,
        rule, new_group, new_owner, new_email,
    ) -> TransferRecord:
        previous_owner_group = doc.get("ownerGroup") or ""
        previous_owner = doc.get("owner")

        if rule is None:
            record = TransferRecord(
                batchId=batch_id, triggerReason=reason, fromUserId=user.userId,
                resourceType=resource_type, resourceId=resource_id,
                previousOwnerGroup=previous_owner_group, previousOwner=previous_owner,
                outcome="pending_manual", by=actor,
            )
        else:
            body: dict[str, Any] = {"ownerGroup": new_group}
            if rule.transferOwner and rule.successorType == "user":
                if new_owner:
                    body["owner"] = new_owner
                if new_email:
                    body["ownerEmail"] = new_email
            try:
                await self.ctx.scicat.patch_resource(resource_type, resource_id, body)
                outcome, error = "transferred", None
            except ScicatError as exc:
                outcome, error = "failed", str(exc)
            record = TransferRecord(
                batchId=batch_id, triggerReason=reason, fromUserId=user.userId,
                resourceType=resource_type, resourceId=resource_id,
                previousOwnerGroup=previous_owner_group, previousOwner=previous_owner,
                newOwnerGroup=new_group or "", newOwner=new_owner,
                ruleId=rule.id, outcome=outcome, error=error, by=actor,
            )

        await self.records.insert_one(record.model_dump())
        await self.ctx.audit.record(
            actor=actor, action="transfer.execute", entity_type="transfer",
            entity_id=record.id, actor_kind="system" if actor == "system" else "user",
            summary=(
                f"{record.outcome} {resource_type}/{resource_id} from {user.userId}"
                + (f" to {new_group}" if new_group else " (no rule)")
            ),
            after=record.model_dump(mode="json"),
        )
        return record
