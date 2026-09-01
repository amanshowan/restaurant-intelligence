"""Shared API dependencies."""

from __future__ import annotations

from app.db import SessionLocal
from app.services.importer import SquareImportService


def get_import_service() -> SquareImportService:
    """The import service, injected so tests can substitute a session factory."""
    return SquareImportService(SessionLocal)
