"""The provider port: what this application needs from a language model.

Two operations, both stateless, neither of them provider-specific:

    complete_structured(...)  ->  JSON text conforming to a JSON Schema
    complete_text(...)        ->  prose

Everything above this module — the planner, the answer generator, the
orchestrator, the endpoint — is written against `LLMClient` and knows nothing
about which vendor is behind it. The one adapter lives in `app/nlq/providers/`.

WHY A PORT RATHER THAN CALLING THE SDK DIRECTLY
Not for hypothetical vendor-switching, which is the weak version of this
argument. Three concrete reasons:

  1. The deterministic test suite must never make a network call. A fake
     implementing this protocol is three lines, and every orchestration,
     grounding and adversarial test runs against one.
  2. Provider failures have to become HTTP status codes. Mapping the SDK's
     exception hierarchy once, at the edge, keeps `except` clauses for a
     specific vendor out of the orchestration logic.
  3. `complete_structured` states the contract the planner actually depends
     on — "JSON matching this schema" — rather than whichever parameter a
     particular vendor spells it with this month.

WHAT THE PORT DELIBERATELY DOES NOT EXPOSE
No tool definitions, no function calling, no streaming, no conversation state.
The model is asked one question and returns one document. It cannot be handed
a callable, which is a large part of why it cannot reach the database.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable


class LLMError(RuntimeError):
    """Base for every provider failure. Callers catch subclasses."""


class LLMNotConfigured(LLMError):
    """No credentials, or the provider package is not installed.

    Distinct from an outage: nothing is wrong with the provider, the operator
    has simply not enabled the feature. The rest of the API is unaffected.
    """


class LLMUnavailable(LLMError):
    """The provider could not be reached, or failed transiently.

    Connection errors, rate limits and 5xx. Retryable in principle; the SDK
    has already retried by the time this is raised.
    """


class LLMTimeout(LLMUnavailable):
    """The provider did not answer within the configured wall-clock budget."""


class LLMRefused(LLMError):
    """The provider declined to answer.

    Its own safety classifiers, not ours. Surfaced separately because it is
    not a fault: nothing is broken, and the right response is to tell the user
    the question was not answered rather than to retry.
    """


class LLMInvalidResponse(LLMError):
    """The model returned something that is not usable.

    Unparseable JSON, or JSON that does not satisfy the schema it was given.
    A model failure rather than an infrastructure one, so it maps to a
    different status code.
    """


@dataclass(frozen=True)
class TokenUsage:
    """What one call cost, as reported by the provider."""

    input_tokens: int | None = None
    output_tokens: int | None = None

    def plus(self, other: "TokenUsage | None") -> "TokenUsage":
        if other is None:
            return self
        return TokenUsage(
            input_tokens=_add(self.input_tokens, other.input_tokens),
            output_tokens=_add(self.output_tokens, other.output_tokens),
        )


def _add(a: int | None, b: int | None) -> int | None:
    if a is None and b is None:
        return None
    return (a or 0) + (b or 0)


@dataclass(frozen=True)
class LLMResponse:
    """One completion, plus what it cost and which model produced it."""

    text: str
    model: str
    usage: TokenUsage | None = None
    #: Provider-reported stop reason, carried for diagnostics only. Nothing in
    #: this application branches on its value — a refusal arrives as
    #: `LLMRefused` instead, so behaviour does not depend on a vendor string.
    stop_reason: str | None = None


@runtime_checkable
class LLMClient(Protocol):
    """What a provider adapter must implement."""

    @property
    def model(self) -> str:
        """The model identifier, for answer metadata and audit."""
        ...

    def complete_structured(
        self,
        *,
        system: str,
        user: str,
        schema: dict[str, Any],
        max_tokens: int,
        effort: str | None = None,
    ) -> LLMResponse:
        """Return JSON text conforming to `schema`.

        The schema is a JSON Schema document generated from the Pydantic model
        the caller will validate against. Implementations should ask the
        provider to constrain generation to it, but the caller validates
        regardless — a provider's guarantee is not this application's
        guarantee.
        """

    def complete_text(
        self,
        *,
        system: str,
        user: str,
        max_tokens: int,
        effort: str | None = None,
    ) -> LLMResponse:
        """Return prose."""
