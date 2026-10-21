"""Transfer rule + record models (T043).

A TransferRule maps a departing/deactivated user (optionally scoped by group/category)
to a successor user or group. A Departure is one trigger (deactivation or lapse of the
user's last membership) and doubles as the batch id of its TransferRecords; each record
logs one resource reassignment and is updated in place when the batch is retried
(data-model.md `transfer_rules` / `transfer_records`).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from ..models.resource_grant import ResourceType
from ..util import new_id, utcnow

SuccessorType = Literal["user", "group"]
TriggerReason = Literal["departure", "expiry", "manual"]
# resolved: was pending/failed, but the user no longer owns the resource (fixed by hand)
TransferOutcome = Literal["transferred", "pending_manual", "failed", "resolved"]


class TransferMatch(BaseModel):
    userId: str | None = None
    category: str | None = None
    groupName: str | None = None


class TransferRuleCreate(BaseModel):
    name: str = Field(min_length=1)
    match: TransferMatch = Field(default_factory=TransferMatch)
    successorType: SuccessorType
    successor: str = Field(min_length=1)  # group name, or directory userId
    # user successors: also hand over contact fields (owner/ownerEmail/...)
    transferOwner: bool = False
    priority: int = 100
    enabled: bool = True


class TransferRule(TransferRuleCreate):
    id: str = Field(default_factory=new_id)
    createdAt: datetime = Field(default_factory=utcnow)
    createdBy: str = ""


class TransferRecord(BaseModel):
    id: str = Field(default_factory=new_id)
    batchId: str
    triggerReason: TriggerReason
    fromUserId: str
    resourceType: ResourceType
    resourceId: str
    previousOwnerGroup: str = ""
    previousOwner: str | None = None
    newOwnerGroup: str = ""
    newOwner: str | None = None
    ruleId: str | None = None
    outcome: TransferOutcome
    error: str | None = None
    notes: list[str] = []
    before: dict[str, Any] = {}  # fields changed (or that would change), as they were
    after: dict[str, Any] = {}
    at: datetime = Field(default_factory=utcnow)
    by: str = "system"


class Departure(BaseModel):
    """One transfer trigger; its id is the batchId of the resulting records."""

    id: str = Field(default_factory=new_id)
    userId: str
    reason: TriggerReason
    # groups the user belonged to when leaving: transfer rules are matched against these
    groups: list[str] = []
    at: datetime = Field(default_factory=utcnow)
    by: str = "system"
    # SciCat could not be listed or refused a reassignment: retried by the reconcile job
    needsRetry: bool = False
    lastRunAt: datetime | None = None


class TransferBatchResult(BaseModel):
    batchId: str
    records: list[TransferRecord] = []  # records created or updated by this run
    errors: list[str] = []  # e.g. a resource type that could not be listed (retry later)
