"""HTTP client for the SciCat v3/v4 REST API (T007).

Verified against the SciCat backend-next v4.3.1 sources (research.md R3):
- list endpoints read a JSON filter ``{"where": ..., "limits": {"limit", "skip", "order"}}``
  (default limit 100); the query parameter is ``filters`` for proposals, ``filter`` otherwise;
- resource ids are path parameters and must be URL-encoded (dataset PIDs contain ``/``);
- only datasets, origdatablocks, proposals and samples carry ownerGroup/accessGroups
  (instruments and jobs do not, and PATCH rejects unknown fields).

All resource calls run as a configured functional (service) account; the app enforces its
own authorization on top. ``whoami`` is the only call made with a caller's token.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import AsyncIterator
from typing import Any
from urllib.parse import quote

import httpx

logger = logging.getLogger(__name__)

# resourceType -> (collection path, id field)
RESOURCE_MAP: dict[str, tuple[str, str]] = {
    "dataset": ("datasets", "pid"),
    "origdatablock": ("origdatablocks", "_id"),
    "proposal": ("proposals", "proposalId"),
    "sample": ("samples", "sampleId"),
}

# Name of the list endpoint's JSON-filter query parameter (differs per controller).
_FILTER_PARAM: dict[str, str] = {"proposal": "filters"}

# SciCat's own page-size default; also the page size used when iterating.
PAGE_SIZE = 100


def resource_id(resource_type: str, doc: dict[str, Any]) -> str:
    """The identifier of a SciCat resource document, as used in its PATCH route."""
    id_field = RESOURCE_MAP[resource_type][1]
    value = doc.get(id_field)
    if value is None and id_field == "_id":
        value = doc.get("id")
    return str(value) if value is not None else ""


class ScicatError(RuntimeError):
    """A SciCat request failed (bad request, not found, forbidden, ...)."""

    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


class ScicatAuthError(ScicatError):
    """A caller's token was rejected by SciCat."""


class ScicatUnavailable(ScicatError):
    """SciCat could not be reached or answered with a server error."""


