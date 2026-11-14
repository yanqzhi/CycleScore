"""Database initialization entry point and idempotent industry seeding."""

import logging
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from cyclescope.domain.services.valuation import default_metric_definitions
from cyclescope.infrastructure.config import get_settings
from cyclescope.infrastructure.database.models import (
    IndustryModel,
    ValuationMetricModel,
)
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


def seed_valuation_metrics(session: Session) -> None:
    """Insert missing initial definitions without overwriting local changes."""
    existing = set(session.scalars(select(ValuationMetricModel.metric_code)).all())
    for definition in default_metric_definitions():
        if definition.metric_code.value in existing:
            continue
        session.add(
            ValuationMetricModel(
                metric_code=definition.metric_code.value,
                metric_name=definition.metric_name,
                description=definition.description,
                unit=definition.unit.value,
                currency_applicability=definition.currency_applicability.value,
                required_inputs=list(definition.required_inputs),
                calculation_method=definition.calculation_method,
                calculation_version=definition.calculation_version,
                validity_rules=list(definition.validity_rules),
                is_active=definition.is_active,
            )
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
        seed_valuation_metrics(session)
    logger.info(
        "Database schema is current and initial industry/valuation masters are present."
    )


if __name__ == "__main__":
    main()
