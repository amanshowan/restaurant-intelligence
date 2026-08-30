"""Health endpoints.

Liveness and readiness are deliberately separate, because an orchestrator
acts on them differently:

  /health        liveness  — "is this process alive?"  Failure => restart me.
  /health/ready  readiness — "can I serve traffic?"    Failure => stop routing
                                                        traffic to me.

Collapsing them into one endpoint that checks the database is a common and
damaging mistake: a brief database outage would fail the liveness check, and
the orchestrator would respond by restarting every API container. That does
not fix the database, discards warm connection pools, and turns a recoverable
dependency blip into a full outage.
"""

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db
from app.schemas.health import LivenessResponse, ReadinessResponse

router = APIRouter(tags=["health"])


@router.get("/health", response_model=LivenessResponse)
def liveness() -> LivenessResponse:
    """Process-level check. Touches no dependencies, so it cannot fail
    because something downstream is unwell."""
    return LivenessResponse(status="ok", service=settings.app_name)


@router.get(
    "/health/ready",
    response_model=ReadinessResponse,
    responses={503: {"model": ReadinessResponse}},
)
def readiness(response: Response, db: Session = Depends(get_db)) -> ReadinessResponse:
    """Dependency check. Returns 503 when the database is unreachable.

    The status code matters as much as the body: load balancers and
    orchestrators route on the code, not on JSON they do not parse.
    """
    try:
        db.execute(text("SELECT 1"))
    except SQLAlchemyError:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return ReadinessResponse(status="degraded", database="unavailable")

    return ReadinessResponse(status="ready", database="ok")
