"""Transfer rule + record models (T043).

A TransferRule maps a departing/deactivated user (optionally scoped by group/category)
to a successor user or group. A TransferRecord is the immutable, idempotent log of one
resource reassignment (data-model.md `transfer_rules` / `transfer_records`).
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from ..models.resource_grant import ResourceType
from ..util import new_id, utcnow

SuccessorType = Literal["user", "group"]
TriggerReason = Literal["departure", "expiry", "manual"]
TransferOutcome = Literal["transferred", "pending_manual", "failed"]


class TransferMatch(BaseModel):
    userId: str | None = None
    category: str | None = None
    groupName: str | None = None


class TransferRuleCreate(BaseModel):
    name: str
    match: TransferMatch = Field(default_factory=TransferMatch)
    successorType: SuccessorType
    successor: str
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
    at: datetime = Field(default_factory=utcnow)
    by: str = "system"


class TransferBatchResult(BaseModel):
    batchId: str
    records: list[TransferRecord] = []
