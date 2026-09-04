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

from app.nlq.llm import (
    LLMError,
    LLMInvalidResponse,
    LLMNotConfigured,
    LLMRefused,
    LLMTimeout,
    LLMUnavailable,
)
from app.nlq.orchestrator import QuestionRejected

#: Provider failures, mapped once. Ordered most-specific first, because
#: LLMTimeout is a subclass of LLMUnavailable and would otherwise be swallowed
#: by it.
#:
#: These are registered as APPLICATION-WIDE handlers rather than caught inside
#: the route, because a provider failure can surface before the handler body
#: runs: the client is constructed in a FastAPI dependency, and an exception
#: raised during dependency resolution never reaches the route's own `try`.
#: An earlier version caught them in the route and returned 500 for the single
#: most likely real-world case — no API key configured.
#:
#: None of them is a 500. A 500 says this service is broken; a missing key, a
#: rate limit and a model that returned nonsense are three different
#: situations, none of them a defect here, and a client should be able to tell
#: them apart to decide whether retrying is worth anything.
LLM_ERROR_STATUS: tuple[tuple[type[LLMError], int, str], ...] = (
    (LLMNotConfigured, 503, "llm_not_configured"),
    (LLMTimeout, 504, "llm_timeout"),
    (LLMUnavailable, 503, "llm_unavailable"),
    (LLMRefused, 502, "llm_refused"),
    (LLMInvalidResponse, 502, "llm_invalid_response"),
)


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


async def _llm_error(request: Request, exc: LLMError):
    """Map a provider failure, wherever in the request it was raised.

    The message is the one this application wrote, never the provider's own —
    an upstream error string can quote the credential it rejected.
    """
    for error_type, status_code, code in LLM_ERROR_STATUS:
        if isinstance(exc, error_type):
            return JSONResponse(
                status_code=status_code, content={"detail": str(exc), "code": code}
            )
    return JSONResponse(
        status_code=503,
        content={"detail": str(exc), "code": "llm_unavailable"},
    )


async def _question_rejected(request: Request, exc: QuestionRejected):
    """An unusable question: empty, or absurdly long. The caller's to fix."""
    return JSONResponse(
        status_code=422, content={"detail": str(exc), "code": "invalid_question"}
    )


def register_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(StarletteHTTPException, _structured_http_exception)
    app.add_exception_handler(RequestValidationError, _validation_exception)
    app.add_exception_handler(QuestionRejected, _question_rejected)
    app.add_exception_handler(LLMError, _llm_error)
