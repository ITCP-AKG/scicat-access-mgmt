"""SciCat-local directory provider (T010).

Reads the SciCat `UserIdentity` collection (the only place SciCat exposes the user
list + accessGroups). Maps each identity document to a DirectoryUser.
"""

from __future__ import annotations

import re
from typing import Any

from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorDatabase

from ...models.directory import DirectoryUser


def identity_filter(user_id: str) -> dict[str, Any]:
    """Match an identity by the key `_to_user` derives. SciCat stores `userId` (and `_id`)
    as ObjectIds, so the string form never matches them directly; `profile.id` only
    happens to equal it for local accounts (LDAP/OIDC put the IdP subject there)."""
    clauses: list[dict[str, Any]] = [{"userId": user_id}, {"profile.id": user_id}]
    if ObjectId.is_valid(user_id):
        oid = ObjectId(user_id)
        clauses += [{"userId": oid}, {"_id": oid}]
    return {"$or": clauses}


def _to_user(doc: dict[str, Any]) -> DirectoryUser:
    profile = doc.get("profile") or {}
    emails = profile.get("emails") or []
    email = profile.get("email") or (emails[0].get("value") if emails else "")
    return DirectoryUser(
        userId=str(doc.get("userId") or profile.get("id") or doc.get("_id")),
        username=profile.get("username", ""),
        displayName=profile.get("displayName", "") or profile.get("username", ""),
        email=email or "",
        accessGroups=[g for g in (profile.get("accessGroups") or [])],
        active=not doc.get("deactivated", False),
    )


class ScicatLocalDirectory:
    def __init__(self, scicat_db: AsyncIOMotorDatabase, collection: str = "UserIdentity") -> None:
        self.col = scicat_db[collection]

    async def search(self, query: str, limit: int = 25) -> list[DirectoryUser]:
        if query:
            rx = re.compile(re.escape(query), re.IGNORECASE)
            q: dict[str, Any] = {
                "$or": [
                    {"profile.username": rx},
                    {"profile.displayName": rx},
                    {"profile.email": rx},
                    {"profile.emails.value": rx},
                ]
            }
        else:
            q = {}
        cursor = self.col.find(q).limit(limit)
        return [_to_user(doc) async for doc in cursor]

    async def get(self, user_id: str) -> DirectoryUser | None:
        doc = await self.col.find_one(identity_filter(user_id))
        return _to_user(doc) if doc else None

    async def list(self, limit: int = 1000) -> list[DirectoryUser]:
        cursor = self.col.find({}).limit(limit)
        return [_to_user(doc) async for doc in cursor]

    async def display_names(self, usernames: list[str]) -> dict[str, str]:
        """Map each known username to its display name (falling back to the username);
        unknown usernames are left out."""
        if not usernames:
            return {}
        cursor = self.col.find(
            {"profile.username": {"$in": usernames}},
            {"profile.username": 1, "profile.displayName": 1},
        )
        names: dict[str, str] = {}
        async for doc in cursor:
            profile = doc.get("profile") or {}
            username = profile.get("username")
            if username:
                names[username] = profile.get("displayName") or username
        return names

    async def username_exists(self, username: str) -> bool:
        rx = re.compile(f"^{re.escape(username.strip())}$", re.IGNORECASE)
        return await self.col.find_one({"profile.username": rx}, {"_id": 1}) is not None

    async def is_active(self, user_id: str) -> bool:
        user = await self.get(user_id)
        return bool(user and user.active)
