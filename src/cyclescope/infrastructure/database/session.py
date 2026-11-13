"""Database engine, sessions, transactions, and SQLite FK enforcement."""

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker


def create_database_engine(database_url: str, *, echo: bool = False) -> Engine:
    """Create an engine, enabling SQLite foreign keys when applicable."""
    options: dict[str, object] = {"echo": echo}
    if database_url.startswith("sqlite"):
        options["connect_args"] = {"check_same_thread": False}
    engine = create_engine(database_url, **options)
    if engine.dialect.name == "sqlite":

        @event.listens_for(engine, "connect")
        def enable_foreign_keys(dbapi_connection: object, _: object) -> None:
            cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    return engine


def create_session_factory(engine: Engine) -> sessionmaker[Session]:
    """Create a session factory bound to an engine."""
    return sessionmaker(bind=engine, expire_on_commit=False)


@contextmanager
def transaction(session_factory: sessionmaker[Session]) -> Iterator[Session]:
    """Yield a session and commit on success, rolling back on failure."""
    session = session_factory()
    try:
        with session.begin():
            yield session
    finally:
        session.close()
