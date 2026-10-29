"""Directory user model (T010)."""

from __future__ import annotations

from pydantic import BaseModel, Field

# Upper bound on one display-name lookup (a list page resolves its visible rows at once).
MAX_DISPLAY_NAME_LOOKUP = 200


class DisplayNameLookup(BaseModel):
    usernames: list[str] = Field(default_factory=list, max_length=MAX_DISPLAY_NAME_LOOKUP)


class DirectoryUser(BaseModel):
    userId: str
    username: str = ""
    displayName: str = ""
    email: str = ""
    accessGroups: list[str] = []
    active: bool = True
