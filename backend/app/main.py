"""FastAPI application factory (T011)."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api.router import api_router
from .config import get_settings
from .context import AppContext
from .db import db


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    await db.connect(settings)
    from .services.scicat_client import ScicatClient

    app.state.ctx = AppContext(
        app_db=db.app,
        scicat_db=db.scicat,
        scicat=ScicatClient(settings.scicat_base_url),
        settings=settings,
    )
    from .scheduler.jobs import Scheduler

    scheduler = Scheduler(app.state.ctx)
    scheduler.start()
    app.state.scheduler = scheduler
    yield
    scheduler.stop()
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
