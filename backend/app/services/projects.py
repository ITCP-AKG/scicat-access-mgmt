"""catorga projects: a SciCat proposal plus the records linked to it.

catorga links a sample to its project through `sampleCharacteristics.SampleBase.proposal`
and a dataset through `proposalId`; origdatablocks belong to their dataset and
attachments to their proposal, sample or dataset. A project's records are the linked ones
owned by the proposal's ownerGroup: records another group owns stay that group's business
(the owner side decides).

Moving a project (a new ownerGroup on the proposal) moves its records and their
attachments along. Each move is kept in `project_moves`; what SciCat refused is retried by
the scheduler until it follows, or until the project moved on again.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..context import AppContext
from ..models.project import ProjectMove
from .scicat_client import PAGE_SIZE, ScicatError, attachment_id, resource_id

SAMPLE_PROJECT_FIELD = "sampleCharacteristics.SampleBase.proposal"
_OPEN = {"$in": ["active", "scheduled"]}


@dataclass
class Record:
    resource_type: str
    resource_id: str
    doc: dict[str, Any]

    @property
    def owner(self) -> str:
        return self.doc.get("ownerGroup") or ""


class ProjectService:
    def __init__(self, ctx: AppContext) -> None:
        self.ctx = ctx
        self.moves = ctx.app_db.project_moves

    async def linked(self, proposal_id: str, block_groups: set[str]) -> list[Record]:
        """Samples and datasets naming the project (any owner), plus the origdatablocks of
        its datasets owned by `block_groups` (blocks follow their dataset)."""
        scicat = self.ctx.scicat
        records = [
            Record("sample", resource_id("sample", doc), doc)
            async for doc in scicat.iter_resources("sample", {SAMPLE_PROJECT_FIELD: proposal_id})
        ]
        datasets = [
            Record("dataset", resource_id("dataset", doc), doc)
            async for doc in scicat.iter_resources("dataset", {"proposalId": proposal_id})
        ]
        records += datasets
        pids = [d.resource_id for d in datasets if d.owner in block_groups]
        for start in range(0, len(pids), PAGE_SIZE):
            where = {"datasetId": {"$in": pids[start : start + PAGE_SIZE]}}
            records += [
                Record("origdatablock", resource_id("origdatablock", doc), doc)
                async for doc in scicat.iter_resources("origdatablock", where)
            ]
        return records

    async def records(self, proposal_id: str) -> tuple[dict[str, Any], list[Record]]:
        """The proposal and the project's records: itself plus the linked records owned
        by its ownerGroup."""
        proposal = await self.ctx.scicat.get_resource("proposal", proposal_id)
        owner = proposal.get("ownerGroup") or ""
        linked = await self.linked(proposal_id, {owner})
        own = [Record("proposal", proposal_id, proposal)] + [r for r in linked if r.owner == owner]
        return proposal, own

    # ---- moves ----

    async def move(self, proposal_id: str, from_group: str, to_group: str, actor: str) -> ProjectMove:
        """Carry an ownerGroup change of the proposal (already made) over to its records."""
        move = ProjectMove(
            proposalId=proposal_id, fromGroup=from_group, toGroup=to_group,
            at=self.ctx.now(), by=actor,
        )
        await self._run(move)
        await self.moves.insert_one(move.model_dump())
        # the project's grants now belong to the new owner side
        parents = [
            doc["id"]
            async for doc in self.ctx.app_db.resource_grants.find(
                {"resourceType": "project", "resourceId": proposal_id, "status": _OPEN}, {"id": 1}
            )
        ]
        await self.ctx.app_db.resource_grants.update_many(
            {"$or": [{"id": {"$in": parents}}, {"parentGrantId": {"$in": parents}}], "status": _OPEN},
            {"$set": {"resourceOwnerGroup": to_group}},
        )
        await self.ctx.audit.record(
            actor=actor, action="project.move", entity_type="project", entity_id=proposal_id,
            summary=f"moved project {proposal_id} from {from_group} to {to_group}: "
            f"{move.moved} record(s)"
            + (f", {len(move.failed)} refused (retried)" if move.failed else ""),
            before={"ownerGroup": from_group}, after=move.model_dump(mode="json"),
        )
        return move

    async def _run(self, move: ProjectMove) -> None:
        """Move what the old group still owns; updates `move` in place."""
        scicat = self.ctx.scicat
        groups = {move.fromGroup, move.toGroup}
        linked = await self.linked(move.proposalId, groups)
        failed: list[str] = []
        for rec in linked:
            if rec.owner != move.fromGroup:
                continue
            try:
                await scicat.patch_resource(
                    rec.resource_type, rec.resource_id, {"ownerGroup": move.toGroup}
                )
                move.moved += 1
            except ScicatError as exc:
                failed.append(f"{rec.resource_type}/{rec.resource_id}: {exc}")

        parents = [("proposal", move.proposalId)] + [
            (r.resource_type, r.resource_id)
            for r in linked
            if r.resource_type in ("sample", "dataset") and r.owner in groups
        ]
        for rtype, rid in parents:
            try:
                attachments = await scicat.list_attachments(rtype, rid)
            except ScicatError as exc:
                failed.append(f"attachments of {rtype}/{rid}: {exc}")
                continue
            for att in attachments:
                if (att.get("ownerGroup") or "") != move.fromGroup:
                    continue
                try:
                    await scicat.patch_attachment(
                        rtype, rid, attachment_id(att), {"ownerGroup": move.toGroup}
                    )
                    move.moved += 1
                except ScicatError as exc:
                    failed.append(f"attachment {attachment_id(att)} of {rtype}/{rid}: {exc}")
        move.failed = failed
        move.status = "incomplete" if failed else "done"

    async def retry_incomplete(self) -> int:
        """Re-run moves SciCat partly refused; returns how many ran."""
        runs = 0
        docs = [d async for d in self.moves.find({"status": "incomplete"}, {"_id": 0})]
        for doc in docs:
            move = ProjectMove(**doc)
            try:
                proposal = await self.ctx.scicat.get_resource("proposal", move.proposalId)
            except ScicatError as exc:
                if exc.status != 404:
                    continue  # SciCat unavailable: next time
                proposal = {}
            if (proposal.get("ownerGroup") or "") != move.toGroup:
                move.status = "superseded"  # deleted, or moved on since
            else:
                await self._run(move)
                runs += 1
            await self.moves.replace_one({"id": move.id}, move.model_dump())
        return runs
