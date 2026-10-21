"""SciCat JWT validation (T008).

Authoritative validation is delegated to SciCat's `/auth/whoami` (works across SciCat
versions and yields the merged `currentGroups`, which SciCat re-reads from the user's
identity on every request). Results are cached briefly per token. When a shared
`JWT_SECRET` is configured we additionally verify the signature locally as a fast
fail-closed pre-check.
"""

from __future__ import annotations

import hashlib
import time

import jwt as pyjwt
from pydantic import BaseModel

from ..config import Settings
from ..services.scicat_client import ScicatAuthError, ScicatClient, ScicatUnavailable


class CurrentUser(BaseModel):
    userId: str
    username: str
    email: str = ""
    currentGroups: list[str] = []
    token: str = ""

    def is_admin(self, admin_groups: list[str]) -> bool:
        return any(g in self.currentGroups for g in admin_groups)


class AuthError(Exception):
    """The token is missing, forged, expired or rejected (HTTP 401)."""


class AuthUnavailable(Exception):
    """SciCat could not confirm the token (HTTP 503)."""


class WhoamiCache:
    """Tiny TTL cache of whoami answers keyed by a hash of the token."""

    def __init__(self, ttl_seconds: float) -> None:
        self.ttl = ttl_seconds
        self._entries: dict[str, tuple[float, dict]] = {}

    @staticmethod
    def _key(token: str) -> str:
        return hashlib.sha256(token.encode()).hexdigest()

    def get(self, token: str) -> dict | None:
        entry = self._entries.get(self._key(token))
        if entry and entry[0] > time.monotonic():
            return entry[1]
        return None

    def put(self, token: str, info: dict) -> None:
        if self.ttl <= 0:
            return
        now = time.monotonic()
        if len(self._entries) > 1000:
            self._entries = {k: v for k, v in self._entries.items() if v[0] > now}
        self._entries[self._key(token)] = (now + self.ttl, info)

    def drop(self, token: str) -> None:
        self._entries.pop(self._key(token), None)


async def validate_token(
    token: str,
    scicat: ScicatClient,
    settings: Settings,
    cache: WhoamiCache | None = None,
) -> CurrentUser:
    if not token:
        raise AuthError("missing token")

    if settings.jwt_secret:
        # Offline signature pre-check; expiry is left to whoami as the final authority.
        try:
            pyjwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
        except pyjwt.InvalidSignatureError as exc:  # definitively forged
            raise AuthError("invalid token signature") from exc
        except pyjwt.PyJWTError:
            pass

    info = cache.get(token) if cache else None
    if info is None:
        try:
            info = await scicat.whoami(token)
        except ScicatAuthError as exc:
            raise AuthError("token rejected by SciCat") from exc
        except ScicatUnavailable as exc:
            raise AuthUnavailable(f"SciCat unavailable: {exc}") from exc
        if cache:
            cache.put(token, info)

    return CurrentUser(
        userId=str(info.get("_id") or info.get("id") or ""),
        username=info.get("username", ""),
        email=info.get("email", "") or "",
        currentGroups=[g for g in (info.get("currentGroups") or []) if g],
        token=token,
    )
