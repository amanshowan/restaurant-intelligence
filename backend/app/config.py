"""Application configuration, loaded from the environment."""

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


settings = Settings()
