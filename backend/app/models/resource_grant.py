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

# Only these SciCat v4.3.1 types carry ownerGroup/accessGroups (instruments and jobs do not).
# "project" is a catorga project: the proposal plus its linked records (services/projects.py);
# a project grant is a parent whose children are ordinary grants on those records.
ResourceType = Literal["dataset", "origdatablock", "proposal", "sample", "project"]
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
    resourceIds: list[str] = Field(min_length=1, max_length=1000)
    mode: GrantMode = "access"
    effectiveFrom: datetime | None = None
    expiresAt: datetime | None = None


class ResourceGrant(BaseModel):
    id: str = Field(default_factory=new_id)
    groupName: str
    resourceType: str  # ResourceType; legacy rows may hold retired types
    resourceId: str
    mode: GrantMode = "access"
    effectiveFrom: datetime | None = None
    expiresAt: datetime | None = None
    status: GrantStatus = "active"
    # owner mode: the ownerGroup before the app took over (restored on withdrawal)
    previousOwnerGroup: str | None = None
    # the group already owned / had access to the resource before the grant took effect;
    # withdrawal then leaves it in place
    preexisting: bool = False
    # the resource's ownerGroup when the grant was applied: its managers may withdraw it
    resourceOwnerGroup: str | None = None
    # a child of a project grant: its window and lifetime are the parent's
    parentGrantId: str | None = None
    # listing only: a project grant's open children
    childCount: int | None = None
    appliedAt: datetime = Field(default_factory=utcnow)
    appliedBy: str = ""
    endedAt: datetime | None = None
    endedBy: str | None = None
    # withdrawal from SciCat failed: still effective, retried by the sweep until it can
    # move to `pendingStatus`
    pendingRemoval: bool = False
    pendingStatus: GrantStatus | None = None
    endRequestedBy: str | None = None
    lastError: str | None = None  # last failure, or a note on how the grant ended
    supersededBy: str | None = None


class GrantDriftItem(BaseModel):
    """An applied grant whose effect is missing from (or contradicted by) SciCat."""

    grantId: str
    groupName: str
    resourceType: str
    resourceId: str
    mode: str
    issue: str
    fixed: bool = False


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
    items: list[ResourceSummary] = []
    hasMore: bool = False
