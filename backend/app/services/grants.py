"""Resource grant application (T034).

Applies/removes a group as `ownerGroup` (mode=owner) or member of `accessGroups`
(mode=access) on SciCat resources via the REST client, read-modify-write per resource.
Bulk applies isolate per-item failures and report them individually (SC-006). Each grant
is persisted in `resource_grants` and audited; `owner` mode captures the prior owner so
the grant can be withdrawn (or restored) later.
"""

from __future__ import annotations

from typing import Any

from ..context import AppContext
from ..models.resource_grant import (
    BulkResult,
    BulkResultItem,
    GrantApply,
    ResourceGrant,
    ResourcePage,
    ResourceSummary,
    compute_grant_status,
)
from ..services.scicat_client import RESOURCE_MAP, ScicatError

# Fields tried (in order) to build a human-readable label for a resource.
_LABEL_FIELDS = ("datasetName", "name", "title", "proposalId", "sampleId", "description")


class GrantError(Exception):
    """Base for expected grant errors (mapped to HTTP by the router)."""


class GroupMissingError(GrantError):
    pass


class GrantNotFoundError(GrantError):
    pass


def _label_for(doc: dict[str, Any], resource_id: str) -> str:
    for field in _LABEL_FIELDS:
        value = doc.get(field)
        if value:
            return str(value)
    return resource_id


