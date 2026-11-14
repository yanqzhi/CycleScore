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
    ValueScoreMeasure,
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


def test_legacy_component_coverage_is_recovered_or_left_unknown(session) -> None:
    company = CompanyModel(name="Legacy Co", country_code="JP")
    session.add(company)
    session.flush()
    security = SecurityModel(company_id=company.id, security_type="COMMON")
    session.add(security)
    session.flush()
    codes = tuple(ValueScoreComponentCode)
    legacy_components = []
    for index, code in enumerate(codes):
        status = (
            "AVAILABLE" if index == 0 else "UNAVAILABLE" if index == 1 else "PARTIAL"
        )
        measures = []
        score = "70"
        reason = None
        if status == "AVAILABLE":
            measures = [
                {
                    "code": code.value,
                    "value": "20",
                    "unit": "RATIO",
                    "score": "70",
                    "reason": None,
                }
            ]
        elif status == "UNAVAILABLE":
            score = None
            reason = "legacy missing"
        elif index == 2:
            reason = "legacy partial with submetrics"
            measures = [
                {
                    "code": "available",
                    "value": "20",
                    "unit": "RATIO",
                    "score": "70",
                    "reason": None,
                },
                {
                    "code": "missing",
                    "value": None,
                    "unit": "RATIO",
                    "score": None,
                    "reason": "missing",
                },
            ]
        else:
            reason = "legacy partial without measures"
        legacy_components.append(
            {
                "code": code.value,
                "status": status,
                "score": score,
                "reason": reason,
                "original_weight": "0.1",
                "effective_weight": "0.2" if score is not None else "0",
                "peer_security_ids": [],
                "measures": measures,
                "input_references": [],
            }
        )
    row = ValueScoreModel(
        security_id=security.id,
        company_id=company.id,
        as_of=datetime(2026, 1, 1),
        score=Decimal("70"),
        coverage=Decimal("0.8"),
        status="PARTIAL",
        confidence="MEDIUM",
        config_version=1,
        config_snapshot=ValueScoreConfig().snapshot(),
        components=legacy_components,
        status_reason="legacy result",
    )
    session.add(row)
    session.flush()
    restored = SQLAlchemyValueScoreRepository(session).get_by_id(row.id)
    assert restored is not None
    components = {component.code: component for component in restored.components}
    assert components[codes[0]].coverage == Decimal(1)
    assert components[codes[1]].coverage == Decimal(0)
    assert components[codes[2]].coverage == Decimal("0.5")
    assert components[codes[3]].coverage is None
    assert restored.coverage == Decimal("0.8")
    assert restored.score == Decimal("70")
    assert session.get(ValueScoreModel, row.id).components == legacy_components


def test_new_component_coverage_round_trips_explicitly(session) -> None:
    company = CompanyModel(name="Explicit Coverage Co", country_code="JP")
    session.add(company)
    session.flush()
    security = SecurityModel(company_id=company.id, security_type="COMMON")
    session.add(security)
    session.flush()
    components = []
    for code in ValueScoreComponentCode:
        if code == ValueScoreComponentCode.HISTORICAL_VALUATION:
            components.append(
                ValueScoreComponent(
                    code,
                    ValueScoreComponentStatus.PARTIAL,
                    Decimal("80"),
                    "PBR unavailable",
                    measures=(
                        ValueScoreMeasure(
                            "PER", Decimal(20), "PERCENTILE", Decimal(80)
                        ),
                        ValueScoreMeasure("PBR", None, "PERCENTILE", None, "missing"),
                    ),
                    coverage=Decimal("0.5"),
                    original_weight=Decimal("0.2"),
                    effective_weight=Decimal("0.1"),
                )
            )
        else:
            components.append(
                ValueScoreComponent(
                    code,
                    ValueScoreComponentStatus.UNAVAILABLE,
                    None,
                    "missing",
                    original_weight=Decimal("0.16"),
                    effective_weight=Decimal("0.18"),
                )
            )
    # Persist an explicitly covered component as a realistic snapshot. The
    # repository round-trip must preserve 0.5 exactly.
    score = ValueScore(
        security_id=security.id,
        company_id=company.id,
        as_of=datetime(2026, 1, 1, tzinfo=UTC),
        score=Decimal("80"),
        coverage=Decimal("0.1"),
        status=ValueScoreStatus.PARTIAL,
        confidence=ValueScoreConfidence.LOW,
        config_version=1,
        config_snapshot=ValueScoreConfig().snapshot(),
        components=tuple(components),
        status_reason="partial coverage",
    )
    restored = SQLAlchemyValueScoreRepository(session).create(score)
    historical = next(
        item
        for item in restored.components
        if item.code == ValueScoreComponentCode.HISTORICAL_VALUATION
    )
    assert historical.coverage == Decimal("0.5")
