"""FastAPI application entry point."""

from fastapi import FastAPI

from app.api.health import router as health_router
from app.config import settings

app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    description=(
        "Analytics for independent hospitality businesses: revenue, timing, "
        "product and channel insight from point-of-sale exports."
    ),
)

app.include_router(health_router)
