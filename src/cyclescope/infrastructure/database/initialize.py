"""Database initialization entry point and idempotent industry seeding."""

import logging
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from cyclescope.infrastructure.config import get_settings
from cyclescope.infrastructure.database.models import IndustryModel
from cyclescope.infrastructure.database.session import (
    create_database_engine,
    create_session_factory,
)
from cyclescope.infrastructure.logging import configure_logging

logger = logging.getLogger(__name__)
INITIAL_INDUSTRIES = (
    ("SEMICONDUCTOR", "Semiconductor"),
    ("LITHIUM_BATTERY", "Lithium & Battery"),
    ("CHEMICALS", "Chemicals"),
    ("NON_FERROUS_METALS", "Non-ferrous Metals"),
    ("SHIPPING", "Shipping"),
    ("OIL_GAS", "Oil & Gas"),
    ("STEEL", "Steel"),
)


def seed_industries(session: Session) -> None:
    """Insert missing initial industries while preserving existing records."""
    existing = set(session.scalars(select(IndustryModel.code)).all())
    session.add_all(
        IndustryModel(code=code, name=name)
        for code, name in INITIAL_INDUSTRIES
        if code not in existing
    )


def main() -> None:
    """Run Alembic migrations and seed industries without deleting data."""
    from alembic import command
    from alembic.config import Config

    settings = get_settings()
    configure_logging(settings.log_level, settings.log_directory)
    settings.data_directory.mkdir(parents=True, exist_ok=True)
    project_root = Path(__file__).resolve().parents[4]
    config = Config(str(project_root / "alembic.ini"))
    config.set_main_option("script_location", str(project_root / "migrations"))
    config.set_main_option("sqlalchemy.url", settings.database_url.replace("%", "%%"))
    command.upgrade(config, "head")
    factory = create_session_factory(create_database_engine(settings.database_url))
    with factory.begin() as session:
        seed_industries(session)
    logger.info("Database schema is current and industry seed data is present.")


if __name__ == "__main__":
    main()
