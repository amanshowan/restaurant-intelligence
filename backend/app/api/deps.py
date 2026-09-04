"""Shared API dependencies."""

from __future__ import annotations

from app.analytics.service import AnalyticsService
from app.config import settings
from app.db import SessionLocal
from app.forecasting.service import ForecastService
from app.nlq.context import ContextBuilder
from app.nlq.executor import AnalyticsExecutor
from app.nlq.orchestrator import QuestionService
from app.nlq.providers import build_llm_client
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


def get_question_service() -> QuestionService:
    """The M7 question service.

    The provider client is built HERE, per request, rather than at import.
    That is what makes a missing API key a 503 on one endpoint instead of a
    failure to start: `build_llm_client` raises `LLMNotConfigured`, the route
    maps it, and every other endpoint is untouched.
    """
    resolver = ProductResolver(SessionLocal)
    forecasts = ForecastService(SessionLocal)
    return QuestionService(
        llm=build_llm_client(),
        executor=AnalyticsExecutor(
            analytics=AnalyticsService(SessionLocal),
            forecasts=forecasts,
            resolver=resolver,
        ),
        context=ContextBuilder(resolver, forecasts),
        max_plan_attempts=settings.llm_max_plan_attempts,
        planner_effort=settings.llm_planner_effort,
        answer_effort=settings.llm_answer_effort,
    )
