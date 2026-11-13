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
    """Run an atomic unit of work, reserving SQLite's single writer up front."""
    session = session_factory()
    try:
        if session.get_bind().dialect.name == "sqlite":
            # A deferred SQLite transaction can validate against a stale read
            # snapshot before competing to write. IMMEDIATE serializes writers
            # before Application check-then-insert rules execute.
            session.connection().exec_driver_sql("BEGIN IMMEDIATE")
            yield session
            session.commit()
        else:
            with session.begin():
                yield session
    except BaseException:
        session.rollback()
        raise
    finally:
        session.close()
