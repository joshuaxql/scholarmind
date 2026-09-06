from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import structlog
import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from scholarmind.api.errors import register_exception_handlers
from scholarmind.api.router import api_router
from scholarmind.core.config import Environment, Settings, get_settings
from scholarmind.core.logging import configure_logging
from scholarmind.core.middleware import (
    RateLimitMiddleware,
    RequestContextMiddleware,
    SecurityHeadersMiddleware,
)
from scholarmind.core.rate_limit import RateLimiter
from scholarmind.db.session import Database
from scholarmind.services.arxiv_search import build_arxiv_search_client
from scholarmind.services.dispatch import build_dispatcher
from scholarmind.services.environment import EnvironmentService
from scholarmind.services.llm import build_llm_gateway
from scholarmind.services.paper_summary import build_briefing_analyzer
from scholarmind.services.provider_client import build_provider_client
from scholarmind.services.research_analysis import build_research_analyzer
from scholarmind.services.retrieval import build_retriever
from scholarmind.services.storage import build_object_store

logger = structlog.get_logger(__name__)


def create_app(app_settings: Settings | None = None) -> FastAPI:
    settings = app_settings or get_settings()
    configure_logging(settings.log_level, json_logs=settings.environment == Environment.PRODUCTION)
    database = Database(settings)
    rate_limiter = RateLimiter(settings)
    object_store = build_object_store(settings)
    provider_client = build_provider_client(settings)
    arxiv_search_client = build_arxiv_search_client(settings)
    retriever = build_retriever(settings, provider_client)
    llm_gateway = build_llm_gateway(settings, provider_client)
    research_analyzer = build_research_analyzer(settings, provider_client)
    briefing_analyzer = build_briefing_analyzer(settings, provider_client)

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        await application.state.environment_service.initialize()
        if settings.auto_create_schema:
            await database.create_schema()
        await object_store.ensure_ready()
        dispatcher = await build_dispatcher(settings)
        application.state.job_dispatcher = dispatcher
        logger.info("application_started", environment=settings.environment.value)
        try:
            yield
        finally:
            await dispatcher.close()
            await retriever.close()
            await llm_gateway.close()
            await arxiv_search_client.close()
            await provider_client.aclose()
            await object_store.close()
            await rate_limiter.close()
            await database.close()
            logger.info("application_stopped")

    application = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        lifespan=lifespan,
        docs_url="/docs" if settings.environment != Environment.PRODUCTION else None,
        redoc_url=None,
    )
    application.state.settings = settings
    application.state.environment_service = EnvironmentService()
    application.state.database = database
    application.state.rate_limiter = rate_limiter
    application.state.object_store = object_store
    application.state.retriever = retriever
    application.state.llm_gateway = llm_gateway
    application.state.arxiv_search_client = arxiv_search_client
    application.state.research_analyzer = research_analyzer
    application.state.briefing_analyzer = briefing_analyzer
    application.dependency_overrides[get_settings] = lambda: settings

    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "DELETE"],
        allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
    )
    application.add_middleware(SecurityHeadersMiddleware)
    application.add_middleware(RateLimitMiddleware, limiter=rate_limiter)
    application.add_middleware(RequestContextMiddleware)
    application.include_router(api_router)
    register_exception_handlers(application)
    return application


app = create_app()


def run() -> None:
    settings = get_settings()
    uvicorn.run(
        "scholarmind.main:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=settings.environment == Environment.DEVELOPMENT,
    )
