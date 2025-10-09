from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes.v1 import jobs, webhooks, auth
from app.core.config import get_settings
from app.core.logging import setup_logging
from app.db.mongo import connect_to_mongo, close_mongo_connection
from app.queues import shutdown_queue


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Context manager to handle startup and shutdown events."""
    setup_logging()
    _logger = logging.getLogger(__name__)
    _logger.info("Starting up...")
    await connect_to_mongo()
    yield
    _logger.info("Shutting down...")
    await shutdown_queue()
    await close_mongo_connection()


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title=settings.PROJECT_NAME,
        version=settings.PROJECT_VERSION,
        openapi_url=f"{settings.API_V1_STR}/openapi.json",
        lifespan=lifespan,
    )

    # Add CORS middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[origin.strip() for origin in settings.APP_CORS_ORIGINS.split(",") if origin.strip()],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # API V1 routes
    app.include_router(auth.router, prefix=settings.API_V1_STR, tags=["auth"])
    app.include_router(jobs.router, prefix=settings.API_V1_STR, tags=["jobs"])
    app.include_router(webhooks.router, prefix=settings.API_V1_STR, tags=["webhooks"])

    return app


app = create_app()
