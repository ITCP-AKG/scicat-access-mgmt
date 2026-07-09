"""Directory user model (T010)."""

from __future__ import annotations

from pydantic import BaseModel


class DirectoryUser(BaseModel):
    userId: str
    username: str = ""
    displayName: str = ""
    email: str = ""
    accessGroups: list[str] = []
    active: bool = True
