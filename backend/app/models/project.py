"""catorga project models: a project is a SciCat proposal plus the records linked to it."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from ..util import new_id, utcnow

MoveStatus = Literal["done", "incomplete", "superseded"]


class ProjectMove(BaseModel):
    """A change of a project's ownerGroup, carried over to its records."""

    id: str = Field(default_factory=new_id)
    proposalId: str
    fromGroup: str
    toGroup: str
    at: datetime = Field(default_factory=utcnow)
    by: str = ""
    moved: int = 0  # records and attachments moved so far
    failed: list[str] = []  # what SciCat refused on the last run (retried by the scheduler)
    status: MoveStatus = "done"
