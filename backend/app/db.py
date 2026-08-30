"""Database engine, session factory and the declarative base."""

from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import settings

engine = create_engine(
    settings.database_url,
    # Issues a lightweight "SELECT 1" before handing a pooled connection to
    # the application, and transparently replaces it if the check fails.
    # This is the runtime counterpart to depends_on in docker-compose.yml:
    # Compose orders startup, pool_pre_ping survives the database restarting
    # or dropping connections *after* startup.
    pool_pre_ping=True,
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    """Declarative base for all ORM models.

    SQLAlchemy 2.0 style: a subclass of DeclarativeBase rather than the
    legacy `declarative_base()` factory. Models inherit from this in
    app/models/.
    """


def get_db() -> Iterator[Session]:
    """FastAPI dependency yielding a session, closed when the request ends.

    Creating a Session does not open a connection — SQLAlchemy acquires one
    lazily on first query — so a database outage surfaces inside the route
    handler where it can be handled, not while resolving the dependency.
    """
    with SessionLocal() as session:
        yield session
