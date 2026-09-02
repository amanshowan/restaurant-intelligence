"""FastAPI application entry point."""

from fastapi import FastAPI

from app.api.analytics import router as analytics_router
from app.api.errors import register_error_handlers
from app.api.health import router as health_router
from app.api.imports import router as imports_router
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
