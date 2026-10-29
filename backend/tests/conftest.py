"""Test harness: in-memory Mongo, fake SciCat, injectable clock (T014)."""

from __future__ import annotations

import copy
import re
from datetime import datetime, timezone

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from mongomock_motor import AsyncMongoMockClient

from app.config import Settings
from app.context import AppContext
from app.main import create_app
from app.services.scicat_client import (
    RESOURCE_MAP,
    ScicatAuthError,
    ScicatClient,
    ScicatError,
    ScicatUnavailable,
)


class Clock:
    """Mutable clock so tests can advance time deterministically."""

    def __init__(self, start: datetime | None = None) -> None:
        self.value = start or datetime(2026, 1, 1, tzinfo=timezone.utc)

    def __call__(self) -> datetime:
        return self.value

    def set(self, value: datetime) -> None:
        self.value = value


# Fields SciCat v4.3.1 accepts in a PATCH, per resource type (forbidNonWhitelisted).
_OWNABLE = {"ownerGroup", "accessGroups", "instrumentGroup"}
PATCHABLE: dict[str, set[str]] = {
    "dataset": _OWNABLE | {"owner", "ownerEmail", "orcidOfOwner", "contactEmail"},
    "origdatablock": _OWNABLE,
    "proposal": _OWNABLE
    | {"email", "firstname", "lastname", "pi_email", "pi_firstname", "pi_lastname"}
    | {"title", "abstract", "startTime", "endTime"},
    "sample": _OWNABLE | {"owner"},
}


def _matches(doc: dict, where: dict) -> bool:
    """Tiny Mongo-ish matcher covering what the app sends: equality, $in, $or, $regex."""
    for key, cond in where.items():
        if key == "$or":
            if not any(_matches(doc, sub) for sub in cond):
                return False
            continue
        value = doc.get(key)
        if isinstance(cond, dict):
            if "$in" in cond:
                values = value if isinstance(value, list) else [value]
                if not any(v in cond["$in"] for v in values):
                    return False
            if "$regex" in cond:
                flags = re.IGNORECASE if "i" in cond.get("$options", "") else 0
                if value is None or not re.search(cond["$regex"], str(value), flags):
                    return False
        elif isinstance(value, list):
            if cond not in value:
                return False
        elif value != cond:
            return False
    return True


