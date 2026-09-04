"""Application configuration, loaded from the environment."""

from zoneinfo import ZoneInfo

from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Settings read from environment variables.

    Field names map to environment variables case-insensitively, so
    `database_url` is populated from DATABASE_URL (set in docker-compose.yml).

    `database_url` has no default. If it is missing the application fails at
    import time with a clear validation error, rather than starting up and
    failing later on the first query.
    """

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str
    app_name: str = "Restaurant Intelligence API"
    environment: str = "development"

    #: The trading timezone. Every user-facing date, and every daily/hourly
    #: grouping, is expressed in this zone rather than UTC — a day's takings
    #: means the business's day, not 00:00-00:00 UTC.
    business_timezone: str = "Europe/London"

    # --- natural-language analytics (M7) ------------------------------------
    #
    # Every value here comes from the environment. No key, model name or
    # endpoint is ever written in code, and none of them is placed in a prompt.
    #
    # `anthropic_api_key` is OPTIONAL by design. Without it the API still
    # starts and every analytics, product, basket and forecast endpoint works
    # exactly as before; only /analytics/ask reports itself unavailable. A
    # missing key must degrade one feature, not the service.

    #: Which provider adapter to build. One value today; the setting exists so
    #: adding a second provider is a configuration change, not a code change.
    llm_provider: str = "anthropic"

    #: Read from ANTHROPIC_API_KEY. Never logged, never rendered into a prompt.
    anthropic_api_key: str | None = None

    #: The model used for both planning and answering.
    llm_model: str = "claude-opus-5"

    #: Wall-clock ceiling for a single provider call, in seconds. A question
    #: that cannot be answered promptly should fail visibly rather than hold a
    #: worker open.
    llm_timeout_seconds: float = 60.0

    #: How hard the model works. Planning is close to classification and does
    #: not repay depth; explaining evidence faithfully does.
    #: Constrained rather than free text: an unrecognised effort is rejected
    #: by the provider with a 400, and a typo in an environment variable
    #: should fail at startup rather than on a user's first question.
    llm_planner_effort: Literal["low", "medium", "high", "xhigh", "max"] = "low"
    llm_answer_effort: Literal["low", "medium", "high", "xhigh", "max"] = "medium"

    #: Total attempts at producing a schema-valid plan, including the first.
    #: A second attempt is given the validation error and asked to correct it —
    #: a malformed structured response is the most common LLM failure and one
    #: repair round fixes most of them. Set to 1 to disable.
    llm_max_plan_attempts: int = 2

    #: Ask the provider to reroute a refused request to another model rather
    #: than returning a refusal. Enabled by default; a refusal is still handled
    #: safely if it arrives, so this only affects availability.
    llm_refusal_fallbacks: bool = True


settings = Settings()


#: Resolved once. Used for local-date <-> UTC-instant conversion everywhere.
BUSINESS_TZ = ZoneInfo(settings.business_timezone)
UTC = ZoneInfo("UTC")
