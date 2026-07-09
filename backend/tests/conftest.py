"""Test harness: in-memory Mongo, fake SciCat, injectable clock (T014)."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from mongomock_motor import AsyncMongoMockClient

from app.config import Settings
from app.context import AppContext
from app.main import create_app
from app.services.scicat_client import ScicatClient


class Clock:
    """Mutable clock so tests can advance time deterministically."""

    def __init__(self, start: datetime | None = None) -> None:
        self.value = start or datetime(2026, 1, 1, tzinfo=timezone.utc)

    def __call__(self) -> datetime:
        return self.value

    def set(self, value: datetime) -> None:
        self.value = value


class FakeScicat(ScicatClient):
    """Stand-in SciCat client.

    Maps tokens to identities for auth and holds an in-memory resource store keyed by
    ``(resource_type, resource_id)`` so grant apply/remove can read-modify-write without a
    live SciCat. Set ``fail_ids`` to force a per-resource error (partial-failure tests).
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
        }
        self.resources: dict[tuple[str, str], dict] = {}
        self.fail_ids: set[str] = set()

    async def whoami(self, token: str):
        if token not in self.identities:
            from app.services.scicat_client import ScicatError

            raise ScicatError("unknown token")
        return self.identities[token]

    def seed_resource(self, resource_type: str, resource_id: str, **fields) -> None:
        from app.services.scicat_client import RESOURCE_MAP

        id_field = RESOURCE_MAP[resource_type][1]
        self.resources[(resource_type, resource_id)] = {id_field: resource_id, **fields}

    async def get_resource(self, resource_type: str, resource_id: str):
        from app.services.scicat_client import ScicatError

        if resource_id in self.fail_ids:
            raise ScicatError(f"forced failure for {resource_id}")
        doc = self.resources.get((resource_type, resource_id))
        if doc is None:
            raise ScicatError(f"get {resource_type}/{resource_id} failed: 404")
        return dict(doc)

    async def patch_resource(self, resource_type: str, resource_id: str, body: dict):
        from app.services.scicat_client import ScicatError

        key = (resource_type, resource_id)
        if key not in self.resources:
            raise ScicatError(f"patch {resource_type}/{resource_id} failed: 404")
        self.resources[key].update(body)
        return dict(self.resources[key])

    async def list_resources(self, resource_type, filter_=None, limit=50, skip=0):
        docs = [
            dict(doc)
            for (rtype, _rid), doc in self.resources.items()
            if rtype == resource_type
        ]
        if filter_:
            docs = [d for d in docs if all(d.get(k) == v for k, v in filter_.items())]
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
    settings = Settings(admin_groups=["admin"])
    return AppContext(
        app_db=app_db,
        scicat_db=scicat_db,
        scicat=FakeScicat(),
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
