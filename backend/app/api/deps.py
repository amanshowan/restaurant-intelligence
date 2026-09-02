"""Shared API dependencies."""

from __future__ import annotations

from app.analytics.service import AnalyticsService
from app.db import SessionLocal
from app.services.importer import SquareImportService


def get_import_service() -> SquareImportService:
    """The import service, injected so tests can substitute a session factory."""
    return SquareImportService(SessionLocal)


def get_analytics_service() -> AnalyticsService:
    """The analytics service, injected so tests can substitute a session factory."""
    return AnalyticsService(SessionLocal)