class FakeScicat(ScicatClient):
    """Stand-in SciCat client mimicking v4.3.1 semantics.

    Maps tokens to identities for auth and holds an in-memory resource store keyed by
    ``(resource_type, resource_id)``. Like SciCat it caps list pages at 100, rejects PATCH
    fields outside the type's whitelist and an empty ownerGroup. Set ``fail_ids`` to force a
    per-resource error (partial-failure tests); ``patches`` records every PATCH sent.
    """

    def __init__(self) -> None:
        super().__init__("http://fake")
        self.identities = {
            "admin-token": {
                "_id": "admin-id",
                "username": "admin",
                "email": "admin@catorga.dev",
                "currentGroups": ["admin", "globalaccess"],
            },
            "user-token": {
                "_id": "user-id",
                "username": "alice",
                "email": "alice@catorga.dev",
                "currentGroups": ["u.alice"],
            },
            "bob-token": {
                "_id": "bob-id",
                "username": "bob",
                "email": "bob@catorga.dev",
                "currentGroups": ["u.bob"],
            },
        }
        self.resources: dict[tuple[str, str], dict] = {}
        self.fail_ids: set[str] = set()
        self.fail_patch_ids: set[str] = set()  # GET works, PATCH is refused (503)
        self.patches: list[tuple[str, str, dict]] = []
        self.whoami_calls = 0
        self.identity_col = None  # set by the ctx fixture

    async def whoami(self, token: str):
        self.whoami_calls += 1
        if token not in self.identities:
            raise ScicatAuthError("unknown token", 401)
        info = dict(self.identities[token])
        # Like SciCat's JwtStrategy: currentGroups are re-read from the stored identity on
        # every request (users without a stored identity keep their static groups).
        if self.identity_col is not None:
            doc = await self.identity_col.find_one({"userId": info["_id"]})
            if doc is not None:
                info["currentGroups"] = list(doc["profile"].get("accessGroups") or [])
        return info

    def seed_resource(self, resource_type: str, resource_id: str, **fields) -> None:
        id_field = RESOURCE_MAP[resource_type][1]
        self.resources[(resource_type, resource_id)] = {id_field: resource_id, **fields}

    async def get_resource(self, resource_type: str, resource_id: str):
        if resource_id in self.fail_ids:
            raise ScicatError(f"forced failure for {resource_id}")
        doc = self.resources.get((resource_type, resource_id))
        if doc is None:
            raise ScicatError(f"get {resource_type}/{resource_id} failed: 404", 404)
        return copy.deepcopy(doc)

    async def patch_resource(self, resource_type: str, resource_id: str, body: dict):
        if resource_id in self.fail_ids:
            raise ScicatError(f"forced failure for {resource_id}")
        if resource_id in self.fail_patch_ids:
            raise ScicatUnavailable(f"patch {resource_type}/{resource_id} failed: 503", 503)
        key = (resource_type, resource_id)
        if key not in self.resources:
            raise ScicatError(f"patch {resource_type}/{resource_id} failed: 404", 404)
        unknown = set(body) - PATCHABLE[resource_type]
        if unknown:
            raise ScicatError(f"patch {resource_type}: property {sorted(unknown)} should not exist", 400)
        if "ownerGroup" in body and not body["ownerGroup"]:
            raise ScicatError("patch: ownerGroup should not be empty", 400)
        self.patches.append((resource_type, resource_id, copy.deepcopy(body)))
        self.resources[key].update(copy.deepcopy(body))
        return copy.deepcopy(self.resources[key])

    async def create_resource(self, resource_type: str, body: dict):
        rid = body[RESOURCE_MAP[resource_type][1]]
        if (resource_type, rid) in self.resources:
            raise ScicatError(f"create {resource_type} failed: 409 duplicate {rid}", 409)
        self.resources[(resource_type, rid)] = copy.deepcopy(body)
        return copy.deepcopy(body)

    async def list_resources(
        self, resource_type, where=None, *, limit=50, skip=0, order=None
    ):
        docs = [
            copy.deepcopy(doc)
            for (rtype, _rid), doc in self.resources.items()
            if rtype == resource_type and _matches(doc, where or {})
        ]
        limit = min(limit, 100)  # SciCat never returns more than its page cap here
        return docs[skip : skip + limit]


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest_asyncio.fixture
async def ctx(clock: Clock) -> AppContext:
    client = AsyncMongoMockClient(tz_aware=True)
    app_db = client["app"]
    scicat_db = client["dacat"]
    # Seed a couple of SciCat identities used by the directory + projection.
    await scicat_db["UserIdentity"].insert_many(
        [
            {
                "userId": "user-id",
                "provider": "local",
                "profile": {
                    "id": "user-id",
                    "username": "alice",
                    "displayName": "Alice Researcher",
                    "email": "alice@catorga.dev",
                    "accessGroups": ["u.alice", "globalaccess"],
                },
            },
            {
                "userId": "bob-id",
                "provider": "local",
                "profile": {
                    "id": "bob-id",
                    "username": "bob",
                    "displayName": "Bob Postdoc",
                    "email": "bob@catorga.dev",
                    "accessGroups": ["u.bob"],
                },
            },
        ]
    )
    settings = Settings(admin_groups=["admin"], personal_group_template="u.{username}")
    scicat = FakeScicat()
    scicat.identity_col = scicat_db["UserIdentity"]
    return AppContext(
        app_db=app_db,
        scicat_db=scicat_db,
        scicat=scicat,
        settings=settings,
        clock=clock,
    )


@pytest_asyncio.fixture
async def client(ctx: AppContext):
    app = create_app()
    app.state.ctx = ctx  # bypass lifespan; ASGITransport does not run startup events
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.fixture
def admin_headers() -> dict[str, str]:
    return {"Authorization": "Bearer admin-token"}


@pytest.fixture
def user_headers() -> dict[str, str]:
    return {"Authorization": "Bearer user-token"}


@pytest.fixture
def bob_headers() -> dict[str, str]:
    return {"Authorization": "Bearer bob-token"}
