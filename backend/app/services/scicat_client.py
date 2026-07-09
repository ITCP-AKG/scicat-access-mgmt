"""HTTP client for the SciCat v3/v4 REST API (T007).

Resource type -> (list path, id field, patch path template). Verified against the
running SciCat v4.3.1 instance (research.md R3).
"""

from __future__ import annotations

from typing import Any

import httpx

# resourceType -> (collection path, id field used to PATCH)
RESOURCE_MAP: dict[str, tuple[str, str]] = {
    "dataset": ("datasets", "pid"),
    "origdatablock": ("origdatablocks", "id"),
    "proposal": ("proposals", "proposalId"),
    "sample": ("samples", "sampleId"),
    "instrument": ("instruments", "id"),
    "job": ("jobs", "id"),
}


class ScicatError(RuntimeError):
    pass


class ScicatClient:
    def __init__(self, base_url: str, token: str | None = None, timeout: float = 10.0) -> None:
        self.base_url = base_url.rstrip("/")
        self._token = token
        self._timeout = timeout

    def _headers(self, token: str | None = None) -> dict[str, str]:
        tok = token or self._token
        headers = {"Content-Type": "application/json"}
        if tok:
            headers["Authorization"] = f"Bearer {tok}"
        return headers

    async def whoami(self, token: str) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.get(f"{self.base_url}/auth/whoami", headers=self._headers(token))
            if resp.status_code != 200:
                raise ScicatError(f"whoami failed: {resp.status_code}")
            return resp.json()

    async def list_resources(
        self, resource_type: str, filter_: dict | None = None, limit: int = 50, skip: int = 0
    ) -> list[dict[str, Any]]:
        path, _ = RESOURCE_MAP[resource_type]
        params: dict[str, Any] = {"limit": limit, "skip": skip}
        if filter_:
            import json

            params["filter"] = json.dumps({"where": filter_, "limit": limit, "skip": skip})
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.get(
                f"{self.base_url}/{path}", headers=self._headers(), params=params
            )
            if resp.status_code != 200:
                raise ScicatError(f"list {resource_type} failed: {resp.status_code} {resp.text}")
            return resp.json()

    async def get_resource(self, resource_type: str, resource_id: str) -> dict[str, Any]:
        path, _ = RESOURCE_MAP[resource_type]
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.get(
                f"{self.base_url}/{path}/{resource_id}", headers=self._headers()
            )
            if resp.status_code != 200:
                raise ScicatError(f"get {resource_type}/{resource_id} failed: {resp.status_code}")
            return resp.json()

    async def patch_resource(
        self, resource_type: str, resource_id: str, body: dict[str, Any]
    ) -> dict[str, Any]:
        path, _ = RESOURCE_MAP[resource_type]
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.patch(
                f"{self.base_url}/{path}/{resource_id}", headers=self._headers(), json=body
            )
            if resp.status_code not in (200, 201):
                raise ScicatError(
                    f"patch {resource_type}/{resource_id} failed: {resp.status_code} {resp.text}"
                )
            return resp.json()
