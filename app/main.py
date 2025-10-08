from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse  # explicit JSONResponse

from app.core.config import get_settings
from app.core.logging import setup_logging
from app.db.mongo import ensure_indexes, get_db
from app.api.routes.v1.jobs import router as jobs_router
from app.api.routes.v1.webhooks import router as webhooks_router
from redis.asyncio import from_url as redis_from_url
from urllib.parse import urlparse
from motor.motor_asyncio import AsyncIOMotorClient


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    setup_logging(settings.LOG_LEVEL)
    logging.getLogger(__name__).info("Starting %s", settings.APP_NAME)
    await ensure_indexes()
    yield
    logging.getLogger(__name__).info("Shutting down %s", settings.APP_NAME)


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title=settings.APP_NAME, lifespan=lifespan)

    # CORS
    if settings.cors_origins == ["*"]:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )
    else:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origins,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    # Routes
    app.include_router(jobs_router)
    app.include_router(webhooks_router)

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    @app.get("/healthz")
    async def healthz():
        ok = True
        details = {}

        # Mongo check
        try:
            db = await get_db()
            await db.command("ping")
            details["mongo"] = "ok"
        except Exception as e:
            details["mongo"] = f"error: {e}"
            ok = False

        # Redis check (only if configured)
        if settings.QUEUE_BACKEND == "redis" and settings.REDIS_URL:
            try:
                client = redis_from_url(settings.REDIS_URL)
                await client.ping()
                details["redis"] = "ok"
            except Exception as e:
                details["redis"] = f"error: {e}"
                ok = False

        status_code = 200 if ok else 503
        return JSONResponse(status_code=status_code, content={"status": "ok" if ok else "degraded", "components": details})

    return app


app = create_app()
