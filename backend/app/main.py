"""FastAPI application entry point."""

from fastapi import FastAPI

from app.api.analytics import router as analytics_router
from app.api.errors import register_error_handlers
from app.api.health import router as health_router
from app.api.imports import router as imports_router
from app.api.baskets import router as baskets_router
from app.api.forecast import router as forecast_router
from app.api.menu import router as menu_router
from app.api.products import router as products_router
from app.config import settings

app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    description=(
        "Analytics for independent hospitality businesses: revenue, timing, "
        "product and channel insight from point-of-sale exports."
    ),
)

register_error_handlers(app)

app.include_router(health_router)
app.include_router(imports_router)
app.include_router(analytics_router)
app.include_router(products_router)
app.include_router(baskets_router)
app.include_router(menu_router)
app.include_router(forecast_router)