class GrantService:
    def __init__(self, ctx: AppContext) -> None:
        self.ctx = ctx
        self.col = ctx.app_db.resource_grants

    async def _require_group(self, name: str) -> None:
        group = await self.ctx.app_db.groups.find_one({"name": name}, {"_id": 0, "name": 1})
        if not group:
            raise GroupMissingError(name)

    def _id_field(self, resource_type: str) -> str:
        return RESOURCE_MAP[resource_type][1]

    async def apply(self, payload: GrantApply, actor: str) -> BulkResult:
        await self._require_group(payload.groupName)
        result = BulkResult(total=len(payload.resourceIds))
        for resource_id in payload.resourceIds:
            try:
                grant = await self._apply_one(payload, resource_id, actor)
                result.succeeded += 1
                result.items.append(
                    BulkResultItem(resourceId=resource_id, ok=True, grantId=grant.id)
                )
            except Exception as exc:  # noqa: BLE001 - isolate per-item failure
                result.failed += 1
                result.items.append(
                    BulkResultItem(resourceId=resource_id, ok=False, error=str(exc))
                )
        return result

    def _compose_apply(
        self, doc: dict[str, Any], group_name: str, mode: str
    ) -> tuple[dict[str, Any], str | None]:
        """Build the PATCH body that adds the group, plus the prior owner (owner mode)."""
        if mode == "owner":
            return {"ownerGroup": group_name}, doc.get("ownerGroup")
        current = list(doc.get("accessGroups") or [])
        if group_name not in current:
            current.append(group_name)
        return {"accessGroups": current}, None

    async def _push(self, grant: ResourceGrant) -> str | None:
        """Apply the grant to its SciCat resource; returns captured previous owner."""
        doc = await self.ctx.scicat.get_resource(grant.resourceType, grant.resourceId)
        body, previous_owner = self._compose_apply(doc, grant.groupName, grant.mode)
        await self.ctx.scicat.patch_resource(grant.resourceType, grant.resourceId, body)
        return previous_owner

    async def _withdraw(self, grant: ResourceGrant) -> None:
        """Remove the grant from its SciCat resource (best-effort; reconcilable)."""
        try:
            resource = await self.ctx.scicat.get_resource(grant.resourceType, grant.resourceId)
            if grant.mode == "owner":
                await self.ctx.scicat.patch_resource(
                    grant.resourceType, grant.resourceId,
                    {"ownerGroup": grant.previousOwnerGroup or ""},
                )
            else:
                current = [g for g in (resource.get("accessGroups") or []) if g != grant.groupName]
                await self.ctx.scicat.patch_resource(
                    grant.resourceType, grant.resourceId, {"accessGroups": current}
                )
        except ScicatError:
            # Resource may be gone; still record the grant as ended (reconcilable).
            pass

    async def _apply_one(
        self, payload: GrantApply, resource_id: str, actor: str
    ) -> ResourceGrant:
        doc = await self.ctx.scicat.get_resource(payload.resourceType, resource_id)
        status = compute_grant_status(payload.effectiveFrom, payload.expiresAt, self.ctx.now())

        previous_owner: str | None = None
        # Only push to SciCat when the grant is active now; scheduled windows are
        # activated later by the expiry sweep (US5).
        if status == "active":
            body, previous_owner = self._compose_apply(doc, payload.groupName, payload.mode)
            await self.ctx.scicat.patch_resource(payload.resourceType, resource_id, body)

        grant = ResourceGrant(
            groupName=payload.groupName,
            resourceType=payload.resourceType,
            resourceId=resource_id,
            mode=payload.mode,
            effectiveFrom=payload.effectiveFrom,
            expiresAt=payload.expiresAt,
            status=status,
            previousOwnerGroup=previous_owner,
            appliedBy=actor,
        )
        # One active/scheduled grant per (group, resource, mode): replace any prior one.
        await self.col.update_many(
            {
                "groupName": payload.groupName,
                "resourceType": payload.resourceType,
                "resourceId": resource_id,
                "mode": payload.mode,
                "status": {"$in": ["active", "scheduled"]},
            },
            {"$set": {"status": "removed", "endedAt": self.ctx.now(), "endedBy": actor}},
        )
        await self.col.insert_one(grant.model_dump())
        await self.ctx.audit.record(
            actor=actor, action="grant.apply", entity_type="grant", entity_id=grant.id,
            summary=(
                f"applied {payload.groupName} as {payload.mode} on "
                f"{payload.resourceType}/{resource_id}"
            ),
            after=grant.model_dump(mode="json"),
        )
        return grant

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

    async def remove(self, grant_id: str, actor: str) -> None:
        doc = await self.col.find_one({"id": grant_id}, {"_id": 0})
        if not doc:
            raise GrantNotFoundError(grant_id)
        grant = ResourceGrant(**doc)

        # Withdraw from SciCat only if the grant was actually applied.
        if grant.status == "active":
            await self._withdraw(grant)

        await self.col.update_one(
            {"id": grant_id},
            {"$set": {"status": "removed", "endedAt": self.ctx.now(), "endedBy": actor}},
        )
        await self.ctx.audit.record(
            actor=actor, action="grant.remove", entity_type="grant", entity_id=grant_id,
            summary=(
                f"removed {grant.groupName} from "
                f"{grant.resourceType}/{grant.resourceId}"
            ),
            before=doc,
        )

    async def sweep(self, actor: str = "system") -> dict[str, int]:
        """Materialise grant temporal transitions and reflect them in SciCat (US5).

        scheduled→active pushes the grant to SciCat (capturing the prior owner);
        active→expired withdraws it. Idempotent: only grants whose computed status
        differs from their stored status are touched.
        """
        now = self.ctx.now()
        activated = expired = 0
        cursor = self.col.find({"status": {"$in": ["active", "scheduled"]}}, {"_id": 0})
        docs = [doc async for doc in cursor]
        for doc in docs:
            grant = ResourceGrant(**doc)
            new_status = compute_grant_status(grant.effectiveFrom, grant.expiresAt, now)
            if new_status == grant.status:
                continue
            if grant.status == "scheduled" and new_status == "active":
                try:
                    previous = await self._push(grant)
                except ScicatError:
                    continue  # retry on the next sweep
                await self.col.update_one(
                    {"id": grant.id},
                    {"$set": {"status": "active", "previousOwnerGroup": previous}},
                )
                await self.ctx.audit.record(
                    actor=actor, action="grant.activate", entity_type="grant",
                    entity_id=grant.id, actor_kind="system",
                    summary=(
                        f"activated {grant.groupName} on "
                        f"{grant.resourceType}/{grant.resourceId}"
                    ),
                )
                activated += 1
            elif new_status == "expired":
                await self._withdraw(grant)
                await self.col.update_one(
                    {"id": grant.id},
                    {"$set": {"status": "expired", "endedAt": now, "endedBy": actor}},
                )
                await self.ctx.audit.record(
                    actor=actor, action="grant.expire", entity_type="grant",
                    entity_id=grant.id, actor_kind="system",
                    summary=(
                        f"expired {grant.groupName} on "
                        f"{grant.resourceType}/{grant.resourceId}"
                    ),
                )
                expired += 1
        return {"grantsActivated": activated, "grantsExpired": expired}

    async def browse(
        self,
        resource_type: str,
        q: str | None = None,
        owner_group: str | None = None,
        skip: int = 0,
        limit: int = 50,
    ) -> ResourcePage:
        filter_: dict[str, Any] = {}
        if owner_group:
            filter_["ownerGroup"] = owner_group
        docs = await self.ctx.scicat.list_resources(
            resource_type, filter_ or None, limit=limit, skip=skip
        )
        id_field = self._id_field(resource_type)
        items: list[ResourceSummary] = []
        for doc in docs:
            resource_id = str(doc.get(id_field, ""))
            label = _label_for(doc, resource_id)
            if q and q.lower() not in label.lower() and q.lower() not in resource_id.lower():
                continue
            items.append(
                ResourceSummary(
                    id=resource_id,
                    label=label,
                    ownerGroup=doc.get("ownerGroup") or "",
                    accessGroups=list(doc.get("accessGroups") or []),
                )
            )
        return ResourcePage(total=skip + len(items), items=items)
