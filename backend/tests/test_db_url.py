"""Pinning a generic PostgreSQL URL onto the driver this project installs.

The defect these cover shipped as a successful build and a failed first
migration: a managed database handed out `postgresql://`, SQLAlchemy resolved
that to the psycopg2 dialect, and the deployment died with

    ModuleNotFoundError: No module named 'psycopg2'

naming a dependency that is deliberately absent rather than the URL that asked
for it. Nothing about it is provider-specific — every managed Postgres issues
the generic libpq scheme, because the scheme says nothing about which Python
driver will consume it.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.config import Settings
from app.db_url import (
    GENERIC_POSTGRES_SCHEMES,
    POSTGRES_DRIVER,
    normalise_database_url,
)

HOST = "user:pass@db.example.com:5432/appdb"


# --- generic schemes are pinned ----------------------------------------------


@pytest.mark.parametrize("scheme", sorted(GENERIC_POSTGRES_SCHEMES))
def test_a_generic_postgres_scheme_is_pinned_to_psycopg(scheme):
    assert (
        normalise_database_url(f"{scheme}://{HOST}")
        == f"postgresql+{POSTGRES_DRIVER}://{HOST}"
    )


def test_the_legacy_postgres_scheme_is_covered():
    """Several providers still issue `postgres://`. SQLAlchemy removed it as an
    alias, so leaving it alone only trades one startup error for another."""
    assert "postgres" in GENERIC_POSTGRES_SCHEMES
    assert normalise_database_url("postgres://user@host/db") == (
        "postgresql+psycopg://user@host/db"
    )


def test_the_scheme_is_matched_case_insensitively():
    assert normalise_database_url("POSTGRESQL://user@host/db") == (
        "postgresql+psycopg://user@host/db"
    )


# --- everything else is left alone -------------------------------------------


def test_an_explicit_psycopg_url_is_unchanged():
    url = f"postgresql+{POSTGRES_DRIVER}://{HOST}"
    assert normalise_database_url(url) == url


@pytest.mark.parametrize(
    "url",
    [
        "postgresql+asyncpg://user@host/db",
        "postgresql+psycopg2://user@host/db",
        "postgresql+pg8000://user@host/db",
    ],
)
def test_a_url_naming_another_driver_is_never_retargeted(url):
    """A URL that names its driver means it. Silently redirecting one would be
    worse than the error it replaced."""
    assert normalise_database_url(url) == url


@pytest.mark.parametrize(
    "url",
    [
        "sqlite:///./local.db",
        "sqlite+aiosqlite:///./local.db",
        "mysql+pymysql://user@host/db",
        "mssql+pyodbc://user@host/db",
        "cockroachdb://user@host/db",
    ],
)
def test_a_non_postgres_url_is_unchanged(url):
    assert normalise_database_url(url) == url


@pytest.mark.parametrize("value", ["", "not-a-url", "postgresql", "/var/run/pg"])
def test_a_string_that_is_not_a_url_is_left_for_sqlalchemy_to_reject(value):
    """SQLAlchemy's own error is better than one invented here."""
    assert normalise_database_url(value) == value


# --- everything after the scheme survives byte for byte ----------------------


@pytest.mark.parametrize(
    "remainder",
    [
        "user:p%40ssword@host/db",              # percent-encoded '@' in password
        "user:pa%2Fss@host:5432/db",            # percent-encoded '/'
        "user@host/db?sslmode=require",
        "user@host/db?sslmode=require&application_name=ri",
        "host/db",                              # no credentials
        "user:pass@[2001:db8::1]:5432/db",      # IPv6 host
        "user:!$&'()*+,;=@host/db",             # sub-delims, unencoded
    ],
)
def test_only_the_scheme_is_rewritten(remainder):
    """Re-serialising a parsed URL risks re-encoding a password that was
    already correct, so the rewrite is textual and stops at the separator."""
    assert normalise_database_url(f"postgresql://{remainder}") == (
        f"postgresql+psycopg://{remainder}"
    )


def test_a_separator_inside_the_password_does_not_confuse_the_split():
    url = "postgresql://user:weird://pass@host/db"
    assert normalise_database_url(url) == (
        "postgresql+psycopg://user:weird://pass@host/db"
    )


def test_normalising_twice_changes_nothing():
    once = normalise_database_url(f"postgresql://{HOST}")
    assert normalise_database_url(once) == once


# --- the value the application and Alembic actually use ----------------------


def test_settings_pins_the_driver_so_both_consumers_agree():
    """`app.db` builds the engine from this field and `alembic/env.py` injects
    it as `sqlalchemy.url` — so normalising it once is what stops a deployment
    getting a working application and a failed migration."""
    settings = Settings(database_url=f"postgresql://{HOST}")
    assert settings.database_url == f"postgresql+{POSTGRES_DRIVER}://{HOST}"


def test_settings_leaves_an_explicit_driver_alone():
    url = "postgresql+asyncpg://user@host/db"
    assert Settings(database_url=url).database_url == url


def test_the_normalised_url_resolves_to_the_installed_dialect():
    """The actual assertion behind all of this: the pinned URL selects a DBAPI
    that is installed. Resolving the dialect imports the driver, which is
    precisely what failed in deployment."""
    from sqlalchemy.engine.url import make_url

    url = make_url(Settings(database_url=f"postgresql://{HOST}").database_url)
    dialect = url.get_dialect()

    assert dialect.driver == POSTGRES_DRIVER
    # `get_dialect()` returns the dialect CLASS; `import_dbapi()` is the
    # SQLAlchemy 2.0 classmethod that actually imports the driver module —
    # the exact step that raised ModuleNotFoundError in deployment.
    assert dialect.import_dbapi().__name__.startswith(POSTGRES_DRIVER)


def test_psycopg2_is_not_installed_and_is_not_meant_to_be():
    """The fix is a URL translation, not a second Postgres driver."""
    import importlib.util

    assert importlib.util.find_spec("psycopg2") is None
    assert importlib.util.find_spec("psycopg") is not None


def test_a_missing_database_url_still_fails_loudly():
    """Normalisation must not turn a missing URL into a usable-looking one."""
    with pytest.raises(ValidationError):
        Settings(_env_file=None, database_url=None)
