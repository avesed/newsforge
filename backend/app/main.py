"""NewsForge application entry point."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import get_settings
from app.db.redis import close_redis


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan: startup and shutdown."""
    settings = get_settings()

    # Startup
    from app.db.database import get_engine

    get_engine()  # Initialize engine

    # Start event checker background task
    from app.pipeline.orchestrator import start_event_checker
    start_event_checker()

    yield

    # Shutdown
    from app.pipeline.orchestrator import stop_event_checker
    await stop_event_checker()

    from app.content.fetcher import shutdown_crawler
    await shutdown_crawler()
    await close_redis()


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        description="Universal news aggregation and analysis platform",
        lifespan=lifespan,
        docs_url="/api/docs" if settings.debug else None,
        redoc_url="/api/redoc" if settings.debug else None,
    )

    # CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # --- Public API v1 ---
    from app.api.v1 import health as health_router
    from app.api.v1 import articles as articles_router
    from app.api.v1 import categories as categories_router
    from app.api.v1 import auth as auth_router
    from app.api.v1 import feeds as feeds_router
    from app.api.v1 import search as search_router
    from app.api.v1 import streaming as streaming_router
    from app.api.v1 import bookmarks as bookmarks_router
    from app.api.v1 import subscriptions as subscriptions_router

    app.include_router(health_router.router, prefix="/api/v1")
    app.include_router(articles_router.router, prefix="/api/v1")
    app.include_router(categories_router.router, prefix="/api/v1")
    app.include_router(auth_router.router, prefix="/api/v1")
    app.include_router(feeds_router.router, prefix="/api/v1")
    app.include_router(search_router.router, prefix="/api/v1")
    app.include_router(streaming_router.router, prefix="/api/v1")
    app.include_router(bookmarks_router.router, prefix="/api/v1")
    app.include_router(subscriptions_router.router, prefix="/api/v1")

    from app.api.v1 import events as events_router

    app.include_router(events_router.router, prefix="/api/v1")

    from app.api.v1 import stories as stories_router

    app.include_router(stories_router.router, prefix="/api/v1")

    from app.api.v1 import reading_history as reading_history_router

    app.include_router(reading_history_router.router, prefix="/api/v1")

    from app.api.v1 import export as export_router
    from app.api.v1 import webhooks as webhooks_router

    app.include_router(export_router.router, prefix="/api/v1")
    app.include_router(webhooks_router.router, prefix="/api/v1")

    # --- Admin API ---
    from app.api.admin import pipeline as admin_pipeline
    from app.api.admin import sources as admin_sources
    from app.api.admin import consumers as admin_consumers
    from app.api.admin import stats as admin_stats
    from app.api.admin import llm as admin_llm

    app.include_router(admin_pipeline.router, prefix="/api/v1")
    app.include_router(admin_sources.router, prefix="/api/v1")
    app.include_router(admin_consumers.router, prefix="/api/v1")
    app.include_router(admin_stats.router, prefix="/api/v1")
    app.include_router(admin_llm.router, prefix="/api/v1")

    # --- Internal API (machine consumers) ---
    from app.api.internal import api as internal_api

    app.include_router(internal_api.router, prefix="/api")

    return app


app = create_app()
