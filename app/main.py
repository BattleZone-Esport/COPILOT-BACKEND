from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from app.core.config import get_settings
from app.core.logging import setup_logging
from app.db.mongo import ensure_indexes, get_db, close_db_connection
from app.api.routes.v1.jobs import router as jobs_router
from app.api.routes.v1.webhooks import router as webhooks_router
from app.api.routes.v1.auth import router as auth_router
from redis.asyncio import from_url as redis_from_url

_logger = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    setup_logging(settings.LOG_LEVEL)
    _logger.info("Starting %s", settings.APP_NAME)
    await ensure_indexes()
    yield
    await close_db_connection()
    _logger.info("Shutting down %s", settings.APP_NAME)

def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title=settings.APP_NAME, lifespan=lifespan)

    # Middlewares
    if settings.AUTH_SECRET_KEY:
        app.add_middleware(SessionMiddleware, secret_key=settings.AUTH_SECRET_KEY)
    else:
        _logger.warning("AUTH_SECRET_KEY not set, session middleware not loaded")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Static files & templates
    app.mount("/static", StaticFiles(directory="static"), name="static")
    templates = Jinja2Templates(directory="templates")

    # Routes
    app.include_router(jobs_router)
    app.include_router(webhooks_router)
    app.include_router(auth_router)

    @app.get("/")
    async def root(request: Request):
        return templates.TemplateResponse("index.html", {"request": request, "user": request.session.get('user')})

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
            _logger.error("MongoDB health check failed: %s", e)
            details["mongo"] = "error"
            ok = False

        # Redis check (only if configured)
        if settings.QUEUE_BACKEND == "redis" and settings.REDIS_URL:
            try:
                client = redis_from_url(settings.REDIS_URL, socket_connect_timeout=2)
                await client.ping()
                details["redis"] = "ok"
                await client.close()
            except Exception as e:
                _logger.error("Redis health check failed: %s", e)
                details["redis"] = "error"
                ok = False

        status_code = 200 if ok else 503
        return JSONResponse(status_code=status_code, content={"status": "ok" if ok else "degraded", "components": details})

    return app

app = create_app()
