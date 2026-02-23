from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from time import perf_counter

from fastapi import FastAPI, Request
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware
from starlette.responses import Response

from app.api.v1.router import api_router
from app.core.errors import add_exception_handlers, success_response
from app.core.logging import configure_logging
from app.core.settings import get_settings
import app.db.session as db_session
from app.db.session import init_db
from app.realtime import ConnectionManager, RealtimeDispatcher, RealtimePublisher

settings = get_settings()
configure_logging(debug=settings.debug)
logger = logging.getLogger(__name__)


def _open_db_session():
    if db_session.SessionLocal is None:
        raise RuntimeError("Database session factory is not configured")
    return db_session.SessionLocal()


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Application startup started")
    logger.debug("Initializing database schema")
    init_db()
    app.state.connection_manager = ConnectionManager(
        max_subscriptions_per_connection=settings.ws_max_subscriptions_per_connection
    )
    app.state.realtime_publisher = RealtimePublisher(app.state.connection_manager)
    app.state.realtime_dispatcher = RealtimeDispatcher(
        publisher=app.state.realtime_publisher,
        session_factory=_open_db_session,
        poll_interval_sec=settings.realtime_dispatcher_poll_ms / 1000.0,
        batch_size=settings.realtime_dispatcher_batch_size,
    )
    if settings.realtime_dispatcher_enabled:
        await app.state.realtime_dispatcher.start()
    logger.info("Application startup completed")
    yield
    if settings.realtime_dispatcher_enabled:
        await app.state.realtime_dispatcher.stop()
    logger.info("Application shutdown completed")


def create_app() -> FastAPI:
    logger.debug("Creating FastAPI app with API prefix: %s", settings.api_v1_prefix)
    app = FastAPI(
        title=settings.app_name,
        lifespan=lifespan,
        middleware=[
            Middleware(
                CORSMiddleware,
                allow_origins=settings.cors_origins,
                allow_credentials=True,
                allow_methods=["*"],
                allow_headers=["*"],
            )
        ],
    )
    logger.debug("CORS configured for origins: %s", settings.cors_origins)

    if settings.debug:
        @app.middleware("http")
        async def request_debug_logger(request: Request, call_next) -> Response:
            start = perf_counter()
            client_ip = request.client.host if request.client else "unknown"
            logger.debug("HTTP request started method=%s path=%s client_ip=%s", request.method, request.url.path, client_ip)
            response = await call_next(request)
            duration_ms = (perf_counter() - start) * 1000
            logger.debug(
                "HTTP request completed method=%s path=%s status=%s duration_ms=%.2f",
                request.method,
                request.url.path,
                response.status_code,
                duration_ms,
            )
            return response

    add_exception_handlers(app)
    app.include_router(api_router, prefix=settings.api_v1_prefix)
    logger.debug("API routers registered")

    @app.get("/health")
    def health_check():
        logger.debug("Health check called")
        return success_response({"ok": True})

    return app


app = create_app()
