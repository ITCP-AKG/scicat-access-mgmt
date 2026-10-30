"""Group invitation models.

An invitation is personal: single-use, bound to one e-mail address, expiring and
revocable. Only a hash of its token is stored; the link is shown once, on creation.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from ..util import new_id, utcnow

InviteStatus = Literal["pending", "accepted", "revoked", "expired"]


class InviteCreate(BaseModel):
    groupName: str
    email: str
    # how long the link stays valid (default: INVITE_DEFAULT_DAYS)
    validDays: int | None = Field(default=None, ge=1)
    # optional end of the resulting membership
    membershipExpiresAt: datetime | None = None


class InviteOut(BaseModel):
    id: str = Field(default_factory=new_id)
    groupName: str
    email: str  # lower-cased
    createdBy: str = ""
    createdAt: datetime = Field(default_factory=utcnow)
    expiresAt: datetime
    membershipExpiresAt: datetime | None = None
    status: InviteStatus = "pending"
    acceptedBy: str | None = None
    acceptedAt: datetime | None = None
    revokedBy: str | None = None
    revokedAt: datetime | None = None


class Invite(InviteOut):
    tokenHash: str  # sha256 of the token; the token itself is never stored


class InviteCreated(InviteOut):
    token: str
    # the invitation link (INVITE_LINK_BASE + token); empty when no base is configured
    link: str = ""


class InvitePreview(BaseModel):
    """What the invitee sees before accepting (no login needed)."""

    groupName: str
    groupDescription: str = ""
    email: str
    invitedBy: str = ""  # the inviter's display name
    expiresAt: datetime
    status: InviteStatus


class InviteAccepted(BaseModel):
    groupName: str
    alreadyMember: bool = False
