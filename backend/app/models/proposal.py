"""Proposal create/update payloads proxied to SciCat.

Only the fields the authorization check needs are typed; every other SciCat proposal
field passes through unchanged and SciCat validates it.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, field_validator


class ProposalCreate(BaseModel):
    model_config = ConfigDict(extra="allow")

    proposalId: str
    ownerGroup: str

    @field_validator("proposalId", "ownerGroup")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("must not be empty")
        return value


class ProposalUpdate(BaseModel):
    model_config = ConfigDict(extra="allow")

    ownerGroup: str | None = None

    @field_validator("ownerGroup")
    @classmethod
    def _not_blank(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value:
            raise ValueError("must not be empty")
        return value
