"""Resource grant models (T033).

A grant applies a group to a SciCat resource's access list (`accessGroups`) or as its
`ownerGroup`, optionally time-bounded. Mirrors data-model.md `resource_grants` and the
`ResourceGrant`/`GrantApply`/`BulkResult`/`ResourcePage` schemas in openapi.yaml.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from ..util import new_id, utcnow

ResourceType = Literal["dataset", "origdatablock", "proposal", "sample", "instrument", "job"]
GrantMode = Literal["owner", "access"]
GrantStatus = Literal["active", "scheduled", "expired", "removed"]


def compute_grant_status(
    effective_from: datetime | None,
    expires_at: datetime | None,
    now: datetime,
    removed: bool = False,
) -> GrantStatus:
    """Derive grant status from its temporal window (data-model.md)."""
    if removed:
        return "removed"
    if expires_at is not None and expires_at <= now:
        return "expired"
    if effective_from is not None and effective_from > now:
        return "scheduled"
    return "active"


class GrantApply(BaseModel):
    groupName: str
    resourceType: ResourceType
    resourceIds: list[str]
    mode: GrantMode = "access"
    effectiveFrom: datetime | None = None
    expiresAt: datetime | None = None


class ResourceGrant(BaseModel):
    id: str = Field(default_factory=new_id)
    groupName: str
    resourceType: ResourceType
    resourceId: str
    mode: GrantMode = "access"
    effectiveFrom: datetime | None = None
    expiresAt: datetime | None = None
    status: GrantStatus = "active"
    previousOwnerGroup: str | None = None
    appliedAt: datetime = Field(default_factory=utcnow)
    appliedBy: str = ""
    endedAt: datetime | None = None
    endedBy: str | None = None


class BulkResultItem(BaseModel):
    resourceId: str
    ok: bool
    error: str | None = None
    grantId: str | None = None


class BulkResult(BaseModel):
    total: int = 0
    succeeded: int = 0
    failed: int = 0
    items: list[BulkResultItem] = []


class ResourceSummary(BaseModel):
    id: str
    label: str = ""
    ownerGroup: str = ""
    accessGroups: list[str] = []


class ResourcePage(BaseModel):
    total: int = 0
    items: list[ResourceSummary] = []
