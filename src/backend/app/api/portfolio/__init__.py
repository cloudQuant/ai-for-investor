from fastapi import APIRouter

from app.api.portfolio.api import router as api_router
from app.api.portfolio.compositions import router as compositions_router
from app.api.portfolio.ledger import router as ledger_router
from app.api.portfolio.analytics_tasks import router as analytics_tasks_router

router = APIRouter()
router.include_router(api_router, prefix="/portfolio", tags=["Portfolio"])
router.include_router(compositions_router)
router.include_router(ledger_router)
router.include_router(analytics_tasks_router)

__all__ = ["router"]
