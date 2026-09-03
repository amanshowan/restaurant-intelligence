"""Shared API dependencies."""

from __future__ import annotations

from app.analytics.service import AnalyticsService
from app.db import SessionLocal
from app.forecasting.service import ForecastService
from app.nlq.executor import AnalyticsExecutor
from app.nlq.resolution import ProductResolver
from app.services.importer import SquareImportService


def get_import_service() -> SquareImportService:
    """The import service, injected so tests can substitute a session factory."""
    return SquareImportService(SessionLocal)


def get_analytics_service() -> AnalyticsService:
    """The analytics service, injected so tests can substitute a session factory."""
    return AnalyticsService(SessionLocal)


def get_forecast_service() -> ForecastService:
    """The forecast service, injected so tests can substitute a session factory."""
    return ForecastService(SessionLocal)


def get_analytics_executor() -> AnalyticsExecutor:
    """The M7 executor, built from the same services the HTTP routes use.

    Deliberately composed from `AnalyticsService` and `ForecastService` rather
    than given its own session factory for analytics: the AI layer must be a
    consumer of the existing business logic, not a second path to the data.
    """
    return AnalyticsExecutor(
        analytics=AnalyticsService(SessionLocal),
        forecasts=ForecastService(SessionLocal),
        resolver=ProductResolver(SessionLocal),
    )
