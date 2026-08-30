"""Response schemas for the health endpoints."""

from typing import Literal

from pydantic import BaseModel


class LivenessResponse(BaseModel):
    """Reports that the process is running and able to serve a request."""

    status: Literal["ok"]
    service: str


class ReadinessResponse(BaseModel):
    """Reports whether dependencies required to serve real traffic are up."""

    status: Literal["ready", "degraded"]
    database: Literal["ok", "unavailable"]
