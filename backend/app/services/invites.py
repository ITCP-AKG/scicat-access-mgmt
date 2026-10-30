"""Group invitations.

A group manager invites a person by e-mail; the invitee opens the link in catorga, logs
in (local or KIT/OIDC, which creates their SciCat identity on first login) and accepts,
which adds them to the group with the inviter as `addedBy` and projects the membership at
once. The signed-in account's e-mail must equal the invited address, so a forwarded or
leaked link is useless to anyone else. An invitation is used once; accepting it again
with the same account is a no-op.
"""

from __future__ import annotations

import hashlib
import re
import secrets
from datetime import timedelta
from typing import Any

from ..auth.jwt import CurrentUser
from ..context import AppContext
from ..models.invite import (
    Invite,
    InviteAccepted,
    InviteCreate,
    InviteCreated,
    InvitePreview,
)
from ..models.membership import MembershipCreate
from ..util import window_error
from .memberships import DuplicateMembershipError, MembershipService

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class InviteError(Exception):
    """Base for expected invitation errors (mapped to HTTP by the router)."""


class InvalidInviteError(InviteError):
    """Malformed request: bad e-mail, validity or window, inactive group (HTTP 422)."""


class InviteNotFoundError(InviteError):
    pass


class InviteGoneError(InviteError):
    """Expired, revoked, used by someone else, or its group is gone (HTTP 410)."""


class InviteEmailMismatchError(InviteError):
    """The signed-in account is not the invited one (HTTP 403)."""


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


class InviteService:
    def __init__(self, ctx: AppContext) -> None:
        self.ctx = ctx
        self.col = ctx.app_db.invites

    def _refresh(self, doc: dict[str, Any]) -> Invite:
        invite = Invite(**doc)
        if invite.status == "pending" and invite.expiresAt <= self.ctx.now():
            invite = invite.model_copy(update={"status": "expired"})
        return invite

    async def _active_group(self, name: str) -> dict[str, Any] | None:
        group = await self.ctx.app_db.groups.find_one({"name": name}, {"_id": 0})
        return group if group and group.get("status", "active") == "active" else None

    async def create(self, payload: InviteCreate, actor: str) -> InviteCreated:
        settings = self.ctx.settings
        if not await self._active_group(payload.groupName):
            raise InvalidInviteError(f"'{payload.groupName}' is not an active group")
        email = payload.email.strip().lower()
        if not EMAIL_RE.match(email):
            raise InvalidInviteError(f"'{payload.email}' is not an e-mail address")
        days = payload.validDays or settings.invite_default_days
        if days > settings.invite_max_days:
            raise InvalidInviteError(f"an invitation is valid for at most {settings.invite_max_days} days")
        now = self.ctx.now()
        error = window_error(None, payload.membershipExpiresAt, now)
        if error:
            raise InvalidInviteError(error)

        token = secrets.token_urlsafe(32)
        invite = Invite(
            groupName=payload.groupName,
            email=email,
            createdBy=actor,
            createdAt=now,
            expiresAt=now + timedelta(days=days),
            membershipExpiresAt=payload.membershipExpiresAt,
            tokenHash=hash_token(token),
        )
        await self.col.insert_one(invite.model_dump())
        public = invite.model_dump(exclude={"tokenHash"})
        await self.ctx.audit.record(
            actor=actor, action="invite.create", entity_type="invite", entity_id=invite.id,
            summary=f"invited {email} to {invite.groupName}",
            after={k: v for k, v in invite.model_dump(mode="json").items() if k != "tokenHash"},
        )
        link = f"{settings.invite_link_base}{token}" if settings.invite_link_base else ""
        return InviteCreated(**public, token=token, link=link)

    async def get(self, invite_id: str) -> Invite:
        doc = await self.col.find_one({"id": invite_id}, {"_id": 0})
        if not doc:
            raise InviteNotFoundError(invite_id)
        return self._refresh(doc)

    async def list(self, group_name: str) -> list[Invite]:
        cursor = self.col.find({"groupName": group_name}, {"_id": 0}).sort("createdAt", -1)
        return [self._refresh(doc) async for doc in cursor]

    async def revoke(self, invite_id: str, actor: str) -> Invite:
        invite = await self.get(invite_id)
        if invite.status != "pending":  # used, expired or revoked already: nothing to do
            return invite
        now = self.ctx.now()
        await self.col.update_one(
            {"id": invite_id, "status": "pending"},
            {"$set": {"status": "revoked", "revokedBy": actor, "revokedAt": now}},
        )
        await self.ctx.audit.record(
            actor=actor, action="invite.revoke", entity_type="invite", entity_id=invite_id,
            summary=f"revoked the invitation of {invite.email} to {invite.groupName}",
        )
        return await self.get(invite_id)

    async def _by_token(self, token: str) -> Invite:
        doc = await self.col.find_one({"tokenHash": hash_token(token)}, {"_id": 0})
        if not doc:
            raise InviteNotFoundError("invitation not found")
        return self._refresh(doc)

    async def preview(self, token: str) -> InvitePreview:
        invite = await self._by_token(token)
        group = await self.ctx.app_db.groups.find_one({"name": invite.groupName}, {"_id": 0})
        inviter = await self.ctx.directory.get(invite.createdBy) if invite.createdBy else None
        return InvitePreview(
            groupName=invite.groupName,
            groupDescription=(group or {}).get("description", ""),
            email=invite.email,
            invitedBy=(inviter.displayName or inviter.username) if inviter else "",
            expiresAt=invite.expiresAt,
            status=invite.status,
        )

    async def accept(self, token: str, user: CurrentUser) -> InviteAccepted:
        invite = await self._by_token(token)
        if invite.status == "accepted" and invite.acceptedBy == user.userId:
            return InviteAccepted(groupName=invite.groupName, alreadyMember=True)
        if invite.status != "pending":
            raise InviteGoneError(f"this invitation is {invite.status}")
        if (user.email or "").strip().lower() != invite.email:
            raise InviteEmailMismatchError(
                f"this invitation is for {invite.email}, but you are signed in as "
                f"{user.email or user.username}"
            )
        if not await self._active_group(invite.groupName):
            raise InviteGoneError(f"group '{invite.groupName}' is no longer active")
        now = self.ctx.now()
        if invite.membershipExpiresAt is not None and invite.membershipExpiresAt <= now:
            raise InviteGoneError("the membership this invitation offered has already ended")

        # Claim the invitation first, so two concurrent accepts cannot both use it.
        claimed = await self.col.update_one(
            {"id": invite.id, "status": "pending"},
            {"$set": {"status": "accepted", "acceptedBy": user.userId, "acceptedAt": now}},
        )
        if not claimed.matched_count:
            return await self.accept(token, user)  # re-evaluate the new state
        already = False
        try:
            await MembershipService(self.ctx).add(
                invite.groupName,
                MembershipCreate(userId=user.userId, expiresAt=invite.membershipExpiresAt),
                actor=invite.createdBy or user.userId,
            )
        except DuplicateMembershipError:
            already = True
        except Exception:
            await self.col.update_one(
                {"id": invite.id},
                {"$set": {"status": "pending", "acceptedBy": None, "acceptedAt": None}},
            )
            raise
        await self.ctx.audit.record(
            actor=user.userId, action="invite.accept", entity_type="invite", entity_id=invite.id,
            summary=f"{user.username} accepted the invitation to {invite.groupName}"
            + (" (already a member)" if already else ""),
        )
        return InviteAccepted(groupName=invite.groupName, alreadyMember=already)
