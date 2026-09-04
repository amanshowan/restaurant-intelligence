"""Request and response schemas for the natural-language question endpoint."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from app.nlq.evidence import EvidenceBundle, ResolvedProduct
from app.nlq.orchestrator import (
    MAX_QUESTION_LENGTH,
    MIN_QUESTION_LENGTH,
    AnswerStatus,
)


class AskRequest(BaseModel):
    """One question. Nothing else is accepted.

    There is deliberately no field for a date override, an operation hint, a
    model name, a system-prompt addition or a temperature. Each would be a way
    for a caller to alter behaviour the server is responsible for, and the
    date context in particular must come from the database rather than from
    whoever is asking.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    question: str = Field(
        min_length=MIN_QUESTION_LENGTH,
        max_length=MAX_QUESTION_LENGTH,
        description=(
            "A question in plain English about this business's trading. "
            "Treated as untrusted text: it is planned against a closed set of "
            "analytics operations and can never become a query."
        ),
        examples=["How did we perform last month?"],
    )


class PlanStepResponse(BaseModel):
    """One operation the planner chose, and what it produced."""

    model_config = ConfigDict(frozen=True)

    operation: str = Field(description="The whitelisted operation that was run.")
    purpose: str = Field(
        description=(
            "The planner's stated reason for choosing it. An audit note, not "
            "a finding — it was never given to the answer stage."
        )
    )
    evidence_status: str = Field(
        description="The resulting bundle's status, e.g. ok or unknown_product."
    )


class TokenUsageResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    input_tokens: int | None = None
    output_tokens: int | None = None


class AskResponse(BaseModel):
    """An answer, and everything needed to check it.

    The evidence is returned in full alongside the prose on purpose. The
    system's claim is not "trust the model"; it is "here is what was measured,
    and here is the sentence it produced from it".
    """

    model_config = ConfigDict(frozen=True)

    question: str
    status: AnswerStatus = Field(
        description=(
            "answered — evidence was gathered and explained. "
            "unsupported — no available operation answers the question; "
            "nothing was run. "
            "clarification_needed — a product name matched several menu "
            "items, so the candidates are returned rather than one being "
            "chosen."
        )
    )
    answer: str = Field(
        description=(
            "Plain-English answer, generated only from the evidence below."
        )
    )

    steps: list[PlanStepResponse] = Field(
        default_factory=list,
        description="The operations that ran, in order. Empty when unsupported.",
    )
    evidence: list[EvidenceBundle] = Field(
        default_factory=list,
        description=(
            "The full evidence the answer was generated from, with units, "
            "provenance and limits. Every claim in `answer` should be "
            "checkable against this."
        ),
    )
    candidates: list[ResolvedProduct] = Field(
        default_factory=list,
        description="Product candidates, when status is clarification_needed.",
    )

    contains_forecast: bool = Field(
        default=False,
        description=(
            "True when any evidence bundle is a prediction. Derived from the "
            "EVIDENCE, not from the wording of the answer, so a consumer can "
            "mark a forecast even if the prose failed to."
        ),
    )
    warnings: list[str] = Field(
        default_factory=list,
        description="Limitations the executor attached to the evidence.",
    )

    model: str = Field(description="The model that produced the answer.")
    usage: TokenUsageResponse | None = Field(
        default=None, description="Tokens consumed across both provider calls."
    )
