"""The natural-language question endpoint.

Thin, like every other route in this codebase: validate, delegate, shape,
map failures. The interesting decisions are in `app/nlq/`; what lives here is
the mapping from provider failures to status codes, which is the part a client
has to reason about.

WHY PROVIDER FAILURES ARE NOT 500s
A 500 says this application is broken. A missing key, a rate limit and a model
that returned malformed JSON are three different situations, none of them a
defect in this service, and a client should be able to tell them apart —
retry a 503, report a 502, and stop asking on a 501-shaped configuration
error. They are mapped accordingly, in the standard error envelope.

Every other endpoint keeps working when this one cannot. That is why the
provider client is constructed per-request rather than at import: no key means
`/analytics/ask` returns 503 and the dashboard, the analytics API and the
forecast are entirely unaffected.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.deps import get_question_service
from app.nlq.orchestrator import QuestionService
from app.schemas.ask import (
    AskRequest,
    AskResponse,
    PlanStepResponse,
    TokenUsageResponse,
)
from app.schemas.imports import ErrorResponse

router = APIRouter(prefix="/analytics", tags=["analytics"])


@router.post(
    "/ask",
    response_model=AskResponse,
    summary="Ask a question about trading in plain English",
    description=(
        "Answers a natural-language question from measured evidence.\n\n"
        "**The language model never queries the database.** A question is "
        "planned into at most four operations from a closed whitelist, those "
        "operations are executed by the deterministic Commit 24 executor, and "
        "the resulting evidence is the model's entire factual input when it "
        "writes the answer. It cannot express SQL, name a table, or reach any "
        "data it was not handed.\n\n"
        "The evidence is returned alongside the prose so every figure in the "
        "answer can be checked against what was actually measured. Forecast "
        "evidence is flagged by `contains_forecast` — derived from the "
        "evidence itself rather than from the answer's wording.\n\n"
        "A question no available operation can answer returns "
        "`status=unsupported` rather than a plausible-sounding guess. A "
        "product name matching several menu items returns "
        "`status=clarification_needed` with the candidates.\n\n"
        "Requires a configured model provider; without one this endpoint "
        "returns 503 and every other endpoint is unaffected."
    ),
    responses={
        422: {"model": ErrorResponse, "description": "Malformed or empty question"},
        502: {
            "model": ErrorResponse,
            "description": "The model returned nothing usable, or declined",
        },
        503: {
            "model": ErrorResponse,
            "description": "No provider configured, or the provider is unavailable",
        },
        504: {"model": ErrorResponse, "description": "The provider timed out"},
    },
)
def ask(
    request: AskRequest,
    service: QuestionService = Depends(get_question_service),
) -> AskResponse:
    # Provider failures and unusable questions are mapped by the handlers
    # registered in app/api/errors.py, not caught here. They can be raised
    # during dependency resolution — before this function body runs — so
    # catching them locally would miss the commonest case of all: no API key.
    result = service.ask(request.question)

    return AskResponse(
        question=result.question,
        status=result.status,
        answer=result.answer,
        steps=[
            PlanStepResponse(
                operation=step.operation,
                purpose=step.purpose,
                evidence_status=step.evidence_status,
            )
            for step in result.steps
        ],
        evidence=result.evidence,
        candidates=result.candidates,
        contains_forecast=result.contains_forecast,
        warnings=result.warnings,
        model=result.model,
        usage=(
            TokenUsageResponse(
                input_tokens=result.usage.input_tokens,
                output_tokens=result.usage.output_tokens,
            )
            if result.usage
            else None
        ),
    )
