"""Append-only SQLAlchemy adapter for inventory snapshots."""

from datetime import UTC, date, datetime
from typing import Any, cast

from sqlalchemy import select
from sqlalchemy.orm import Session

from cyclescope.domain.entities.inventory import (
    InventoryConfidence,
    InventoryInputReference,
    InventorySnapshot,
    InventoryStatus,
    InventoryTrend,
)
from cyclescope.domain.exceptions import DomainValidationError
from cyclescope.domain.repositories.contracts import InventorySnapshotRepository
from cyclescope.infrastructure.database.models.inventory import InventorySnapshotModel


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _reference_dict(reference: InventoryInputReference) -> dict[str, object]:
    return {
        "statement_id": reference.statement_id,
        "statement_item_id": reference.statement_item_id,
        "source_id": reference.source_id,
        "revision_number": reference.revision_number,
        "fiscal_year": reference.fiscal_year,
        "fiscal_period": reference.fiscal_period,
        "item_code": reference.item_code,
        "period_start": reference.period_start.isoformat()
        if reference.period_start
        else None,
        "period_end": reference.period_end.isoformat(),
        "available_at": reference.available_at.isoformat(),
        "publication_date": reference.publication_date.isoformat(),
        "publication_datetime": (
            reference.publication_datetime.isoformat()
            if reference.publication_datetime
            else None
        ),
    }


def _to_domain(row: InventorySnapshotModel) -> InventorySnapshot:
    refs = cast(list[dict[str, Any]], row.input_references)
    return InventorySnapshot(
        id=row.id,
        company_id=row.company_id,
        security_id=row.security_id,
        as_of=_utc(row.as_of),
        fiscal_year=row.fiscal_year,
        period_start=row.period_start,
        period_end=row.period_end,
        closing_inventory=row.closing_inventory,
        opening_inventory=row.opening_inventory,
        average_inventory=row.average_inventory,
        cogs=row.cogs,
        inventory_change=row.inventory_change,
        inventory_growth=row.inventory_growth,
        inventory_turnover=row.inventory_turnover,
        dio=row.dio,
        trend=InventoryTrend(row.trend),
        status=InventoryStatus(row.status),
        unavailable_reasons=tuple(row.unavailable_reasons),
        data_coverage=row.data_coverage,
        confidence=InventoryConfidence(row.confidence),
        currency=row.currency,
        source_id=row.source_id,
        calculation_version=row.calculation_version,
        config_snapshot=row.config_snapshot,
        input_references=tuple(
            InventoryInputReference(
                statement_id=ref["statement_id"],
                statement_item_id=ref["statement_item_id"],
                source_id=ref["source_id"],
                revision_number=ref["revision_number"],
                fiscal_year=ref["fiscal_year"],
                fiscal_period=ref["fiscal_period"],
                item_code=ref["item_code"],
                period_start=date.fromisoformat(ref["period_start"])
                if ref["period_start"]
                else None,
                period_end=date.fromisoformat(ref["period_end"]),
                available_at=datetime.fromisoformat(ref["available_at"]),
                publication_date=date.fromisoformat(ref["publication_date"]),
                publication_datetime=datetime.fromisoformat(ref["publication_datetime"])
                if ref["publication_datetime"]
                else None,
            )
            for ref in refs
        ),
        created_at=_utc(row.created_at),
    )


class SQLAlchemyInventorySnapshotRepository(InventorySnapshotRepository):
    """Create and read methods only; all transaction control belongs to callers."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def create(self, result: InventorySnapshot) -> InventorySnapshot:
        row = InventorySnapshotModel(
            company_id=result.company_id,
            security_id=result.security_id,
            as_of=result.as_of.replace(tzinfo=None),
            fiscal_year=result.fiscal_year,
            period_start=result.period_start,
            period_end=result.period_end,
            closing_inventory=result.closing_inventory,
            opening_inventory=result.opening_inventory,
            average_inventory=result.average_inventory,
            cogs=result.cogs,
            inventory_change=result.inventory_change,
            inventory_growth=result.inventory_growth,
            inventory_turnover=result.inventory_turnover,
            dio=result.dio,
            trend=result.trend.value,
            status=result.status.value,
            unavailable_reasons=list(result.unavailable_reasons),
            data_coverage=result.data_coverage,
            confidence=result.confidence.value,
            currency=result.currency,
            source_id=result.source_id,
            calculation_version=result.calculation_version,
            config_snapshot=result.config_snapshot,
            input_references=[
                _reference_dict(reference) for reference in result.input_references
            ],
        )
        self._session.add(row)
        self._session.flush()
        self._session.refresh(row)
        return _to_domain(row)

    def list_by_company(
        self, company_id: int, *, as_of: datetime | None = None
    ) -> list[InventorySnapshot]:
        query = select(InventorySnapshotModel).where(
            InventorySnapshotModel.company_id == company_id
        )
        if as_of is not None:
            if as_of.tzinfo is None or as_of.utcoffset() is None:
                raise DomainValidationError("as_of must be timezone-aware.")
            query = query.where(InventorySnapshotModel.as_of <= as_of.astimezone(UTC))
        return [
            _to_domain(row)
            for row in self._session.scalars(
                query.order_by(
                    InventorySnapshotModel.as_of,
                    InventorySnapshotModel.fiscal_year,
                    InventorySnapshotModel.id,
                )
            )
        ]
