"""Resource grant application (T034).

Applies/removes a group as `ownerGroup` (mode=owner) or member of `accessGroups`
(mode=access) on SciCat resources via the REST client, read-modify-write per resource.
Bulk applies isolate per-item failures and report them individually (SC-006). Each grant
is persisted in `resource_grants` and audited.

Withdrawal semantics:
- a grant only undoes what it did: if the group already owned / had access to the
  resource when the grant took effect (`preexisting`), withdrawal leaves it in place;
- owner grants restore `previousOwnerGroup`, but only while the resource is still owned by
  the grant's group (never an empty ownerGroup);
- a withdrawal SciCat refuses is not swallowed: the grant stays effective, flagged
  `pendingRemoval`, and the expiry sweep retries it.
At most one owner grant per resource is open at a time; re-applying a grant for the same
group replaces it and carries over what it captured.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from ..context import AppContext
from ..models.resource_grant import (
    BulkResult,
    BulkResultItem,
    GrantApply,
    GrantDriftItem,
    GrantStatus,
    ResourceGrant,
    ResourcePage,
    ResourceSummary,
    compute_grant_status,
)
from ..services.scicat_client import PAGE_SIZE, RESOURCE_MAP, ScicatError, resource_id
from ..util import window_error

logger = logging.getLogger(__name__)

_OPEN = {"$in": ["active", "scheduled"]}

# Per type: fields searched by `q` (pushed to SciCat as a case-insensitive regex) and tried,
# in order, to build a human-readable label.
_SEARCH_FIELDS: dict[str, tuple[str, ...]] = {
    "dataset": ("datasetName", "pid", "description"),
    "origdatablock": ("datasetId", "_id"),
    "proposal": ("title", "proposalId"),
    "sample": ("description", "sampleId"),
}
_LABEL_FIELDS: dict[str, tuple[str, ...]] = {
    "dataset": ("datasetName", "description"),
    "origdatablock": ("datasetId",),
    "proposal": ("title",),
    "sample": ("description",),
}


class GrantError(Exception):
    """Base for expected grant errors (mapped to HTTP by the router)."""


class GroupMissingError(GrantError):
    pass


class GroupRetiredError(GrantError):
    pass


class InvalidWindowError(GrantError):
    pass


class GrantNotFoundError(GrantError):
    pass


class GrantForbiddenError(GrantError):
    pass


class GrantConflictError(GrantError):
    pass


def _label_for(resource_type: str, doc: dict[str, Any], rid: str) -> str:
    for field in _LABEL_FIELDS.get(resource_type, ()):
        value = doc.get(field)
        if value:
            return str(value)
    return rid


def _describe(grant: ResourceGrant) -> str:
    return f"{grant.groupName} ({grant.mode}) on {grant.resourceType}/{grant.resourceId}"


class GrantService:
    def __init__(self, ctx: AppContext) -> None:
        self.ctx = ctx
        self.col = ctx.app_db.resource_grants

    async def _require_group(self, name: str) -> None:
        group = await self.ctx.app_db.groups.find_one({"name": name}, {"_id": 0, "status": 1})
        if not group:
            raise GroupMissingError(name)
        if group.get("status") == "retired":
            raise GroupRetiredError(f"group '{name}' is retired")

    async def get(self, grant_id: str) -> ResourceGrant:
        doc = await self.col.find_one({"id": grant_id}, {"_id": 0})
        if not doc:
            raise GrantNotFoundError(grant_id)
        return ResourceGrant(**doc)

    async def list(
        self, group_name: str | None = None, resource_type: str | None = None
    ) -> list[ResourceGrant]:
        query: dict[str, Any] = {}
        if group_name:
            query["groupName"] = group_name
        if resource_type:
            query["resourceType"] = resource_type
        cursor = self.col.find(query, {"_id": 0}).sort("appliedAt", -1)
        return [ResourceGrant(**doc) async for doc in cursor]

    # ---- SciCat effects ----

    async def _activate(
        self,
        grant: ResourceGrant,
        doc: dict[str, Any],
        inherited: ResourceGrant | None = None,
    ) -> dict[str, Any]:
        """Make the grant effective on the resource `doc`; returns what it captured.

        `inherited` is the grant being replaced for the same group: its captured state
        (original owner, pre-existence) is carried over instead of re-read, because the
        resource currently reflects that grant, not the state before it.
        """
        group = grant.groupName
        if grant.mode == "owner":
            current = doc.get("ownerGroup") or ""
            if inherited is not None:
                fields = {
                    "previousOwnerGroup": inherited.previousOwnerGroup,
                    "preexisting": inherited.preexisting,
                }
            else:
                fields = {
                    "previousOwnerGroup": current if current and current != group else None,
                    "preexisting": current == group,
                }
            if current != group:
                await self.ctx.scicat.patch_resource(
                    grant.resourceType, grant.resourceId, {"ownerGroup": group}
                )
        else:
            current_list = list(doc.get("accessGroups") or [])
            fields = {
                "preexisting": inherited.preexisting
                if inherited is not None
                else group in current_list
            }
            if group not in current_list:
                await self.ctx.scicat.patch_resource(
                    grant.resourceType, grant.resourceId, {"accessGroups": [*current_list, group]}
                )
        return fields

    async def _withdraw(self, grant: ResourceGrant) -> str | None:
        """Undo an applied grant in SciCat.

        Returns a note when the resource was deliberately left as is; raises ScicatError
        when SciCat refused or was unreachable (the caller keeps the grant pending).
        """
        try:
            doc = await self.ctx.scicat.get_resource(grant.resourceType, grant.resourceId)
        except ScicatError as exc:
            if exc.status == 404:
                return "resource no longer exists in SciCat"
            raise
        group = grant.groupName
        if grant.preexisting:
            return "the group held this before the grant; left in place"
        if grant.mode == "owner":
            current = doc.get("ownerGroup") or ""
            if current != group:
                return f"ownerGroup already changed to '{current}'; left as is"
            previous = grant.previousOwnerGroup
            if not previous or previous == group:
                return "no previous owner recorded; ownership left with the group"
            await self.ctx.scicat.patch_resource(
                grant.resourceType, grant.resourceId, {"ownerGroup": previous}
            )
            return None
        current_list = list(doc.get("accessGroups") or [])
        if group in current_list:
            await self.ctx.scicat.patch_resource(
                grant.resourceType,
                grant.resourceId,
                {"accessGroups": [g for g in current_list if g != group]},
            )
        return None

    async def _end(
        self, grant: ResourceGrant, final_status: GrantStatus, actor: str, *, system: bool = False
    ) -> bool:
        """Close a grant, withdrawing it from SciCat if it was applied.

        Returns False (grant kept effective, flagged pendingRemoval) if SciCat refused.
        """
        now = self.ctx.now()
        audit_actor = "system" if system else actor
        actor_kind = "system" if audit_actor == "system" else "user"
        note = None
        if grant.status == "active":
            try:
                note = await self._withdraw(grant)
            except ScicatError as exc:
                await self.col.update_one(
                    {"id": grant.id},
                    {"$set": {
                        "pendingRemoval": True,
                        "pendingStatus": final_status,
                        "endRequestedBy": grant.endRequestedBy or actor,
                        "lastError": str(exc),
                    }},
                )
                if not grant.pendingRemoval:  # audit the first failure, not every retry
                    await self.ctx.audit.record(
                        actor=audit_actor, actor_kind=actor_kind,
                        action="grant.withdraw_failed", entity_type="grant", entity_id=grant.id,
                        summary=f"could not withdraw {_describe(grant)}: {exc}; will retry",
                    )
                return False
        await self.col.update_one(
            {"id": grant.id},
            {"$set": {
                "status": final_status,
                "endedAt": now,
                "endedBy": actor,
                "pendingRemoval": False,
                "pendingStatus": None,
                "lastError": note,
            }},
        )
        verb = "expired" if final_status == "expired" else "removed"
        await self.ctx.audit.record(
            actor=audit_actor, actor_kind=actor_kind,
            action="grant.expire" if final_status == "expired" else "grant.remove",
            entity_type="grant", entity_id=grant.id,
            summary=f"{verb} {_describe(grant)}" + (f": {note}" if note else ""),
            before=grant.model_dump(mode="json"),
        )
        return True

    # ---- apply ----

    async def apply(
        self, payload: GrantApply, actor: str, allowed_owner_groups: set[str] | None = None
    ) -> BulkResult:
        """Apply a grant to each resource, isolating per-item failures.

        `allowed_owner_groups` (non-admin callers): only resources whose current ownerGroup
        is in this set may be granted; others fail individually as forbidden.
        """
        await self._require_group(payload.groupName)
        error = window_error(payload.effectiveFrom, payload.expiresAt, self.ctx.now())
        if error:
            raise InvalidWindowError(error)
        ids = list(dict.fromkeys(payload.resourceIds))
        result = BulkResult(total=len(ids))
        for rid in ids:
            try:
                grant = await self._apply_one(payload, rid, actor, allowed_owner_groups)
                result.succeeded += 1
                result.items.append(BulkResultItem(resourceId=rid, ok=True, grantId=grant.id))
            except Exception as exc:  # noqa: BLE001 - isolate per-item failure
                if not isinstance(exc, (GrantError, ScicatError)):
                    logger.exception("grant apply failed for %s", rid)
                result.failed += 1
                result.items.append(BulkResultItem(resourceId=rid, ok=False, error=str(exc)))
        return result

    async def _apply_one(
        self,
        payload: GrantApply,
        rid: str,
        actor: str,
        allowed_owner_groups: set[str] | None = None,
    ) -> ResourceGrant:
        doc = await self.ctx.scicat.get_resource(payload.resourceType, rid)
        if allowed_owner_groups is not None and doc.get("ownerGroup") not in allowed_owner_groups:
            raise GrantForbiddenError(
                f"forbidden: {payload.resourceType}/{rid} is not owned by one of your groups"
            )
        now = self.ctx.now()
        status = compute_grant_status(payload.effectiveFrom, payload.expiresAt, now)
        open_grants = [
            ResourceGrant(**d)
            async for d in self.col.find(
                {"resourceType": payload.resourceType, "resourceId": rid,
                 "mode": payload.mode, "status": _OPEN},
                {"_id": 0},
            )
        ]
        if payload.mode == "owner":
            other = next((g for g in open_grants if g.groupName != payload.groupName), None)
            if other is not None:
                raise GrantConflictError(
                    f"{payload.resourceType}/{rid} already has an owner grant for "
                    f"'{other.groupName}'; remove it first"
                )
        same = [g for g in open_grants if g.groupName == payload.groupName]
        applied = next((g for g in same if g.status == "active"), None)

        grant = ResourceGrant(
            groupName=payload.groupName,
            resourceType=payload.resourceType,
            resourceId=rid,
            mode=payload.mode,
            effectiveFrom=payload.effectiveFrom,
            expiresAt=payload.expiresAt,
            status=status,
            appliedBy=actor,
        )
        if status == "active":
            grant = grant.model_copy(update=await self._activate(grant, doc, inherited=applied))
        elif applied is not None:
            # the new window starts later: take the current grant's effect back first
            if not await self._end(applied, "removed", actor):
                raise GrantError(
                    f"could not withdraw the current grant on {payload.resourceType}/{rid}; "
                    "it is pending removal and will be retried"
                )

        await self.col.insert_one(grant.model_dump())
        # the new grant replaces any open one for the same group/resource/mode
        await self.col.update_many(
            {"id": {"$in": [g.id for g in same]}, "status": _OPEN},
            {"$set": {"status": "removed", "endedAt": now, "endedBy": actor,
                      "supersededBy": grant.id, "pendingRemoval": False}},
        )
        await self.ctx.audit.record(
            actor=actor, action="grant.apply", entity_type="grant", entity_id=grant.id,
            summary=f"applied {_describe(grant)}"
            + (" (scheduled)" if status == "scheduled" else ""),
            after=grant.model_dump(mode="json"),
        )
        return grant

    # ---- remove / temporal sweep ----

    async def remove(self, grant_id: str, actor: str) -> ResourceGrant:
        """End a grant. Returns it; `pendingRemoval` is set if SciCat refused (retried)."""
        grant = await self.get(grant_id)
        if grant.status in ("active", "scheduled"):  # ended grants: idempotent no-op
            await self._end(grant, "removed", actor)
        return await self.get(grant_id)

    async def sweep(self, actor: str = "system") -> dict[str, int]:
        """Materialise grant temporal transitions and reflect them in SciCat (US5).

        scheduled→active pushes the grant (capturing what it changes); active→expired
        withdraws it; scheduled grants whose window lapsed unapplied are just closed;
        withdrawals that SciCat refused earlier are retried. Idempotent.
        """
        now = self.ctx.now()
        counts = {"grantsActivated": 0, "grantsExpired": 0, "grantsRetried": 0,
                  "grantsPendingRemoval": 0, "grantsActivationFailed": 0}
        docs = [doc async for doc in self.col.find({"status": _OPEN}, {"_id": 0})]
        for doc in docs:
            grant = ResourceGrant(**doc)
            if grant.resourceType not in RESOURCE_MAP:
                continue
            if grant.pendingRemoval:
                done = await self._end(
                    grant, grant.pendingStatus or "removed",
                    grant.endRequestedBy or actor, system=True,
                )
                counts["grantsRetried" if done else "grantsPendingRemoval"] += 1
                continue
            new_status = compute_grant_status(grant.effectiveFrom, grant.expiresAt, now)
            if new_status == grant.status:
                continue
            if grant.status == "scheduled" and new_status == "active":
                if await self._activate_scheduled(grant):
                    counts["grantsActivated"] += 1
                else:
                    counts["grantsActivationFailed"] += 1
            elif new_status == "expired":
                done = await self._end(grant, "expired", actor, system=True)
                counts["grantsExpired" if done else "grantsPendingRemoval"] += 1
        return counts

    async def _activate_scheduled(self, grant: ResourceGrant) -> bool:
        try:
            doc = await self.ctx.scicat.get_resource(grant.resourceType, grant.resourceId)
            fields = await self._activate(grant, doc)
        except ScicatError as exc:
            if exc.status == 404:
                await self.col.update_one(
                    {"id": grant.id},
                    {"$set": {"status": "removed", "endedAt": self.ctx.now(),
                              "endedBy": "system",
                              "lastError": "resource no longer exists in SciCat"}},
                )
            else:  # retry on the next sweep
                await self.col.update_one({"id": grant.id}, {"$set": {"lastError": str(exc)}})
            return False
        await self.col.update_one(
            {"id": grant.id}, {"$set": {"status": "active", "lastError": None, **fields}}
        )
        await self.ctx.audit.record(
            actor="system", actor_kind="system", action="grant.activate",
            entity_type="grant", entity_id=grant.id, summary=f"activated {_describe(grant)}",
        )
        return True

    # ---- reconciliation ----

    async def _fetch_many(self, resource_type: str, ids: list[str]) -> dict[str, dict[str, Any]]:
        id_field = RESOURCE_MAP[resource_type][1]
        found: dict[str, dict[str, Any]] = {}
        for start in range(0, len(ids), PAGE_SIZE):
            chunk = ids[start:start + PAGE_SIZE]
            docs = await self.ctx.scicat.list_resources(
                resource_type, {id_field: {"$in": chunk}}, limit=len(chunk)
            )
            for doc in docs:
                found[resource_id(resource_type, doc)] = doc
        return found

    async def check_drift(
        self, *, apply: bool = True, actor: str = "system"
    ) -> tuple[list[GrantDriftItem], list[str]]:
        """Verify every applied grant against the live resource.

        Missing access entries are re-added (the app is the source of truth). Owner drift
        is reported only: a data owner may legitimately re-assign ownership in SciCat, and
        reverting it every cycle would fight them. Grants on deleted resources are closed.
        """
        by_type: dict[str, list[ResourceGrant]] = {}
        async for doc in self.col.find(
            {"status": "active", "pendingRemoval": {"$ne": True}}, {"_id": 0}
        ):
            grant = ResourceGrant(**doc)
            if grant.resourceType in RESOURCE_MAP:
                by_type.setdefault(grant.resourceType, []).append(grant)

        items: list[GrantDriftItem] = []
        errors: list[str] = []
        for rtype, grants in by_type.items():
            try:
                live = await self._fetch_many(rtype, sorted({g.resourceId for g in grants}))
            except ScicatError as exc:
                errors.append(f"grants on {rtype}: {exc}")
                continue
            for grant in grants:
                item = await self._check_one(grant, live.get(grant.resourceId), apply, actor)
                if item is not None:
                    items.append(item)
        return items, errors

    async def _check_one(
        self, grant: ResourceGrant, doc: dict[str, Any] | None, apply: bool, actor: str
    ) -> GrantDriftItem | None:
        base = grant.model_dump(include={"groupName", "resourceType", "resourceId", "mode"})
        if doc is None:
            item = GrantDriftItem(grantId=grant.id, issue="resource no longer exists", **base)
            if apply:
                item.fixed = await self._end(grant, "removed", actor, system=True)
            return item
        group = grant.groupName
        if grant.mode == "owner":
            owner = doc.get("ownerGroup") or ""
            if owner == group:
                return None
            issue = f"ownerGroup is '{owner}', expected '{group}' (changed outside the app)"
            if apply:
                await self.col.update_one({"id": grant.id}, {"$set": {"lastError": issue}})
            return GrantDriftItem(grantId=grant.id, issue=issue, **base)
        if group in (doc.get("accessGroups") or []):
            return None
        item = GrantDriftItem(grantId=grant.id, issue="group missing from accessGroups", **base)
        if apply:
            try:
                await self._activate(grant, doc, inherited=grant)
                item.fixed = True
                await self.ctx.audit.record(
                    actor="system", actor_kind="system", action="grant.reapply",
                    entity_type="grant", entity_id=grant.id,
                    summary=f"re-applied {_describe(grant)} (drift)",
                )
            except ScicatError as exc:
                item.issue += f"; re-apply failed: {exc}"
        return item

    # ---- browsing ----

    async def browse(
        self,
        resource_type: str,
        q: str | None = None,
        owner_group: str | None = None,
        skip: int = 0,
        limit: int = 50,
        restrict_owner_groups: list[str] | None = None,
    ) -> ResourcePage:
        """One page of SciCat resources. `restrict_owner_groups` limits non-admin callers
        to resources owned by their own groups."""
        where: dict[str, Any] = {}
        if owner_group:
            where["ownerGroup"] = owner_group
        if restrict_owner_groups is not None:
            allowed = list(restrict_owner_groups)
            if owner_group:
                allowed = [owner_group] if owner_group in allowed else []
            where["ownerGroup"] = {"$in": allowed}
        if q:
            rx = {"$regex": re.escape(q), "$options": "i"}
            where["$or"] = [{field: rx} for field in _SEARCH_FIELDS[resource_type]]
        # fetch one extra row to learn whether another page exists
        docs = await self.ctx.scicat.list_resources(
            resource_type, where, limit=limit + 1, skip=skip
        )
        items = [
            ResourceSummary(
                id=(rid := resource_id(resource_type, doc)),
                label=_label_for(resource_type, doc, rid),
                ownerGroup=doc.get("ownerGroup") or "",
                accessGroups=list(doc.get("accessGroups") or []),
            )
            for doc in docs[:limit]
        ]
        return ResourcePage(items=items, hasMore=len(docs) > limit)
