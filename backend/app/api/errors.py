"""Consistent error envelopes across every endpoint.

Every failure — ours or FastAPI's own request validation — is returned in the
same shape, matching the `ErrorResponse` schema exactly:

    {"detail": "...", "code": "...", "errors": [...]}

Without these handlers, raising `HTTPException(detail={"detail":…, "code":…})`
nests the payload one level deeper than the documented schema, so a client
generated from the OpenAPI document would read `.code` and find nothing.
"""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.exception_handlers import http_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException


async def _structured_http_exception(request: Request, exc: StarletteHTTPException):
    """Unwrap our structured detail so the body matches ErrorResponse."""
    if isinstance(exc.detail, dict) and "code" in exc.detail:
        return JSONResponse(
            status_code=exc.status_code,
            content=exc.detail,
            headers=getattr(exc, "headers", None),
        )
    return await http_exception_handler(request, exc)


async def _validation_exception(request: Request, exc: RequestValidationError):
    """Report FastAPI's parameter validation in the same envelope.

    Only `loc`, `msg` and `type` are echoed. The raw `input` and `ctx` fields
    are deliberately dropped: they reflect submitted values straight back to
    the caller, which is a needless way to surface data in error logs.
    """
    errors = [
        {
            "location": ".".join(str(part) for part in error.get("loc", ())),
            "message": error.get("msg", ""),
            "type": error.get("type", ""),
        }
        for error in exc.errors()
    ]
    summary = "; ".join(f"{e['location']}: {e['message']}" for e in errors) or (
        "request validation failed"
    )
    return JSONResponse(
        status_code=422,
        content={"detail": summary, "code": "validation_error", "errors": errors},
    )


def register_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(StarletteHTTPException, _structured_http_exception)
    app.add_exception_handler(RequestValidationError, _validation_exception)
