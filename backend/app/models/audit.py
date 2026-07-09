"""Audit entry model (T009)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from ..util import new_id, utcnow

ActorKind = Literal["user", "system"]


class AuditEntry(BaseModel):
    id: str = Field(default_factory=new_id)
    at: datetime = Field(default_factory=utcnow)
    actor: str
    actorKind: ActorKind = "user"
    action: str
    entityType: str
    entityId: str
    summary: str = ""
    before: dict[str, Any] | None = None
    after: dict[str, Any] | None = None
