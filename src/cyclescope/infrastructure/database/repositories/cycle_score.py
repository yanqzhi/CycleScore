"""Append-only SQLAlchemy adapter for Cycle Score snapshots."""

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, cast

from sqlalchemy import select
from sqlalchemy.orm import Session

from cyclescope.domain.entities.cycle_score import (
    CyclePhase,
    CycleScore,
    CycleScoreComponent,
    CycleScoreComponentCode,
    CycleScoreComponentStatus,
    CycleScoreConfidence,
    CycleScoreInputReference,
    CycleScoreStatus,
)
from cyclescope.domain.exceptions import DomainValidationError
from cyclescope.domain.repositories.contracts import CycleScoreRepository
from cyclescope.infrastructure.database.models.cycle_score import CycleScoreModel


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _reference_dict(reference: CycleScoreInputReference) -> dict[str, object]:
    return {
        "record_id": reference.record_id,
        "statement_id": reference.statement_id,
        "normalized_earnings_result_id": reference.normalized_earnings_result_id,
        "source_id": reference.source_id,
        "revision_number": reference.revision_number,
        "fiscal_year": reference.fiscal_year,
        "fiscal_period": reference.fiscal_period,
        "item_code": reference.item_code,
        "period_start": reference.period_start.isoformat()
        if reference.period_start
        else None,
        "period_end": reference.period_end.isoformat(),
        "publication_date": reference.publication_date.isoformat()
        if reference.publication_date
        else None,
        "publication_datetime": reference.publication_datetime.isoformat()
        if reference.publication_datetime
        else None,
        "available_at": reference.available_at.isoformat(),
    }


def _component_dict(component: CycleScoreComponent) -> dict[str, object]:
    return {
        "code": component.code.value,
        "status": component.status.value,
        "score": str(component.score) if component.score is not None else None,
        "value": str(component.value) if component.value is not None else None,
        "coverage": str(component.coverage) if component.coverage is not None else None,
        "reason": component.reason,
    }


def _to_domain(row: CycleScoreModel) -> CycleScore:
    raw_components = cast(list[dict[str, Any]], row.components)
    raw_references = cast(list[dict[str, Any]], row.input_references)
    components = tuple(
        CycleScoreComponent(
            code=CycleScoreComponentCode(item["code"]),
            status=CycleScoreComponentStatus(item["status"]),
            score=Decimal(item["score"]) if item["score"] is not None else None,
            value=Decimal(item["value"]) if item["value"] is not None else None,
            coverage=(
                Decimal(item["coverage"]) if item["coverage"] is not None else None
            ),
            reason=item["reason"],
        )
        for item in raw_components
    )
    references = tuple(
        CycleScoreInputReference(
            record_id=item["record_id"],
            statement_id=item["statement_id"],
            normalized_earnings_result_id=item["normalized_earnings_result_id"],
            source_id=item["source_id"],
            revision_number=item["revision_number"],
            fiscal_year=item["fiscal_year"],
            fiscal_period=item["fiscal_period"],
            item_code=item["item_code"],
            period_end=datetime.fromisoformat(item["period_end"]).date(),
            available_at=datetime.fromisoformat(item["available_at"]),
            period_start=(
                datetime.fromisoformat(item["period_start"]).date()
                if item.get("period_start")
                else None
            ),
            publication_date=(
                datetime.fromisoformat(item["publication_date"]).date()
                if item.get("publication_date")
                else None
            ),
            publication_datetime=(
                datetime.fromisoformat(item["publication_datetime"])
                if item.get("publication_datetime")
                else None
            ),
        )
        for item in raw_references
    )
    return CycleScore(
        id=row.id,
        company_id=row.company_id,
        security_id=row.security_id,
        as_of=_utc(row.as_of),
        score=row.score,
        status=CycleScoreStatus(row.status),
        phase=CyclePhase(row.phase),
        phase_reason=row.phase_reason,
        confidence=CycleScoreConfidence(row.confidence),
        coverage=row.coverage,
        currency=row.currency,
        source_id=row.source_id,
        normalized_earnings_result_id=row.normalized_earnings_result_id,
        calculation_version=row.calculation_version,
        config_snapshot=row.config_snapshot,
        components=components,
        input_references=references,
        status_reason=row.status_reason,
        created_at=_utc(row.created_at),
    )


class SQLAlchemyCycleScoreRepository(CycleScoreRepository):
    """Create/read methods only; callers own all transaction boundaries."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def create(self, result: CycleScore) -> CycleScore:
        row = CycleScoreModel(
            company_id=result.company_id,
            security_id=result.security_id,
            as_of=result.as_of.replace(tzinfo=None),
            score=result.score,
            status=result.status.value,
            phase=result.phase.value,
            phase_reason=result.phase_reason,
            confidence=result.confidence.value,
            coverage=result.coverage,
            currency=result.currency,
            source_id=result.source_id,
            normalized_earnings_result_id=result.normalized_earnings_result_id,
            calculation_version=result.calculation_version,
            config_snapshot=result.config_snapshot,
            components=[_component_dict(component) for component in result.components],
            input_references=[
                _reference_dict(reference) for reference in result.input_references
            ],
            status_reason=result.status_reason,
        )
        self._session.add(row)
        self._session.flush()
        self._session.refresh(row)
        return _to_domain(row)

    def get_by_id(self, result_id: int) -> CycleScore | None:
        row = self._session.get(CycleScoreModel, result_id)
        return _to_domain(row) if row is not None else None

    def list_by_company(
        self, company_id: int, *, as_of: datetime | None = None
    ) -> list[CycleScore]:
        query = select(CycleScoreModel).where(CycleScoreModel.company_id == company_id)
        if as_of is not None:
            if as_of.tzinfo is None or as_of.utcoffset() is None:
                raise DomainValidationError("as_of must be timezone-aware.")
            query = query.where(CycleScoreModel.as_of <= as_of.astimezone(UTC))
        rows = self._session.scalars(
            query.order_by(CycleScoreModel.as_of, CycleScoreModel.id)
        )
        return [_to_domain(row) for row in rows]
