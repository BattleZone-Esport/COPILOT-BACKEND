from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.sessions import SessionMiddleware
from fastapi.responses import JSONResponse
from fastapi.exception_handlers import http_exception_handler

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

    # Add session middleware (MUST be added before CORS)
    app.add_middleware(
        SessionMiddleware,
        secret_key=settings.AUTH_SECRET_KEY,
        same_site="lax",
        https_only=settings.ENVIRONMENT == "production",
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
    app.include_router(auth.router, prefix=f"{settings.API_V1_STR}/auth", tags=["auth"])
    app.include_router(jobs.router, prefix=f"{settings.API_V1_STR}/jobs", tags=["jobs"])
    app.include_router(webhooks.router, prefix=f"{settings.API_V1_STR}/webhooks", tags=["webhooks"])
    
    # Health check endpoint
    @app.get("/healthz")
    async def health_check():
        """Health check endpoint for monitoring and load balancers."""
        return JSONResponse(
            content={
                "status": "healthy",
                "service": settings.PROJECT_NAME,
                "version": settings.PROJECT_VERSION,
                "environment": settings.ENVIRONMENT
            },
            status_code=200
        )
    
    # Root endpoint
    @app.get("/")
    async def root():
        """Root endpoint with basic API information."""
        return {
            "name": settings.PROJECT_NAME,
            "version": settings.PROJECT_VERSION,
            "docs": "/docs",
            "health": "/healthz"
        }
    
    # Global exception handler
    @app.exception_handler(HTTPException)
    async def custom_http_exception_handler(request: Request, exc: HTTPException):
        return await http_exception_handler(request, exc)
    
    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception):
        """Global exception handler for unhandled exceptions."""
        _logger = logging.getLogger(__name__)
        _logger.exception("Unhandled exception: %s", exc)
        return JSONResponse(
            status_code=500,
            content={
                "detail": "An internal server error occurred",
                "type": "internal_server_error"
            }
        )

    return app


app = create_app()
