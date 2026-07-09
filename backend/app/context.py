"""Application context: builds and holds shared services (T011).

Stored on `app.state.ctx` at startup. Services pull their dependencies from here so
tests can construct an AppContext with a fake SciCat client + in-memory Mongo.
"""

from __future__ import annotations

from typing import Callable

from motor.motor_asyncio import AsyncIOMotorDatabase

from .config import Settings, get_settings
from .services.audit import AuditService
from .services.directory.scicat_local import ScicatLocalDirectory
from .services.scicat_client import ScicatClient
from .util import utcnow


class AppContext:
    def __init__(
        self,
        *,
        app_db: AsyncIOMotorDatabase,
        scicat_db: AsyncIOMotorDatabase,
        scicat: ScicatClient,
        settings: Settings | None = None,
        clock: Callable[[], "object"] = utcnow,
    ) -> None:
        self.settings = settings or get_settings()
        self.app_db = app_db
        self.scicat_db = scicat_db
        self.scicat = scicat
        self.clock = clock
        self.audit = AuditService(app_db)
        self.directory = ScicatLocalDirectory(scicat_db, self.settings.scicat_identity_collection)

    def now(self):
        return self.clock()
