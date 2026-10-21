"""Automatic ownership transfer (T044).

When a user departs (manual deactivation, or expiry of their last membership), the SciCat
resources *they personally* own are handed to a successor per the highest-priority
matching TransferRule (FR-018–021, SC-004). A resource is the user's when

- its ownerGroup is the user's personal group (`PERSONAL_GROUP_TEMPLATE`, e.g.
  "u.{username}"; empty disables this), or
- a contact field names them (dataset ownerEmail/contactEmail, proposal email/pi_email —
  matched on email — or a sample's `owner` username).

Data owned by shared/project groups stays with its group; only the matched fields of a
resource are changed. Without a matching rule nothing is changed and the resource is
flagged `pending_manual` rather than silently orphaned.

Each trigger is a Departure whose id is the batchId of its records. Re-running a batch
(retry) re-evaluates what the user still owns with the current rules: failed and pending
records are updated in place, those fixed by hand meanwhile become `resolved`, and
completed transfers are left alone — so retries never double-apply (FR-021, SC-008).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from ..context import AppContext
from ..models.directory import DirectoryUser
from ..models.transfer import (
    Departure,
    TransferBatchResult,
    TransferRecord,
    TransferRule,
    TransferRuleCreate,
)
from ..services.scicat_client import ScicatError, resource_id
from ..util import new_id
from .groups import NAME_RE

# Resource types that carry an ownerGroup worth transferring.
OWNED_RESOURCE_TYPES = ["dataset", "origdatablock", "proposal", "sample"]


@dataclass(frozen=True)
class ContactSlot:
    """Fields naming a person on a resource, matched by email (case-insensitive) or, for
    `by_username` slots, by the username stored in `name`."""

    email: str | None = None
    name: str | None = None  # full name, or a username when by_username
    first: str | None = None
    last: str | None = None
    by_username: bool = False


# Verified against the SciCat v4.3.1 update DTOs. The first slot is the owner: it is also
# handed over when a resource moves away from the user's personal group. catorga stores the
# creator's username in dataset/sample `owner` (and their email in contactEmail).
CONTACT_SLOTS: dict[str, list[ContactSlot]] = {
    "dataset": [
        ContactSlot(name="owner", by_username=True),
        ContactSlot(email="ownerEmail"),
        ContactSlot(email="contactEmail"),
    ],
    "proposal": [
        ContactSlot(email="email", first="firstname", last="lastname"),
        ContactSlot(email="pi_email", first="pi_firstname", last="pi_lastname"),
    ],
    "sample": [ContactSlot(name="owner", by_username=True)],
    "origdatablock": [],
}


class TransferError(Exception):
    pass


class TransferRuleNotFoundError(TransferError):
    pass


class TransferBatchNotFoundError(TransferError):
    pass


class InvalidTransferRuleError(TransferError):
    pass


@dataclass
class _Successor:
    group: str | None = None  # new ownerGroup for personal-group resources
    person: DirectoryUser | None = None  # receives contact fields (None: not handed over)
    error: str | None = None


@dataclass
class _Plan:
    changes: dict[str, Any] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)
    error: str | None = None


def _same_email(a: Any, b: str) -> bool:
    return bool(a) and bool(b) and str(a).strip().lower() == b.strip().lower()


def _slot_matches(slot: ContactSlot, doc: dict[str, Any], user: DirectoryUser) -> bool:
    if slot.by_username:
        return bool(user.username) and doc.get(slot.name) == user.username
    return slot.email is not None and _same_email(doc.get(slot.email), user.email)


def _slot_values(slot: ContactSlot, person: DirectoryUser) -> tuple[dict[str, Any], list[str]]:
    values: dict[str, Any] = {}
    notes: list[str] = []
    full_name = person.displayName or person.username
    if slot.email:
        if person.email:
            values[slot.email] = person.email
        else:
            notes.append(f"successor has no email; {slot.email} left unchanged")
    if slot.name:
        value = person.username if slot.by_username else full_name
        if value:
            values[slot.name] = value
    if (slot.first or slot.last) and full_name:
        parts = full_name.split()
        if slot.first:
            values[slot.first] = " ".join(parts[:-1]) or parts[0]
        if slot.last and len(parts) > 1:
            values[slot.last] = parts[-1]
    return values, notes


class TransferService:
    def __init__(self, ctx: AppContext) -> None:
        self.ctx = ctx
        self.rules = ctx.app_db.transfer_rules
        self.records = ctx.app_db.transfer_records
        self.departures = ctx.app_db.departures

    # ---- Rule CRUD ----

    async def _validate_rule(self, payload: TransferRuleCreate) -> None:
        if payload.successorType == "group":
            name = payload.successor.strip()
            if self.ctx.settings.is_reserved(name) or not NAME_RE.match(name):
                raise InvalidTransferRuleError(f"'{name}' is not a valid successor group")
        elif not await self.ctx.directory.get(payload.successor):
            raise InvalidTransferRuleError(f"successor user '{payload.successor}' not found")

    async def create_rule(self, payload: TransferRuleCreate, actor: str) -> TransferRule:
        await self._validate_rule(payload)
        rule = TransferRule(**payload.model_dump(), createdBy=actor)
        await self.rules.insert_one(rule.model_dump())
        await self.ctx.audit.record(
            actor=actor, action="transfer_rule.create", entity_type="transfer",
            entity_id=rule.id, summary=f"created transfer rule {rule.name}",
            after=rule.model_dump(mode="json"),
        )
        return rule

    async def list_rules(self) -> list[TransferRule]:
        cursor = self.rules.find({}, {"_id": 0}).sort([("priority", 1), ("createdAt", 1)])
        return [TransferRule(**doc) async for doc in cursor]

    async def update_rule(
        self, rule_id: str, payload: TransferRuleCreate, actor: str
    ) -> TransferRule:
        doc = await self.rules.find_one({"id": rule_id}, {"_id": 0})
        if not doc:
            raise TransferRuleNotFoundError(rule_id)
        await self._validate_rule(payload)
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
        self,
        from_user_id: str | None = None,
        outcome: str | None = None,
        batch_id: str | None = None,
    ) -> list[TransferRecord]:
        query: dict[str, Any] = {}
        if from_user_id:
            query["fromUserId"] = from_user_id
        if outcome:
            query["outcome"] = outcome
        if batch_id:
            query["batchId"] = batch_id
        cursor = self.records.find(query, {"_id": 0}).sort("at", -1)
        return [TransferRecord(**doc) async for doc in cursor]

    async def list_departures(self, user_id: str | None = None) -> list[Departure]:
        query = {"userId": user_id} if user_id else {}
        cursor = self.departures.find(query, {"_id": 0}).sort("at", -1)
        return [Departure(**doc) async for doc in cursor]

    # ---- Rule matching ----

    async def _match_rule(self, user: DirectoryUser, groups: list[str]) -> TransferRule | None:
        """First enabled rule (by priority) matching the user and the groups they belonged
        to when leaving — not their current SciCat groups, which projection has already
        stripped by then."""
        categories = {
            doc.get("category")
            async for doc in self.ctx.app_db.groups.find(
                {"name": {"$in": groups}}, {"category": 1, "_id": 0}
            )
        }
        for rule in await self.list_rules():
            if not rule.enabled:
                continue
            m = rule.match
            if m.userId and m.userId != user.userId:
                continue
            if m.groupName and m.groupName not in groups:
                continue
            if m.category and m.category not in categories:
                continue
            return rule
        return None

    def _personal_group(self, user: DirectoryUser) -> str | None:
        template = self.ctx.settings.personal_group_template
        if not template or not user.username:
            return None
        return template.replace("{username}", user.username)

    async def _resolve_successor(self, rule: TransferRule) -> _Successor:
        if rule.successorType == "group":
            return _Successor(group=rule.successor)
        person = await self.ctx.directory.get(rule.successor)
        if person is None:
            return _Successor(error=f"successor user '{rule.successor}' not found")
        return _Successor(
            group=self._personal_group(person), person=person if rule.transferOwner else None
        )

    # ---- Enumeration + planning ----

    def _ownership_query(
        self, resource_type: str, user: DirectoryUser, personal: str | None
    ) -> dict[str, Any] | None:
        clauses: list[dict[str, Any]] = []
        if personal:
            clauses.append({"ownerGroup": personal})
        for slot in CONTACT_SLOTS[resource_type]:
            if slot.by_username:
                if user.username:
                    clauses.append({slot.name: user.username})
            elif slot.email and user.email:
                rx = {"$regex": f"^{re.escape(user.email.strip())}$", "$options": "i"}
                clauses.append({slot.email: rx})
        return {"$or": clauses} if clauses else None

    def _plan(
        self,
        resource_type: str,
        doc: dict[str, Any],
        user: DirectoryUser,
        personal: str | None,
        rule: TransferRule | None,
        successor: _Successor | None,
    ) -> _Plan:
        plan = _Plan()
        owns_group = personal is not None and doc.get("ownerGroup") == personal
        slots = CONTACT_SLOTS[resource_type]
        matched = [s for s in slots if _slot_matches(s, doc, user)]
        if rule is None or successor is None:
            plan.notes.append("no transfer rule matches the departing user")
            return plan
        if successor.error:
            plan.error = successor.error
            return plan
        if owns_group:
            if successor.group:
                plan.changes["ownerGroup"] = successor.group
            else:
                plan.notes.append("successor has no personal group; ownerGroup left unchanged")
            if successor.person and slots and slots[0] not in matched:
                matched.insert(0, slots[0])  # the owner moves together with the group
        if matched:
            if successor.person:
                for slot in matched:
                    values, notes = _slot_values(slot, successor.person)
                    plan.changes.update(values)
                    plan.notes.extend(notes)
            else:
                plan.notes.append("contact fields still name the departing user")
        # drop no-op changes
        plan.changes = {k: v for k, v in plan.changes.items() if doc.get(k) != v}
        return plan

    # ---- Batches ----

    async def transfer_for_user(
        self,
        user_id: str,
        *,
        reason: str = "departure",
        actor: str = "system",
        groups: list[str] | None = None,
    ) -> TransferBatchResult:
        departure = Departure(
            userId=user_id, reason=reason, groups=sorted(set(groups or [])),
            at=self.ctx.now(), by=actor,
        )
        await self.departures.insert_one(departure.model_dump())
        return await self.run_batch(departure, actor=actor)

    async def retry_batch(self, batch_id: str, actor: str) -> TransferBatchResult:
        doc = await self.departures.find_one({"id": batch_id}, {"_id": 0})
        if not doc:
            raise TransferBatchNotFoundError(batch_id)
        return await self.run_batch(Departure(**doc), actor=actor)

    async def run_batch(self, departure: Departure, *, actor: str) -> TransferBatchResult:
        user = await self.ctx.directory.get(departure.userId) or DirectoryUser(
            userId=departure.userId
        )
        personal = self._personal_group(user)
        rule = await self._match_rule(user, departure.groups)
        successor = await self._resolve_successor(rule) if rule else None
        previous = {
            (doc["resourceType"], doc["resourceId"]): TransferRecord(**doc)
            async for doc in self.records.find({"batchId": departure.id}, {"_id": 0})
        }

        result = TransferBatchResult(batchId=departure.id)
        seen: set[tuple[str, str]] = set()
        enumerated: set[str] = set()
        for resource_type in OWNED_RESOURCE_TYPES:
            where = self._ownership_query(resource_type, user, personal)
            if where is None:
                enumerated.add(resource_type)
                continue
            try:
                docs = [d async for d in self.ctx.scicat.iter_resources(resource_type, where)]
            except ScicatError as exc:
                result.errors.append(f"could not list {resource_type}s: {exc}")
                continue
            enumerated.add(resource_type)
            for doc in docs:
                rid = resource_id(resource_type, doc)
                key = (resource_type, rid)
                if not rid or key in seen:
                    continue
                seen.add(key)
                prev = previous.get(key)
                plan = self._plan(resource_type, doc, user, personal, rule, successor)
                if not plan.changes and not plan.error and prev and prev.outcome == "transferred":
                    continue  # done earlier; only notes (e.g. contact kept) remain
                record = await self._execute(
                    departure, actor, resource_type, rid, doc, rule, plan, prev
                )
                result.records.append(record)

        # earlier pending/failed records the user no longer owns were fixed by hand
        for (resource_type, rid), prev in previous.items():
            if (
                (resource_type, rid) in seen
                or resource_type not in enumerated
                or prev.outcome not in ("pending_manual", "failed")
            ):
                continue
            record = prev.model_copy(update={
                "outcome": "resolved", "error": None, "at": self.ctx.now(), "by": actor,
                "notes": [*prev.notes, "no longer owned by the departing user"],
            })
            await self._save(record, prev, actor)
            result.records.append(record)

        failed = await self.records.count_documents({"batchId": departure.id, "outcome": "failed"})
        await self.departures.update_one(
            {"id": departure.id},
            {"$set": {"needsRetry": bool(result.errors or failed), "lastRunAt": self.ctx.now()}},
        )
        return result

    async def retry_incomplete(self, actor: str = "system") -> int:
        """Re-run departures that hit SciCat errors (SC-008); returns how many ran.
        `pending_manual` items alone do not trigger retries — they need a human or rule."""
        runs = 0
        cursor = self.departures.find({"needsRetry": True}, {"_id": 0})
        for doc in [d async for d in cursor]:
            await self.run_batch(Departure(**doc), actor=actor)
            runs += 1
        return runs

    async def _execute(
        self,
        departure: Departure,
        actor: str,
        resource_type: str,
        rid: str,
        doc: dict[str, Any],
        rule: TransferRule | None,
        plan: _Plan,
        prev: TransferRecord | None,
    ) -> TransferRecord:
        before = {k: doc.get(k) for k in plan.changes}
        outcome, error = "pending_manual", plan.error
        if plan.error:
            outcome = "failed"
        elif plan.changes:
            try:
                await self.ctx.scicat.patch_resource(resource_type, rid, plan.changes)
                outcome = "transferred"
            except ScicatError as exc:
                outcome, error = "failed", str(exc)
        record = TransferRecord(
            id=prev.id if prev else new_id(),
            batchId=departure.id,
            triggerReason=departure.reason,
            fromUserId=departure.userId,
            resourceType=resource_type,
            resourceId=rid,
            previousOwnerGroup=doc.get("ownerGroup") or "",
            previousOwner=doc.get("owner"),
            newOwnerGroup=plan.changes.get("ownerGroup", ""),
            newOwner=plan.changes.get("owner"),
            ruleId=rule.id if rule else None,
            outcome=outcome,
            error=error,
            notes=plan.notes,
            before=before,
            after=dict(plan.changes),
            at=self.ctx.now(),
            by=actor,
        )
        await self._save(record, prev, actor)
        return record

    async def _save(
        self, record: TransferRecord, prev: TransferRecord | None, actor: str
    ) -> None:
        if prev is None:
            await self.records.insert_one(record.model_dump())
        else:
            await self.records.replace_one({"id": prev.id}, record.model_dump())
        if prev is not None and prev.outcome == record.outcome and record.outcome != "transferred":
            return  # unchanged retry: no audit noise
        target = f"{record.resourceType}/{record.resourceId}"
        await self.ctx.audit.record(
            actor=actor, action="transfer.execute", entity_type="transfer",
            entity_id=record.id, actor_kind="system" if actor == "system" else "user",
            summary=(
                f"{record.outcome} {target} from {record.fromUserId}"
                + (f": {', '.join(f'{k}={v}' for k, v in record.after.items())}"
                   if record.after and record.outcome == "transferred" else "")
                + (f" ({record.error})" if record.error else "")
            ),
            before=record.before or None,
            after=record.model_dump(mode="json"),
        )
