"""Append-only audit writer + query (T009)."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Any

from motor.motor_asyncio import AsyncIOMotorDatabase

from ..models.audit import ActorKind, AuditEntry


class AuditService:
    def __init__(
        self,
        app_db: AsyncIOMotorDatabase,
        resolve_name: Callable[[str], Awaitable[str]] | None = None,
    ) -> None:
        self.col = app_db.audit_log
        self._resolve_name = resolve_name

    async def record(
        self,
        *,
        actor: str,
        action: str,
        entity_type: str,
        entity_id: str,
        summary: str = "",
        before: dict[str, Any] | None = None,
        after: dict[str, Any] | None = None,
        actor_kind: ActorKind = "user",
    ) -> AuditEntry:
        actor_name = actor if actor == "system" else ""
        if not actor_name and self._resolve_name:
            try:
                actor_name = await self._resolve_name(actor)
            except Exception:  # noqa: BLE001 - a name lookup must never block auditing
                actor_name = ""
        entry = AuditEntry(
            actor=actor,
            actorName=actor_name,
            actorKind=actor_kind,
            action=action,
            entityType=entity_type,
            entityId=entity_id,
            summary=summary,
            before=before,
            after=after,
        )
        await self.col.insert_one(entry.model_dump())
        return entry

    async def query(
        self,
        *,
        actor: str | None = None,
        entity_type: str | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
        skip: int = 0,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        q: dict[str, Any] = {}
        if actor:
            q["actor"] = actor
        if entity_type:
            q["entityType"] = entity_type
        if date_from or date_to:
            at: dict[str, Any] = {}
            if date_from:
                at["$gte"] = date_from
            if date_to:
                at["$lte"] = date_to
            q["at"] = at
        cursor = self.col.find(q, {"_id": 0}).sort("at", -1).skip(skip).limit(limit)
        return [doc async for doc in cursor]
