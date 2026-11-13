"""Shared temporary database fixtures."""

import pytest
from sqlalchemy.orm import Session

from cyclescope.infrastructure.database.base import Base
from cyclescope.infrastructure.database.session import create_database_engine


@pytest.fixture
def session(tmp_path: object) -> Session:
    """Return a session connected to an isolated temporary SQLite database."""
    db_path = tmp_path / "test.db"  # type: ignore[operator]
    engine = create_database_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(engine)
    with Session(engine) as db_session:
        yield db_session
    engine.dispose()
