"""The Anthropic adapter: the only module in this codebase that imports an SDK.

It does three things and nothing else — build a request, make the call, map the
failure. It holds no analytics knowledge, no prompt text and no business rules,
so reading it tells you exactly what leaves the process and nothing about what
the application means.

MODEL AND PARAMETERS
`claude-opus-5` by default, overridable by environment. Thinking is left
unconfigured: it is adaptive by default on this model, and the deprecated
fixed-budget parameter is rejected outright by it. Depth is controlled through
`effort` instead, which the caller sets per stage — planning is close to
classification and does not repay depth, whereas explaining evidence
faithfully does.

STRUCTURED OUTPUT
`output_config.format` constrains generation to the JSON Schema the planner
was built from. The caller still validates the result with Pydantic. A
provider's guarantee is not this application's guarantee, and the whitelist
has to hold even if the constraint silently stops working — which is exactly
what makes the schema subset below safe to work around.

Two things go wrong here in practice, and both are handled without weakening
anything:

  1. The provider accepts a SUBSET of JSON Schema, and Pydantic emits keywords
     outside it — see `compatible_schema`.
  2. Even a valid schema can be refused if its compiled grammar is too large.
     A twelve-operation discriminated union is, and no amount of rewriting
     changes that.

So constrained generation is BEST EFFORT. When the provider refuses the
schema, the adapter falls back to carrying the schema in the system prompt and
parsing the JSON that comes back. That is a downgrade in convenience, not in
safety: the plan has always been validated by Pydantic against the unmodified
model afterwards, precisely so that this layer never has to be trusted.

REFUSALS
The provider's own classifiers may decline a request — an adversarial question
is a plausible trigger. Two independent things happen. Server-side fallbacks
ask the provider to reroute to another model, so a benign question is not lost
to a false positive; and a refusal that arrives anyway is raised as
`LLMRefused`, which the orchestrator turns into a safe "not answered" reply.
The second is what makes the behaviour correct; the first only improves
availability, and can be switched off by configuration.
"""

from __future__ import annotations

import json
import re
from typing import Any

from app.nlq.llm import (
    LLMError,
    LLMInvalidResponse,
    LLMNotConfigured,
    LLMRefused,
    LLMResponse,
    LLMTimeout,
    LLMUnavailable,
    TokenUsage,
)

#: Opts into server-side refusal rerouting. Paired with `fallbacks="default"`,
#: which routes by refusal category so no model list has to be maintained here.
REFUSAL_FALLBACK_BETA = "server-side-fallback-2026-07-01"

#: JSON Schema keywords this provider's structured-output engine rejects with a
#: 400. Established by probing the live API keyword by keyword, not guessed:
#:
#:     maxItems           "For 'array' type, property 'maxItems' is not supported"
#:     minimum/maximum    "For 'integer' type, property 'minimum' is not supported"
#:     exclusiveMinimum/Maximum   likewise
#:
#: Everything else Pydantic emits is accepted: minItems, minLength, maxLength,
#: format, const, enum, anyOf, default, title, description, examples, $ref/$defs.
#:
#: These are GENERATION constraints only. Dropping one cannot widen what this
#: application accepts, because the plan is validated by Pydantic against the
#: unmodified model after it comes back — the bound stays a hard limit, it
#: simply stops being enforced twice. A model that ignores a dropped bound
#: produces a plan that fails validation and is rejected, exactly as before.
UNSUPPORTED_SCHEMA_KEYWORDS: dict[str, str] = {
    "maxItems": "At most {value} items.",
    "maximum": "Maximum: {value}.",
    "minimum": "Minimum: {value}.",
    "exclusiveMaximum": "Must be less than {value}.",
    "exclusiveMinimum": "Must be greater than {value}.",
}

#: Dropped outright — there is no prose worth adding, because the information
#: is already carried by each branch's `operation` const.
#:
#:     discriminator      "For 'anyOf', 'discriminator' is not supported"
DISCARDED_SCHEMA_KEYWORDS = ("discriminator",)

#: `oneOf` is rejected ("Schema type 'oneOf' is not supported"); `anyOf` is
#: accepted. Pydantic renders a discriminated union as `oneOf`, so it is
#: rewritten. `anyOf` is the looser of the two — it permits a document matching
#: several branches, which `oneOf` would not — but the branches here are made
#: mutually exclusive by their `operation` const, and the plan is validated
#: afterwards against the real discriminated union either way.
REWRITTEN_SCHEMA_KEYWORDS = {"oneOf": "anyOf"}

#: Fragments identifying a 400 that rejects the SCHEMA rather than the request.
#: Matched on the provider's message because there is no distinct error type;
#: the message is used here for routing only and is never shown to a user.
_SCHEMA_REJECTION_MARKERS = (
    "output_config.format.schema",
    "compiled grammar",
    "grammar is too large",
)

