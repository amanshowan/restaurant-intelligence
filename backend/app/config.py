"""Application configuration, loaded from the environment."""

from zoneinfo import ZoneInfo

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


settings = Settings()


#: Resolved once. Used for local-date <-> UTC-instant conversion everywhere.
BUSINESS_TZ = ZoneInfo(settings.business_timezone)
UTC = ZoneInfo("UTC")
