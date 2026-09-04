"""Normalising a database URL onto the driver this project actually installs.

WHY THIS EXISTS
SQLAlchemy picks its DBAPI from the URL scheme, and bare `postgresql://`
resolves to the **psycopg2** dialect — a driver this project deliberately does
not install. It uses psycopg 3, which SQLAlchemy reaches through the explicit
`postgresql+psycopg://` scheme.

Locally that never bites, because docker-compose.yml writes the explicit scheme.
It bites the moment the URL comes from somewhere else: every managed Postgres
provider hands out a generic `postgresql://` (or the older `postgres://`)
connection string, because that is the standard libpq form and says nothing
about which Python driver will consume it. The result is a build that succeeds
and a first migration that dies with:

    ModuleNotFoundError: No module named 'psycopg2'

which points at a missing dependency rather than at the URL that asked for it.

The fix is to translate the scheme once, at the point the URL enters the
application, rather than to install a second Postgres driver or to require
every deployment target to know about our DBAPI choice.

WHY ITS OWN MODULE
`app.config` builds a `Settings` instance at import time, and `app.db` builds
an engine from it — so importing either one has already chosen a database.
This module has no import-time side effects, which is what lets the test
harness and the demo loader normalise a URL *before* deciding which database to
point at.

WHAT IT DELIBERATELY DOES NOT DO
It rewrites the scheme and nothing else. Everything after `://` — credentials,
host, port, path, query string, percent-encoding — is preserved byte for byte,
because re-serialising a parsed URL risks re-encoding a password that was
already correct. An explicit driver is never overridden: a URL that says
`postgresql+asyncpg://` means it, and silently retargeting it would be worse
than the error it replaced.
"""

from __future__ import annotations

#: Schemes that mean "PostgreSQL, driver unspecified".
#:
#: `postgres://` is the older form still issued by several hosting providers.
#: SQLAlchemy removed it as an alias in 1.4 and rejects it outright, so leaving
#: it alone would only trade one confusing startup error for another.
GENERIC_POSTGRES_SCHEMES = frozenset({"postgresql", "postgres"})

#: The driver this project installs. psycopg 3, not psycopg2.
POSTGRES_DRIVER = "psycopg"

_SEPARATOR = "://"


def normalise_database_url(url: str) -> str:
    """Return `url` with a generic PostgreSQL scheme pinned to psycopg 3.

    >>> normalise_database_url("postgresql://u:p@host:5432/db")
    'postgresql+psycopg://u:p@host:5432/db'

    Anything else is returned unchanged: a scheme that already names a driver,
    a non-PostgreSQL database, or a string that is not a URL at all — that last
    case is left for SQLAlchemy to reject, with its own better message.
    """
    scheme, separator, remainder = url.partition(_SEPARATOR)
    if not separator:
        return url

    # Schemes are case-insensitive; the rest of the URL is not touched.
    if scheme.lower() in GENERIC_POSTGRES_SCHEMES:
        return f"postgresql+{POSTGRES_DRIVER}{_SEPARATOR}{remainder}"

    return url
