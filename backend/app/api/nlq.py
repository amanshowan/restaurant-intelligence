"""The structured analytics query endpoint.

WHY THIS EXISTS
There is a reasonable argument for shipping Commit 24 as a service class alone
and adding HTTP only when the language layer needs it. Three things tipped the
decision the other way, and none of them is "an endpoint might be handy":

  1. The request body IS the tool schema. FastAPI publishes the discriminated
     union in the OpenAPI document, which is the exact JSON Schema Commit 25
     will hand the model as its tool definition. Generating it from the same
     Pydantic models that enforce it removes the possibility of the two
     drifting apart.
  2. It makes the whitelist testable end to end. An adversarial body can be
     posted at the real application and shown to be rejected by validation,
     rather than only shown to be rejected by a direct call to the executor.
  3. Commit 25's answer generator will consume evidence over this boundary,
     so the boundary is worth having under test a commit early.

WHAT IT IS NOT
It accepts one thing: a member of the `AnalyticsRequest` union. There is no
free-text field, no SQL, no expression, no table or column selector, and no
generic operation. A body naming an unknown operation, or carrying an extra
key, is a 422 in the standard error envelope — it never reaches the executor,
and no session is opened.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import ConfigDict, RootModel

from app.api.deps import get_analytics_executor
from app.nlq.evidence import EvidenceBundle
from app.nlq.executor import AnalyticsExecutor
from app.nlq.requests import AnalyticsRequest
from app.schemas.imports import ErrorResponse


class AnalyticsQueryBody(RootModel[AnalyticsRequest]):
    """The request body: exactly one member of the whitelist.

    Wrapped in a RootModel rather than annotated directly on the handler
    because FastAPI reads the outermost `FieldInfo` on a parameter, and a
    `Body(...)` default there DISCARDS the `Field(discriminator="operation")`
    that makes the union closed. The published schema then advertised a bare
    `anyOf`, and validation fell back to trying each member in turn. A
    RootModel keeps the discriminator where Pydantic can see it, so both the
    schema a model is given and the validation it faces name `operation` as
    the tag.
    """

    model_config = ConfigDict(
        json_schema_extra={"description": "One validated analytics operation."}
    )

router = APIRouter(prefix="/analytics", tags=["analytics"])


@router.post(
    "/query",
    response_model=EvidenceBundle,
    summary="Execute one validated analytics operation",
    description=(
        "Runs a single operation from a closed whitelist and returns structured "
        "evidence: the numbers, what each one is, where it came from, and the "
        "limits applied.\n\n"
        "This endpoint exists so that a language model can obtain facts without "
        "ever expressing a query. It cannot select tables or columns, cannot "
        "supply SQL or any other expression, and has no generic operation to "
        "fall back on. Product names are matched exactly (case- and "
        "whitespace-insensitive) against the catalogue as bound parameters.\n\n"
        "Returns 200 with a non-`ok` `status` when a product reference is "
        "ambiguous or unknown, or when there is too little history to "
        "forecast: those are answers a caller can act on, and the candidate "
        "list is the useful part of an ambiguous one.\n\n"
        "Forecast rows are PREDICTIONS and are labelled as such — see the "
        "`forecast` block and `field_provenance`."
    ),
    responses={
        422: {
            "model": ErrorResponse,
            "description": (
                "Unknown operation, unknown field, out-of-range value or "
                "invalid date range. Rejected before any database access."
            ),
        }
    },
)
def analytics_query(
    body: AnalyticsQueryBody,
    executor: AnalyticsExecutor = Depends(get_analytics_executor),
) -> EvidenceBundle:
    return executor.execute(body.root)
