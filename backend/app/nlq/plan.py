"""The plan: the only thing a language model is allowed to emit.

Commit 24 established that a model may produce an `AnalyticsRequest` and
nothing else. Commit 25 adds exactly one layer above that — a short, bounded
list of them, with a stated reason for each.

The plan reuses `AnalyticsRequest` VERBATIM. It does not restate the operation
enum, redeclare a date field or define a looser parallel schema, because a
second declaration of the whitelist is a second thing to keep in step, and the
one that drifted would be the one the model was actually validated against.

Everything a model can express is therefore bounded twice: by the number of
steps here, and by each step's Commit 24 schema. A plan is either fully valid
or entirely rejected — there is no partial execution of a malformed plan.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.nlq.requests import AnalyticsRequest

#: A question that genuinely needs more than four aggregate operations is a
#: report, not a question. The ceiling bounds latency, provider cost and the
#: volume of evidence the answer stage has to stay faithful to — and it is a
#: hard schema limit, so no prompt wording can raise it.
MAX_PLAN_STEPS = 4

#: Free text the model writes about its own intent. Bounded so a plan cannot
#: become a channel for smuggling a wall of text into the answer stage.
MAX_REASON_LENGTH = 400


class PlannedStep(BaseModel):
    """One analytics operation, and why the planner chose it."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    purpose: str = Field(
        max_length=MAX_REASON_LENGTH,
        description=(
            "Why this operation answers part of the question. Recorded for "
            "audit; it is never treated as a fact and never reaches the "
            "answer stage as evidence."
        ),
    )
    request: AnalyticsRequest = Field(
        description=(
            "A validated analytics request. This is the Commit 24 whitelist "
            "unchanged: an unknown operation or an unknown field fails here."
        )
    )


class AnalyticsPlan(BaseModel):
    """What the planner returns for one question."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    answerable: bool = Field(
        description=(
            "False when the question cannot be answered by any combination of "
            "the available operations. Saying so is a correct outcome; "
            "choosing a loosely related operation instead is not."
        )
    )
    steps: tuple[PlannedStep, ...] = Field(
        default=(),
        max_length=MAX_PLAN_STEPS,
        description=(
            f"At most {MAX_PLAN_STEPS} operations, executed in order. Empty "
            f"when the question is unanswerable."
        ),
    )
    unsupported_reason: str | None = Field(
        default=None,
        max_length=MAX_REASON_LENGTH,
        description=(
            "Required when `answerable` is false: what was asked for, and "
            "which data the system does not hold. Stated plainly, with no "
            "guess at the answer."
        ),
    )

    @model_validator(mode="after")
    def _coherent(self) -> "AnalyticsPlan":
        """A plan must be one thing or the other, never both or neither."""
        if self.answerable:
            if not self.steps:
                raise ValueError(
                    "an answerable plan must contain at least one operation"
                )
            if self.unsupported_reason:
                raise ValueError(
                    "unsupported_reason must be omitted when answerable is true"
                )
        else:
            if self.steps:
                raise ValueError(
                    "an unanswerable plan must contain no operations"
                )
            if not self.unsupported_reason:
                raise ValueError(
                    "unsupported_reason is required when answerable is false"
                )
        return self

    @property
    def operations(self) -> list[str]:
        return [step.request.operation.value for step in self.steps]


def plan_json_schema() -> dict:
    """The JSON Schema handed to the provider to constrain generation.

    Generated from the models above rather than written by hand, so the schema
    the model is given and the schema it is validated against are the same
    object. `extra="forbid"` throughout means it also carries
    `additionalProperties: false`, which is what makes a smuggled field a
    generation-time failure rather than a validation-time one.
    """
    return AnalyticsPlan.model_json_schema()
