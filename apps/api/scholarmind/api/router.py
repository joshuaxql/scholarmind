from fastapi import APIRouter

from scholarmind.api.routes.chat import router as chat_router
from scholarmind.api.routes.health import router as health_router
from scholarmind.api.routes.metrics import router as metrics_router
from scholarmind.api.routes.papers import router as papers_router
from scholarmind.api.routes.research import router as research_router
from scholarmind.api.routes.settings import router as settings_router

api_router = APIRouter()
api_router.include_router(health_router)
api_router.include_router(metrics_router)
api_router.include_router(papers_router, prefix="/api/v1")
api_router.include_router(chat_router, prefix="/api/v1")
api_router.include_router(research_router, prefix="/api/v1")
api_router.include_router(settings_router, prefix="/api/v1")
