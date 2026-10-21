"""FastAPI application factory (T011)."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api.router import api_router
from .config import get_settings
from .context import AppContext
from .db import db
from .scheduler.jobs import Scheduler
from .services.scicat_client import ScicatClient

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    await db.connect(settings)
    if not (settings.scicat_service_username or settings.scicat_service_token):
        logger.warning(
            "No SciCat service account configured (SCICAT_SERVICE_USERNAME/PASSWORD or "
            "SCICAT_SERVICE_TOKEN): resource grants, browsing and transfers will fail."
        )
    scicat = ScicatClient(
        settings.scicat_base_url,
        username=settings.scicat_service_username,
        password=settings.scicat_service_password,
        token=settings.scicat_service_token,
        timeout=settings.scicat_timeout_seconds,
    )
    app.state.ctx = AppContext(
        app_db=db.app, scicat_db=db.scicat, scicat=scicat, settings=settings
    )
    scheduler = Scheduler(app.state.ctx)
    scheduler.start()
    app.state.scheduler = scheduler
    try:
        yield
    finally:
        scheduler.stop()
        await scicat.aclose()
        db.close()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="SciCat Access Management", version="1.0.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    app.include_router(api_router)
    return app


app = create_app()
