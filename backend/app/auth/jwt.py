"""SciCat JWT validation (T008).

Authoritative validation is delegated to SciCat's `/auth/whoami` (works across SciCat
versions and yields the merged `currentGroups`). When a shared `JWT_SECRET` is configured
we additionally verify the signature locally as a fast fail-closed pre-check.
"""

from __future__ import annotations

import jwt as pyjwt
from pydantic import BaseModel

from ..config import Settings
from ..services.scicat_client import ScicatClient, ScicatError


class CurrentUser(BaseModel):
    userId: str
    username: str
    email: str = ""
    currentGroups: list[str] = []

    def is_admin(self, admin_groups: list[str]) -> bool:
        return any(g in self.currentGroups for g in admin_groups)


class AuthError(Exception):
    pass


async def validate_token(
    token: str, scicat: ScicatClient, settings: Settings
) -> CurrentUser:
    if not token:
        raise AuthError("missing token")

    if settings.jwt_secret:
        # Optional offline signature pre-check; ignore expiry skew issues here and let
        # whoami be the final authority on validity.
        try:
            pyjwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
        except pyjwt.InvalidSignatureError as exc:  # definitively forged
            raise AuthError("invalid token signature") from exc
        except pyjwt.PyJWTError:
            pass

    try:
        info = await scicat.whoami(token)
    except ScicatError as exc:
        raise AuthError("token rejected by SciCat") from exc

    return CurrentUser(
        userId=str(info.get("_id") or info.get("id") or ""),
        username=info.get("username", ""),
        email=info.get("email", ""),
        currentGroups=list(info.get("currentGroups") or []),
    )
