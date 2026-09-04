"""Building the configured provider, or refusing clearly.

One function, so the rest of the application never names a vendor. Adding a
provider means adding a branch here and a module beside it.
"""

from __future__ import annotations

from app.config import Settings, settings as default_settings
from app.nlq.llm import LLMClient, LLMNotConfigured


def build_llm_client(config: Settings | None = None) -> LLMClient:
    """The configured client.

    Raises `LLMNotConfigured` rather than returning None, so a missing key
    fails at one predictable place with a message an operator can act on,
    instead of as an AttributeError somewhere downstream.
    """
    config = config or default_settings

    if config.llm_provider != "anthropic":
        raise LLMNotConfigured(
            f"unknown llm_provider {config.llm_provider!r}; the only adapter "
            f"built is 'anthropic'"
        )

    if not config.anthropic_api_key:
        raise LLMNotConfigured(
            "ANTHROPIC_API_KEY is not set, so natural-language questions "
            "cannot be answered. Every other endpoint is unaffected."
        )

    from app.nlq.providers.anthropic_provider import AnthropicProvider

    return AnthropicProvider(
        api_key=config.anthropic_api_key,
        model=config.llm_model,
        timeout_seconds=config.llm_timeout_seconds,
        refusal_fallbacks=config.llm_refusal_fallbacks,
    )