#: Prepended to the system prompt when constrained generation is unavailable.
#: The schema goes in the SYSTEM message, not the user message: it is operator
#: content, and keeping it out of the user turn leaves the untrusted question
#: as the only thing in that channel.
_SCHEMA_INSTRUCTION = """

OUTPUT FORMAT
Reply with a single JSON document and nothing else — no prose before or after
it, and no markdown code fence. It must conform exactly to this JSON Schema,
including every required field and no additional properties:

{schema}
"""


class SchemaNotSupported(LLMError):
    """The provider will not accept this schema for constrained generation.

    Internal to this module. It never reaches a caller: `complete_structured`
    handles it by retrying without the constraint.
    """


def _extract_json(text: str) -> str:
    """The JSON document out of a model response.

    Needed only on the fallback path, where generation is unconstrained and a
    model may wrap its answer in a fence or a sentence. Conservative: it
    unwraps a fence, and otherwise takes the outermost braces. If it finds
    neither it returns the text unchanged and lets Pydantic produce the error,
    which is more useful than one invented here.
    """
    stripped = text.strip()
    fence = re.match(r"^```(?:json)?\s*(.*?)\s*```$", stripped, re.DOTALL)
    if fence:
        return fence.group(1).strip()
    if stripped.startswith("{"):
        return stripped
    start, end = stripped.find("{"), stripped.rfind("}")
    if 0 <= start < end:
        return stripped[start : end + 1]
    return stripped


def compatible_schema(schema: Any) -> Any:
    """The same schema, minus the keywords this provider will not accept.

    The dropped bound is not simply discarded: it is appended to the field's
    `description`, so the model is still told "at most 4 items" or "maximum:
    14" in text it does read. Dropping the bound silently would cost accuracy —
    the model would guess, the plan would fail validation, and the repair round
    would be spent recovering something it could have been told.

    `oneOf` is rewritten to `anyOf` and `discriminator` is dropped for the same
    reason and with the same safety argument: both describe how to GENERATE a
    plan, and neither is what accepts one.

    Recursive and non-mutating: the caller's schema is untouched, so
    `plan_json_schema()` remains the exact document the plan is validated
    against.
    """
    if isinstance(schema, list):
        return [compatible_schema(item) for item in schema]
    if not isinstance(schema, dict):
        return schema

    cleaned: dict[str, Any] = {}
    notes: list[str] = []
    for key, value in schema.items():
        if key in UNSUPPORTED_SCHEMA_KEYWORDS:
            notes.append(UNSUPPORTED_SCHEMA_KEYWORDS[key].format(value=value))
            continue
        if key in DISCARDED_SCHEMA_KEYWORDS:
            continue
        cleaned[REWRITTEN_SCHEMA_KEYWORDS.get(key, key)] = compatible_schema(value)

    if notes:
        description = cleaned.get("description", "")
        cleaned["description"] = " ".join([description, *notes]).strip()
    return cleaned


def build_request(
    *,
    model: str,
    system: str,
    user: str,
    max_tokens: int,
    effort: str | None = None,
    schema: dict[str, Any] | None = None,
    refusal_fallbacks: bool = True,
) -> dict[str, Any]:
    """The exact keyword arguments for one Messages call.

    A pure function, separated from the call so the request shape is testable
    without a network or a key. Two properties matter enough to be asserted in
    the suite: the untrusted question travels in the USER message and never in
    `system`, and no credential appears anywhere in the payload.
    """
    output_config: dict[str, Any] = {}
    if effort:
        output_config["effort"] = effort
    if schema is not None:
        output_config["format"] = {
            "type": "json_schema",
            "schema": compatible_schema(schema),
        }

    request: dict[str, Any] = {
        "model": model,
        "max_tokens": max_tokens,
        # The grounding rules and the operation whitelist. Operator authority.
        "system": system,
        # The user's question, or evidence to explain. Untrusted content.
        "messages": [{"role": "user", "content": user}],
    }
    if output_config:
        request["output_config"] = output_config
    if refusal_fallbacks:
        request["betas"] = [REFUSAL_FALLBACK_BETA]
        request["fallbacks"] = "default"
    return request


