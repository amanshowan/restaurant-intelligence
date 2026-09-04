"""Question to answer, in four bounded stages.

    question  ->  plan  ->  execute  ->  answer

Two provider calls at most, and the second only happens if the first produced
a plan that validated and executed into evidence. Everything between the calls
is deterministic Commit 24 code.

WHAT THIS MODULE GUARANTEES
1. A model's output reaches the database only as a validated `AnalyticsPlan`,
   whose steps are Commit 24 `AnalyticsRequest`s. There is no other path.
2. The answer stage receives evidence and the question. It does not receive a
   database session, a tool, a catalogue, the plan's free-text purposes, or
   anything from the environment.
3. Every outcome that is not an answer — unanswerable, ambiguous product,
   provider failure — resolves WITHOUT a second provider call and without a
   fabricated answer.

WHAT IT DELIBERATELY DOES NOT DO
It does not verify the generated prose against the evidence. Extracting
numbers from English and matching them back is unreliable in both directions,
and a checker that is wrong in either direction is worse than none: it either
blocks correct answers or confers false confidence. Grounding is instead
enforced where it can be enforced — by controlling the model's entire factual
input — and the evidence is returned alongside the answer so a reader can
check it themselves.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import Enum

from pydantic import ValidationError

from app.nlq.context import ContextBuilder
from app.nlq.evidence import EvidenceBundle, EvidenceStatus, ResolvedProduct
from app.nlq.executor import AnalyticsExecutor
from app.nlq.llm import (
    LLMClient,
    LLMError,
    LLMInvalidResponse,
    LLMRefused,
    TokenUsage,
)
from app.nlq.plan import AnalyticsPlan, plan_json_schema
from app.nlq.prompts import (
    ANSWER_SYSTEM,
    PLANNER_SYSTEM,
    answer_user_message,
    planner_user_message,
)

#: Generous enough for a four-step plan, bounded so a runaway generation is cut
#: off rather than billed.
PLAN_MAX_TOKENS = 4096
#: A few paragraphs of prose. Not a report.
ANSWER_MAX_TOKENS = 2000

#: Questions outside these bounds never reach a provider.
MIN_QUESTION_LENGTH = 3
MAX_QUESTION_LENGTH = 1000


class AnswerStatus(str, Enum):
    """How the question ended. Every value is a complete, honest outcome."""

    #: Evidence was gathered and explained.
    ANSWERED = "answered"
    #: No combination of available operations answers the question. The
    #: planner said so; nothing was run and nothing was guessed.
    UNSUPPORTED = "unsupported"
    #: A product reference matched several catalogue entries. The candidates
    #: are returned so the user can choose. No answer was generated, because
    #: any answer would have required picking one for them.
    CLARIFICATION_NEEDED = "clarification_needed"


class QuestionRejected(ValueError):
    """The question itself is unusable — empty, or absurdly long."""


class PlanningFailed(LLMInvalidResponse):
    """The model could not produce a plan that satisfies the whitelist.

    A subclass of `LLMInvalidResponse` so the endpoint maps it like any other
    unusable model output. Carries the validation error for the operator log,
    never for the user.
    """

    def __init__(self, message: str, *, attempts: int, detail: str) -> None:
        super().__init__(message)
        self.attempts = attempts
        self.detail = detail


@dataclass(frozen=True)
class PlanStepRecord:
    """What one step was, and what it produced. The audit trail."""

    operation: str
    purpose: str
    evidence_status: str


@dataclass(frozen=True)
class AnswerResult:
    """One answered question, with everything needed to check it."""

    question: str
    status: AnswerStatus
    answer: str
    model: str
    steps: list[PlanStepRecord] = field(default_factory=list)
    evidence: list[EvidenceBundle] = field(default_factory=list)
    #: Populated only for CLARIFICATION_NEEDED.
    candidates: list[ResolvedProduct] = field(default_factory=list)
    usage: TokenUsage | None = None
    #: True when any bundle is a prediction. Derived from the EVIDENCE, never
    #: from the wording of the answer — so a consumer can flag a forecast even
    #: if the prose failed to.
    contains_forecast: bool = False
    #: Every limitation the executor attached to the evidence, in order.
    warnings: list[str] = field(default_factory=list)


class QuestionService:
    """Answers a natural-language question from measured evidence."""

    def __init__(
        self,
        *,
        llm: LLMClient,
        executor: AnalyticsExecutor,
        context: ContextBuilder,
        max_plan_attempts: int = 2,
        planner_effort: str | None = "low",
        answer_effort: str | None = "medium",
    ) -> None:
        self._llm = llm
        self._executor = executor
        self._context = context
        self._max_plan_attempts = max(1, max_plan_attempts)
        self._planner_effort = planner_effort
        self._answer_effort = answer_effort

    def ask(self, question: str) -> AnswerResult:
        cleaned = _validated_question(question)

        plan, usage = self._plan(cleaned)

        if not plan.answerable:
            # No execution, no answer call. The planner's own words are
            # returned verbatim: generating prose about an absence would mean
            # a second billed call to say "no".
            return AnswerResult(
                question=cleaned,
                status=AnswerStatus.UNSUPPORTED,
                answer=plan.unsupported_reason or (
                    "That question cannot be answered from the data this "
                    "system holds."
                ),
                model=self._llm.model,
                usage=usage,
            )

        bundles = [self._executor.execute(step.request) for step in plan.steps]
        records = [
            PlanStepRecord(
                operation=step.request.operation.value,
                purpose=step.purpose,
                evidence_status=bundle.status.value,
            )
            for step, bundle in zip(plan.steps, bundles)
        ]
        warnings = [w for bundle in bundles for w in bundle.warnings]
        contains_forecast = any(b.forecast is not None for b in bundles)

        ambiguous = [
            b for b in bundles if b.status is EvidenceStatus.AMBIGUOUS_PRODUCT
        ]
        if ambiguous:
            return self._clarification(
                cleaned, ambiguous, bundles, records, warnings, usage
            )

        answer = self._answer(cleaned, bundles)
        return AnswerResult(
            question=cleaned,
            status=AnswerStatus.ANSWERED,
            answer=answer.text,
            model=self._llm.model,
            steps=records,
            evidence=bundles,
            usage=usage.plus(answer.usage) if usage else answer.usage,
            contains_forecast=contains_forecast,
            warnings=warnings,
        )

    # -- stages ---------------------------------------------------------------

    def _plan(self, question: str) -> tuple[AnalyticsPlan, TokenUsage | None]:
        """Plan, with one repair round.

        A structurally invalid response is the commonest model failure, and
        showing the model its own validation error fixes most of them. The
        retry is bounded and the correction is the ERROR TEXT ONLY — no
        loosened schema, no relaxed rules, no second chance at the whitelist.
        """
        dates = self._context.dates()
        catalogue = self._context.catalogue()
        schema = plan_json_schema()
        base = planner_user_message(question, dates, catalogue)

        usage: TokenUsage | None = None
        last_error = ""

        for attempt in range(1, self._max_plan_attempts + 1):
            user = base if attempt == 1 else (
                f"{base}\n\nYour previous response was rejected by schema "
                f"validation:\n{last_error}\n\nReturn a corrected plan. The "
                f"schema and the rules are unchanged."
            )
            response = self._llm.complete_structured(
                system=PLANNER_SYSTEM,
                user=user,
                schema=schema,
                max_tokens=PLAN_MAX_TOKENS,
                effort=self._planner_effort,
            )
            usage = response.usage if usage is None else usage.plus(response.usage)

            try:
                return AnalyticsPlan.model_validate_json(response.text), usage
            except ValidationError as exc:
                last_error = _readable(exc)
            except ValueError as exc:  # not JSON at all
                last_error = f"the response was not valid JSON: {exc}"

        raise PlanningFailed(
            "the model did not produce a valid analytics plan",
            attempts=self._max_plan_attempts,
            detail=last_error,
        )

    def _answer(self, question: str, bundles: list[EvidenceBundle]):
        """Generate prose from evidence alone.

        The only inputs are the grounding rules and this message. No catalogue,
        no date context, no plan text, no session — the answer stage cannot
        reach a fact it was not handed.
        """
        return self._llm.complete_text(
            system=ANSWER_SYSTEM,
            user=answer_user_message(question, bundles),
            max_tokens=ANSWER_MAX_TOKENS,
            effort=self._answer_effort,
        )

    def _clarification(
        self, question, ambiguous, bundles, records, warnings, usage
    ) -> AnswerResult:
        """Ask which product was meant, rather than choosing one.

        Written deterministically, not generated. There is nothing here for a
        model to add, and a billed call to phrase a question we already know
        the shape of would be waste.
        """
        candidates = [
            candidate
            for bundle in ambiguous
            if bundle.product_resolution
            for candidate in bundle.product_resolution.candidates
        ]
        names = ", ".join(
            f"{c.name} ({c.variation})" if c.variation else c.name
            for c in candidates
        )
        requested = next(
            (
                b.product_resolution.requested_name
                for b in ambiguous
                if b.product_resolution and b.product_resolution.requested_name
            ),
            None,
        )
        subject = f'"{requested}"' if requested else "That product"
        return AnswerResult(
            question=question,
            status=AnswerStatus.CLARIFICATION_NEEDED,
            answer=(
                f"{subject} matches more than one item on the menu: {names}. "
                f"Which did you mean? No figures have been reported, because "
                f"answering would have meant choosing one for you."
            ),
            model=self._llm.model,
            steps=records,
            evidence=bundles,
            candidates=candidates,
            usage=usage,
            warnings=warnings,
        )


# --- helpers -----------------------------------------------------------------


def _validated_question(question: str) -> str:
    """Bound the question before it costs anything.

    Length only. Nothing here inspects the question for intent, and no attempt
    is made to detect an injection by pattern-matching English — that is
    unreliable, and it is not what protects this system. What protects it is
    that the question can only ever become a validated plan.
    """
    cleaned = question.strip()
    if len(cleaned) < MIN_QUESTION_LENGTH:
        raise QuestionRejected("a question must be at least a few characters long")
    if len(cleaned) > MAX_QUESTION_LENGTH:
        raise QuestionRejected(
            f"a question must be {MAX_QUESTION_LENGTH} characters or fewer; "
            f"this one is {len(cleaned)}"
        )
    return cleaned


def _readable(exc: ValidationError) -> str:
    """Validation errors as short lines the model can act on.

    Deliberately drops the submitted `input` values, matching the API's own
    error envelope: echoing a rejected payload back into a prompt is how
    attacker-controlled text gets a second attempt at being read as an
    instruction.
    """
    lines = []
    for error in exc.errors(include_url=False):
        location = ".".join(str(part) for part in error.get("loc", ()))
        lines.append(f"- {location}: {error.get('msg', '')}")
    return "\n".join(lines[:20]) or "the plan did not match the required schema"
