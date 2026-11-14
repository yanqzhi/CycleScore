"""Persistence adapter for append-only Value Score snapshots."""

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, cast

from sqlalchemy import select
from sqlalchemy.orm import Session

from cyclescope.domain.entities.value_score import (
    ValueScore,
    ValueScoreComponent,
    ValueScoreComponentCode,
    ValueScoreComponentStatus,
    ValueScoreConfidence,
    ValueScoreInputReference,
    ValueScoreMeasure,
    ValueScoreStatus,
)
from cyclescope.domain.repositories.contracts import ValueScoreRepository
from cyclescope.infrastructure.database.models.value_score import ValueScoreModel


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _ref_dict(ref: ValueScoreInputReference) -> dict[str, object]:
    return {
        "record_type": ref.record_type,
        "record_id": ref.record_id,
        "available_at": ref.available_at.isoformat(),
        "source_id": ref.source_id,
        "financial_source_ids": list(ref.financial_source_ids),
        "revision_number": ref.revision_number,
        "observation_date": ref.observation_date.isoformat()
        if ref.observation_date
        else None,
        "security_id": ref.security_id,
        "reference_code": ref.reference_code,
    }


def _component_dict(component: ValueScoreComponent) -> dict[str, object]:
    return {
        "code": component.code.value,
        "status": component.status.value,
        "score": str(component.score) if component.score is not None else None,
        "reason": component.reason,
        "original_weight": str(component.original_weight),
        "effective_weight": str(component.effective_weight),
        "exclusion_reasons": list(component.exclusion_reasons),
        "excluded_peer_reasons": [
            [peer_id, reason] for peer_id, reason in component.excluded_peer_reasons
        ],
        "coverage": str(component.coverage) if component.coverage is not None else None,
        "peer_security_ids": list(component.peer_security_ids),
        "measures": [
            {
                "code": m.code,
                "value": str(m.value) if m.value is not None else None,
                "unit": m.unit,
                "score": str(m.score) if m.score is not None else None,
                "reason": m.reason,
            }
            for m in component.measures
        ],
        "input_references": [_ref_dict(ref) for ref in component.input_references],
    }


def _domain(row: ValueScoreModel) -> ValueScore:
    components = []
    component_data = cast(list[dict[str, Any]], row.components)
    for item in component_data:
        measure_data = cast(list[dict[str, Any]], item["measures"])
        component_coverage: Decimal | None
        if "coverage" in item and item["coverage"] is not None:
            component_coverage = Decimal(item["coverage"])
        elif item["status"] == ValueScoreComponentStatus.AVAILABLE.value:
            component_coverage = Decimal(1)
        elif item["status"] in {
            ValueScoreComponentStatus.UNAVAILABLE.value,
            ValueScoreComponentStatus.INVALID_INPUT.value,
        }:
            component_coverage = Decimal(0)
        else:
            measure_count = len(measure_data)
            usable_count = sum(measure["score"] is not None for measure in measure_data)
            component_coverage = (
                Decimal(usable_count) / Decimal(measure_count)
                if measure_count and usable_count
                else None
            )
        refs = tuple(
            ValueScoreInputReference(
                record_type=ref["record_type"],
                record_id=int(ref["record_id"]),
                available_at=_utc(datetime.fromisoformat(ref["available_at"])),
                source_id=ref["source_id"],
                financial_source_ids=tuple(ref.get("financial_source_ids", ())),
                revision_number=ref["revision_number"],
                observation_date=datetime.fromisoformat(ref["observation_date"]).date()
                if ref["observation_date"]
                else None,
                security_id=ref["security_id"],
                reference_code=ref["reference_code"],
            )
            for ref in item["input_references"]
        )
        measures = tuple(
            ValueScoreMeasure(
                code=measure["code"],
                value=Decimal(measure["value"])
                if measure["value"] is not None
                else None,
                unit=measure["unit"],
                score=Decimal(measure["score"])
                if measure["score"] is not None
                else None,
                reason=measure["reason"],
            )
            for measure in measure_data
        )
        components.append(
            ValueScoreComponent(
                code=ValueScoreComponentCode(item["code"]),
                status=ValueScoreComponentStatus(item["status"]),
                score=Decimal(item["score"]) if item["score"] is not None else None,
                reason=item["reason"],
                measures=measures,
                input_references=refs,
                peer_security_ids=tuple(item["peer_security_ids"]),
                original_weight=Decimal(item["original_weight"]),
                effective_weight=Decimal(item["effective_weight"]),
                exclusion_reasons=tuple(item.get("exclusion_reasons", ())),
                excluded_peer_reasons=tuple(
                    (int(peer_id), str(reason))
                    for peer_id, reason in item.get("excluded_peer_reasons", ())
                ),
                coverage=component_coverage,
            )
        )
    return ValueScore(
        id=row.id,
        security_id=row.security_id,
        company_id=row.company_id,
        as_of=_utc(row.as_of),
        score=row.score,
        coverage=row.coverage,
        status=ValueScoreStatus(row.status),
        confidence=ValueScoreConfidence(row.confidence),
        config_version=row.config_version,
        config_snapshot=row.config_snapshot,
        components=tuple(components),
        status_reason=row.status_reason,
        created_at=_utc(row.created_at),
    )


class SQLAlchemyValueScoreRepository(ValueScoreRepository):
    """Only create/read methods are exposed; no mutation or deletion API exists."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def create(self, result: ValueScore) -> ValueScore:
        row = ValueScoreModel(
            security_id=result.security_id,
            company_id=result.company_id,
            as_of=result.as_of.replace(tzinfo=None),
            score=result.score,
            coverage=result.coverage,
            status=result.status.value,
            confidence=result.confidence.value,
            config_version=result.config_version,
            config_snapshot=result.config_snapshot,
            components=[_component_dict(component) for component in result.components],
            status_reason=result.status_reason,
        )
        self._session.add(row)
        self._session.flush()
        self._session.refresh(row)
        return _domain(row)

    def get_by_id(self, result_id: int) -> ValueScore | None:
        row = self._session.get(ValueScoreModel, result_id)
        return _domain(row) if row is not None else None

    def list_by_security(
        self, security_id: int, *, as_of: datetime | None = None
    ) -> list[ValueScore]:
        statement = select(ValueScoreModel).where(
            ValueScoreModel.security_id == security_id
        )
        if as_of is not None:
            statement = statement.where(
                ValueScoreModel.as_of <= as_of.astimezone(UTC).replace(tzinfo=None)
            )
        statement = statement.order_by(ValueScoreModel.as_of, ValueScoreModel.id)
        return [_domain(row) for row in self._session.scalars(statement).all()]
