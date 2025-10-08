from __future__ import annotations

import logging
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from app.api.routes.v1.auth import router as auth_router
from app.api.routes.v1.jobs import router as jobs_router
from app.api.routes.v1.webhooks import router as webhooks_router
from app.core.config import get_settings
from app.core.logging import request_id_var, setup_logging
from app.db.mongo import close_db_connection, ensure_indexes, get_db
from app.queues.redis_queue import close_redis_client, get_redis_client

_logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    setup_logging(settings.LOG_LEVEL)
    _logger.info("Starting %s with settings: %s", settings.APP_NAME, settings.model_dump_json(exclude={"AUTH_SECRET_KEY"}))
    await ensure_indexes()
    # Initialize Redis client if configured
    if settings.QUEUE_BACKEND == "redis":
        get_redis_client()
    yield
    await close_db_connection()
    if settings.QUEUE_BACKEND == "redis":
        await close_redis_client()
    _logger.info("Shutting down %s", settings.APP_NAME)


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title=settings.APP_NAME, lifespan=lifespan)

    # -- Middlewares --

    # Request ID Middleware
    @app.middleware("http")
    async def request_id_middleware(request: Request, call_next):
        # Get ID from header or generate a new one
        request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
        # Set the context variable
        request_id_var.set(request_id)
        _logger.debug(f"Request {request.method} {request.url.path} - ID: {request_id}")
        response = await call_next(request)
        # Add the ID to the response header
        response.headers["X-Request-ID"] = request_id
        return response

    # Session Middleware (for auth)
    if settings.AUTH_ENABLED:
        app.add_middleware(SessionMiddleware, secret_key=settings.AUTH_SECRET_KEY)

    # CORS Middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.APP_CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # -- Static files & templates --
    app.mount("/static", StaticFiles(directory="static"), name="static")
    templates = Jinja2Templates(directory="templates")

    # -- API Routes --
    app.include_router(jobs_router)
    app.include_router(webhooks_router)
    app.include_router(auth_router)

    # -- Web Routes --
    @app.get("/")
    async def root(request: Request):
        user = request.session.get("user")
        return templates.TemplateResponse("index.html", {"request": request, "user": user})

    # -- Health Checks --
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
            _logger.error("MongoDB health check failed: %s", e, exc_info=True)
            details["mongo"] = "error"
            ok = False

        # Redis check (only if configured)
        if settings.QUEUE_BACKEND == "redis":
            try:
                client = get_redis_client()
                if not await client.ping():
                    raise Exception("Redis ping failed")
                details["redis"] = "ok"
            except Exception as e:
                _logger.error("Redis health check failed: %s", e, exc_info=True)
                details["redis"] = "error"
                ok = False

        status_code = 200 if ok else 503
        return JSONResponse(
            status_code=status_code,
            content={"status": "ok" if ok else "degraded", "components": details},
        )

    return app


app = create_app()