class AnthropicProvider:
    """`LLMClient` backed by the Anthropic Messages API."""

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        timeout_seconds: float = 60.0,
        refusal_fallbacks: bool = True,
        client: Any | None = None,
    ) -> None:
        self._model = model
        self._refusal_fallbacks = refusal_fallbacks
        #: Schemas this model has already refused, so the wasted round trip
        #: happens at most once per process rather than on every question.
        self._unconstrainable: set[str] = set()
        self._client = client if client is not None else _build_client(
            api_key=api_key, timeout_seconds=timeout_seconds
        )

    @property
    def model(self) -> str:
        return self._model

    def complete_structured(
        self,
        *,
        system: str,
        user: str,
        schema: dict[str, Any],
        max_tokens: int,
        effort: str | None = None,
    ) -> LLMResponse:
        """JSON conforming to `schema`, constrained by the provider if it can be.

        The port promises JSON text, not a particular mechanism for getting it.
        Constrained generation is used when the provider accepts the schema and
        the prompt carries it otherwise; either way the caller validates what
        comes back, so the guarantee the application relies on is the same.
        """
        fingerprint = _fingerprint(schema)

        if fingerprint not in self._unconstrainable:
            try:
                return self._call(
                    system=system, user=user, max_tokens=max_tokens,
                    effort=effort, schema=schema,
                )
            except SchemaNotSupported:
                # Remembered, so this costs one round trip per process rather
                # than one per question.
                self._unconstrainable.add(fingerprint)

        response = self._call(
            system=system + _SCHEMA_INSTRUCTION.format(
                schema=json.dumps(compatible_schema(schema), indent=1)
            ),
            user=user,
            max_tokens=max_tokens,
            effort=effort,
        )
        # The port's contract is JSON text. Unconstrained generation may fence
        # it, so honouring that contract is this adapter's job, not the
        # orchestrator's.
        return LLMResponse(
            text=_extract_json(response.text),
            model=response.model,
            usage=response.usage,
            stop_reason=response.stop_reason,
        )

    def complete_text(
        self,
        *,
        system: str,
        user: str,
        max_tokens: int,
        effort: str | None = None,
    ) -> LLMResponse:
        return self._call(
            system=system, user=user, max_tokens=max_tokens, effort=effort
        )

    # -- internals ------------------------------------------------------------

    def _call(self, **kwargs: Any) -> LLMResponse:
        request = build_request(
            model=self._model, refusal_fallbacks=self._refusal_fallbacks, **kwargs
        )
        try:
            message = self._client.beta.messages.create(**request)
        except Exception as exc:  # mapped below; nothing is swallowed
            raise _mapped(exc) from exc

        # Checked before the content is read: on a refusal the content blocks
        # are not the answer that was asked for.
        if getattr(message, "stop_reason", None) == "refusal":
            raise LLMRefused(
                "the provider declined to answer this question"
            )

        text = "".join(
            block.text
            for block in message.content
            if getattr(block, "type", None) == "text"
        )
        if not text.strip():
            raise LLMInvalidResponse("the provider returned an empty response")

        return LLMResponse(
            text=text,
            model=getattr(message, "model", self._model),
            usage=_usage(getattr(message, "usage", None)),
            stop_reason=getattr(message, "stop_reason", None),
        )


def _build_client(*, api_key: str, timeout_seconds: float) -> Any:
    """Construct the SDK client, importing it lazily.

    Lazy on purpose. The import is what makes the package a hard runtime
    dependency, and deferring it to the moment a key is actually used keeps
    every other endpoint working on an installation that has neither.
    """
    try:
        import anthropic
    except ModuleNotFoundError as exc:  # pragma: no cover - install-time state
        raise LLMNotConfigured(
            "the 'anthropic' package is not installed, so natural-language "
            "questions cannot be answered"
        ) from exc

    return anthropic.Anthropic(api_key=api_key, timeout=timeout_seconds)


def _fingerprint(schema: dict[str, Any]) -> str:
    """A stable key for one schema. Sorted, so key order cannot vary it."""
    return json.dumps(schema, sort_keys=True, default=str)


def _usage(usage: Any) -> TokenUsage | None:
    if usage is None:
        return None
    return TokenUsage(
        input_tokens=getattr(usage, "input_tokens", None),
        output_tokens=getattr(usage, "output_tokens", None),
    )


def _mapped(exc: Exception):
    """Translate the SDK's exception hierarchy into this application's.

    Most-specific first, and deliberately not one broad `except`: a timeout, a
    rate limit and a malformed request are three different operational
    situations that should reach the caller as three different status codes.

    Matching is on class NAME rather than by importing the SDK's exception
    classes, so this function stays importable — and testable — on a machine
    where the package is absent.
    """
    name = type(exc).__name__

    # Checked first: a schema the provider will not compile is not a failed
    # request, it is a capability limit, and the caller can work around it.
    if name in ("BadRequestError", "UnprocessableEntityError"):
        message = str(exc).lower()
        if any(marker in message for marker in _SCHEMA_REJECTION_MARKERS):
            return SchemaNotSupported(
                "the provider will not compile this schema for constrained "
                "generation"
            )

    if name in ("APITimeoutError", "TimeoutError"):
        return LLMTimeout("the model provider did not respond in time")
    if name in (
        "APIConnectionError",
        "APIStatusError",
        "RateLimitError",
        "InternalServerError",
        "ServiceUnavailableError",
        "OverloadedError",
    ):
        return LLMUnavailable(f"the model provider is unavailable ({name})")
    if name in ("AuthenticationError", "PermissionDeniedError"):
        # Deliberately not echoed: the provider's message can quote the
        # credential it rejected.
        return LLMNotConfigured(
            "the configured model provider credentials were rejected"
        )
    if name in ("BadRequestError", "UnprocessableEntityError", "NotFoundError"):
        return LLMInvalidResponse(f"the model provider rejected the request ({name})")
    if isinstance(exc, (LLMNotConfigured, LLMInvalidResponse)):
        return exc
    return LLMUnavailable(f"the model provider call failed ({name})")