class ScicatClient:
    def __init__(
        self,
        base_url: str,
        *,
        username: str | None = None,
        password: str | None = None,
        token: str | None = None,
        timeout: float = 10.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self._username = username
        self._password = password
        self._static_token = token
        self._timeout = timeout
        self._http: httpx.AsyncClient | None = None
        self._token: str | None = None
        self._token_expires: float = 0.0
        self._login_lock = asyncio.Lock()

    # ---- plumbing ----

    def _client(self) -> httpx.AsyncClient:
        if self._http is None:
            self._http = httpx.AsyncClient(base_url=self.base_url, timeout=self._timeout)
        return self._http

    async def aclose(self) -> None:
        if self._http is not None:
            await self._http.aclose()
            self._http = None

    async def _send(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        try:
            resp = await self._client().request(method, path, **kwargs)
        except httpx.HTTPError as exc:
            raise ScicatUnavailable(f"{method} {path}: {exc.__class__.__name__}: {exc}") from exc
        if resp.status_code >= 500:
            raise ScicatUnavailable(
                f"{method} {path} failed: {resp.status_code} {resp.text[:300]}", resp.status_code
            )
        return resp

    async def _service_token(self, *, force: bool = False) -> str | None:
        if self._static_token:
            return self._static_token
        if not self._username:
            return None
        if not force and self._token and time.monotonic() < self._token_expires:
            return self._token
        async with self._login_lock:
            if not force and self._token and time.monotonic() < self._token_expires:
                return self._token
            return await self._login()

    async def _login(self) -> str | None:
        resp = await self._send(
            "POST", "/auth/login", json={"username": self._username, "password": self._password}
        )
        if resp.status_code not in (200, 201):
            raise ScicatError(
                f"service account login failed: {resp.status_code}", resp.status_code
            )
        data = resp.json()
        self._token = data.get("access_token") or data.get("id")
        expires_in = float(data.get("expires_in") or 3600)
        # renew a minute early (or halfway, for very short-lived tokens)
        self._token_expires = time.monotonic() + max(expires_in - 60, expires_in / 2)
        return self._token

    async def _authed(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        token = await self._service_token()
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        resp = await self._send(method, path, headers=headers, **kwargs)
        if resp.status_code == 401 and self._username and not self._static_token:
            token = await self._service_token(force=True)
            resp = await self._send(
                method, path, headers={"Authorization": f"Bearer {token}"}, **kwargs
            )
        return resp

    @staticmethod
    def _item_path(resource_type: str, rid: str) -> str:
        path, _ = RESOURCE_MAP[resource_type]
        return f"/{path}/{quote(rid, safe='')}"

    # ---- caller identity ----

    async def whoami(self, token: str) -> dict[str, Any]:
        resp = await self._send(
            "GET", "/auth/whoami", headers={"Authorization": f"Bearer {token}"}
        )
        if resp.status_code in (401, 403):
            raise ScicatAuthError(f"whoami rejected: {resp.status_code}", resp.status_code)
        if resp.status_code != 200:
            raise ScicatUnavailable(f"whoami failed: {resp.status_code}", resp.status_code)
        data = resp.json()
        if not isinstance(data, dict) or not (data.get("_id") or data.get("id")):
            # SciCat answers 200 with an empty body for anonymous callers
            raise ScicatAuthError("whoami returned no identity", resp.status_code)
        return data

    # ---- resources ----

    async def list_resources(
        self,
        resource_type: str,
        where: dict[str, Any] | None = None,
        *,
        limit: int = 50,
        skip: int = 0,
        order: str | None = None,
    ) -> list[dict[str, Any]]:
        path, _ = RESOURCE_MAP[resource_type]
        limits: dict[str, Any] = {"limit": limit, "skip": skip}
        if order:
            limits["order"] = order
        param = _FILTER_PARAM.get(resource_type, "filter")
        params = {param: json.dumps({"where": where or {}, "limits": limits})}
        resp = await self._authed("GET", f"/{path}", params=params)
        if resp.status_code != 200:
            raise ScicatError(
                f"list {resource_type} failed: {resp.status_code} {resp.text[:300]}",
                resp.status_code,
            )
        return resp.json()

    async def iter_resources(
        self, resource_type: str, where: dict[str, Any] | None = None
    ) -> AsyncIterator[dict[str, Any]]:
        """Yield every matching resource, paging through SciCat's capped list endpoint."""
        id_field = RESOURCE_MAP[resource_type][1]
        skip = 0
        while True:
            page = await self.list_resources(
                resource_type, where, limit=PAGE_SIZE, skip=skip, order=f"{id_field}:asc"
            )
            for doc in page:
                yield doc
            if len(page) < PAGE_SIZE:
                return
            skip += PAGE_SIZE

    async def get_resource(self, resource_type: str, rid: str) -> dict[str, Any]:
        resp = await self._authed("GET", self._item_path(resource_type, rid))
        if resp.status_code != 200 or not resp.content:
            raise ScicatError(
                f"get {resource_type}/{rid} failed: {resp.status_code}", resp.status_code
            )
        return resp.json()

    async def patch_resource(
        self, resource_type: str, rid: str, body: dict[str, Any]
    ) -> dict[str, Any]:
        resp = await self._authed("PATCH", self._item_path(resource_type, rid), json=body)
        if resp.status_code not in (200, 201):
            raise ScicatError(
                f"patch {resource_type}/{rid} failed: {resp.status_code} {resp.text[:300]}",
                resp.status_code,
            )
        return resp.json()

    async def create_resource(self, resource_type: str, body: dict[str, Any]) -> dict[str, Any]:
        path, _ = RESOURCE_MAP[resource_type]
        resp = await self._authed("POST", f"/{path}", json=body)
        if resp.status_code not in (200, 201):
            raise ScicatError(
                f"create {resource_type} failed: {resp.status_code} {resp.text[:300]}",
                resp.status_code,
            )
        return resp.json()
