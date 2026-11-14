from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import func, select

from cyclescope.domain.entities.value_score import (
    ValueScore,
    ValueScoreComponent,
    ValueScoreComponentCode,
    ValueScoreComponentStatus,
    ValueScoreConfidence,
    ValueScoreConfig,
    ValueScoreStatus,
)
from cyclescope.infrastructure.database.models import CompanyModel, SecurityModel
from cyclescope.infrastructure.database.models.value_score import ValueScoreModel
from cyclescope.infrastructure.database.repositories.value_score import (
    SQLAlchemyValueScoreRepository,
)


def _insufficient_score(security_id: int, company_id: int) -> ValueScore:
    components = tuple(
        ValueScoreComponent(
            code, ValueScoreComponentStatus.UNAVAILABLE, None, "not available"
        )
        for code in ValueScoreComponentCode
    )
    return ValueScore(
        security_id=security_id,
        company_id=company_id,
        as_of=datetime(2026, 1, 1, tzinfo=UTC),
        score=None,
        coverage=Decimal(0),
        status=ValueScoreStatus.INSUFFICIENT_DATA,
        confidence=ValueScoreConfidence.INSUFFICIENT,
        config_version=1,
        config_snapshot=ValueScoreConfig().snapshot(),
        components=components,
        status_reason="Coverage is insufficient.",
    )


def test_value_score_persistence_is_append_only_and_round_trips(session) -> None:
    company = CompanyModel(name="Score Co", country_code="JP")
    session.add(company)
    session.flush()
    security = SecurityModel(company_id=company.id, security_type="COMMON")
    session.add(security)
    session.flush()
    repository = SQLAlchemyValueScoreRepository(session)
    first = repository.create(_insufficient_score(security.id, company.id))
    second = repository.create(_insufficient_score(security.id, company.id))
    session.flush()
    assert first.id != second.id
    restored = repository.get_by_id(first.id)
    assert restored is not None
    assert restored.components == first.components
    assert len(repository.list_by_security(security.id)) == 2


def test_value_score_transaction_rollback_removes_only_new_snapshot(session) -> None:
    company = CompanyModel(name="Rollback Score Co", country_code="JP")
    session.add(company)
    session.flush()
    security = SecurityModel(company_id=company.id, security_type="COMMON")
    session.add(security)
    session.flush()
    repository = SQLAlchemyValueScoreRepository(session)
    prior = repository.create(_insufficient_score(security.id, company.id))
    session.commit()
    repository.create(_insufficient_score(security.id, company.id))
    session.rollback()
    assert session.scalar(select(func.count()).select_from(ValueScoreModel)) == 1
    assert repository.get_by_id(prior.id) is not None
