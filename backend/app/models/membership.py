"""Membership models (T022)."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from ..util import new_id, utcnow

MembershipStatus = Literal["active", "scheduled", "expired", "revoked"]


def compute_status(
    effective_from: datetime | None,
    expires_at: datetime | None,
    now: datetime,
    ended: bool = False,
) -> MembershipStatus:
    """Derive membership status from its temporal window (data-model.md)."""
    if ended:
        return "revoked"
    if expires_at is not None and expires_at <= now:
        return "expired"
    if effective_from is not None and effective_from > now:
        return "scheduled"
    return "active"


class MembershipCreate(BaseModel):
    userId: str
    effectiveFrom: datetime | None = None
    expiresAt: datetime | None = None


class MembershipUpdate(BaseModel):
    effectiveFrom: datetime | None = None
    expiresAt: datetime | None = None


class Membership(BaseModel):
    id: str = Field(default_factory=new_id)
    groupName: str
    userId: str
    userDisplay: str = ""
    effectiveFrom: datetime | None = None
    expiresAt: datetime | None = None
    status: MembershipStatus = "active"
    addedAt: datetime = Field(default_factory=utcnow)
    addedBy: str = ""
    endedAt: datetime | None = None
    endedBy: str | None = None
