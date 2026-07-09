"""Group models (T016)."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from ..util import utcnow

GroupCategory = Literal["research-group", "project", "proposal", "instrument", "other"]
GroupStatus = Literal["active", "retired"]


class GroupCreate(BaseModel):
    name: str
    description: str = ""
    category: GroupCategory = "other"
    managers: list[str] = []


class GroupUpdate(BaseModel):
    description: str | None = None
    category: GroupCategory | None = None
    managers: list[str] | None = None
    status: GroupStatus | None = None


class Group(BaseModel):
    name: str
    description: str = ""
    category: GroupCategory = "other"
    managers: list[str] = []
    status: GroupStatus = "active"
    createdAt: datetime = Field(default_factory=utcnow)
    createdBy: str = ""
    modifiedAt: datetime = Field(default_factory=utcnow)
    modifiedBy: str = ""


class GroupDetail(Group):
    memberCount: int = 0
    grantCount: int = 0
