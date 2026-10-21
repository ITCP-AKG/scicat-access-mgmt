"""MongoDB clients for the app store and the SciCat (dacat) database (T006).

The app DB holds the access-management collections (groups, memberships, ...).
The SciCat DB is used read/write for the directory provider and projection.
"""

from __future__ import annotations

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase

from .config import Settings, get_settings


class Database:
    """Holds the Motor clients and exposes the two databases."""

    def __init__(self) -> None:
        self._app_client: AsyncIOMotorClient | None = None
        self._scicat_client: AsyncIOMotorClient | None = None
        self.app: AsyncIOMotorDatabase | None = None
        self.scicat: AsyncIOMotorDatabase | None = None

    async def connect(self, settings: Settings | None = None) -> None:
        settings = settings or get_settings()
        # tz_aware so datetimes round-trip as aware UTC instants (BSON stores naive
        # UTC otherwise), keeping all temporal comparisons against the UTC clock safe.
        self._app_client = AsyncIOMotorClient(settings.app_mongo_uri, tz_aware=True)
        self.app = self._app_client[settings.app_db_name]
        if settings.scicat_mongo_uri == settings.app_mongo_uri:
            self._scicat_client = self._app_client
        else:
            self._scicat_client = AsyncIOMotorClient(settings.scicat_mongo_uri, tz_aware=True)
        self.scicat = self._scicat_client[settings.scicat_db_name]
        await self.ensure_indexes()

    async def ensure_indexes(self) -> None:
        assert self.app is not None
        await self.app.groups.create_index("name", unique=True)
        # At most one non-ended membership per (group, user).
        await self.app.memberships.create_index(
            [("groupName", 1), ("userId", 1)],
            unique=True,
            partialFilterExpression={"status": {"$in": ["active", "scheduled"]}},
        )
        await self.app.resource_grants.create_index([("groupName", 1), ("resourceType", 1)])
        await self.app.transfer_records.create_index(
            [("batchId", 1), ("resourceType", 1), ("resourceId", 1)], unique=True
        )
        await self.app.audit_log.create_index([("at", -1)])
        await self.app.audit_log.create_index([("actor", 1)])
        await self.app.audit_log.create_index([("entityType", 1)])
        await self.migrate()

    async def migrate(self) -> None:
        """Idempotent data migrations, run at startup."""
        assert self.app is not None
        await migrate(self.app)

    def close(self) -> None:
        if self._app_client is not None:
            self._app_client.close()
        if self._scicat_client is not None and self._scicat_client is not self._app_client:
            self._scicat_client.close()


async def migrate(app_db: AsyncIOMotorDatabase) -> None:
    # Group category "proposal" was renamed to "administrative".
    await app_db.groups.update_many(
        {"category": "proposal"}, {"$set": {"category": "administrative"}}
    )
    # Instruments and jobs carry no ownerGroup/accessGroups in SciCat v4.3.1, so grants on
    # them could never be applied; retire any that were stored.
    await app_db.resource_grants.update_many(
        {"resourceType": {"$in": ["instrument", "job"]}, "status": {"$ne": "removed"}},
        {"$set": {"status": "removed", "endedBy": "migration"}},
    )


# Singleton used by the FastAPI app; tests inject their own Database instance.
db = Database()


def get_db() -> Database:
    return db
