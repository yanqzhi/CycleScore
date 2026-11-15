"""SQLAlchemy repository for immutable industry inventory analyses."""

from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from cyclescope.domain.entities.industry_inventory import (
    IndustryInventoryClassification,
    IndustryInventoryConfig,
    IndustryInventoryInputReference,
    IndustryInventorySnapshot,
    IndustryInventoryStatus,
    IndustryInventoryTrend,
)
from cyclescope.domain.exceptions import DomainValidationError
from cyclescope.domain.repositories.contracts import IndustryInventoryRepository
from cyclescope.infrastructure.database.models.industry_inventory import (
    IndustryInventoryInputModel,
    IndustryInventoryScopeModel,
    IndustryInventorySnapshotModel,
)


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _config_dict(config: IndustryInventoryConfig) -> dict[str, str | int]:
    return {
        "version": config.version,
        "accumulation_yoy": str(config.accumulation_yoy),
        "rapid_accumulation_yoy": str(config.rapid_accumulation_yoy),
        "normalization_prior_yoy": str(config.normalization_prior_yoy),
        "normalization_growth_ceiling": str(config.normalization_growth_ceiling),
        "stable_growth_tolerance": str(config.stable_growth_tolerance),
        "gap_ratio_tolerance": str(config.gap_ratio_tolerance),
        "minimum_coverage": str(config.minimum_coverage),
    }


def _from_config(value: dict[str, str | int]) -> IndustryInventoryConfig:
    return IndustryInventoryConfig(
        version=int(value["version"]),
        accumulation_yoy=Decimal(str(value["accumulation_yoy"])),
        rapid_accumulation_yoy=Decimal(str(value["rapid_accumulation_yoy"])),
        normalization_prior_yoy=Decimal(str(value["normalization_prior_yoy"])),
        normalization_growth_ceiling=Decimal(
            str(value["normalization_growth_ceiling"])
        ),
        stable_growth_tolerance=Decimal(str(value["stable_growth_tolerance"])),
        gap_ratio_tolerance=Decimal(str(value["gap_ratio_tolerance"])),
        minimum_coverage=Decimal(str(value["minimum_coverage"])),
    )


def _to_domain(
    row: IndustryInventorySnapshotModel,
    inputs: tuple[IndustryInventoryInputReference, ...],
    scopes: tuple[tuple[tuple[int, str], ...], tuple[tuple[int, str], ...]],
) -> IndustryInventorySnapshot:
    return IndustryInventorySnapshot(
        id=row.id,
        industry_id=row.industry_id,
        sub_industry_id=row.sub_industry_id,
        aggregate_region_code=row.aggregate_region_code,
        source_id=row.source_id,
        unit_code=row.unit_code,
        currency_code=row.currency_code,
        observation_date=row.observation_date,
        as_of=_utc(row.as_of),
        calculated_at=_utc(row.calculated_at),
        classification=IndustryInventoryClassification(row.classification),
        trend=IndustryInventoryTrend(row.trend),
        status=IndustryInventoryStatus(row.status),
        inventory_value=row.inventory_value,
        prior_inventory_value=row.prior_inventory_value,
        absolute_change=row.absolute_change,
        yoy_growth=row.yoy_growth,
        prior_yoy_growth=row.prior_yoy_growth,
        growth_acceleration=row.growth_acceleration,
        production_value=row.production_value,
        shipments_value=row.shipments_value,
        production_shipment_gap=row.production_shipment_gap,
        coverage=row.coverage,
        confidence=row.confidence,
        config=_from_config(row.config_snapshot),
        requested_scope=scopes[0],
        contributing_regions=scopes[1],
        input_references=inputs,
        unavailable_reasons=tuple(row.unavailable_reasons),
    )


class SQLAlchemyIndustryInventoryRepository(IndustryInventoryRepository):
    """Append and retrieve snapshots; commits remain the caller's responsibility."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def create(self, snapshot: IndustryInventorySnapshot) -> IndustryInventorySnapshot:
        row = IndustryInventorySnapshotModel(
            industry_id=snapshot.industry_id,
            sub_industry_id=snapshot.sub_industry_id,
            aggregate_region_code=snapshot.aggregate_region_code,
            source_id=snapshot.source_id,
            unit_code=snapshot.unit_code,
            currency_code=snapshot.currency_code,
            observation_date=snapshot.observation_date,
            as_of=snapshot.as_of.replace(tzinfo=None),
            calculated_at=snapshot.calculated_at.replace(tzinfo=None),
            classification=snapshot.classification.value,
            trend=snapshot.trend.value,
            status=snapshot.status.value,
            inventory_value=snapshot.inventory_value,
            prior_inventory_value=snapshot.prior_inventory_value,
            absolute_change=snapshot.absolute_change,
            yoy_growth=snapshot.yoy_growth,
            prior_yoy_growth=snapshot.prior_yoy_growth,
            growth_acceleration=snapshot.growth_acceleration,
            production_value=snapshot.production_value,
            shipments_value=snapshot.shipments_value,
            production_shipment_gap=snapshot.production_shipment_gap,
            coverage=snapshot.coverage,
            confidence=snapshot.confidence,
            config_version=snapshot.config.version,
            config_snapshot=_config_dict(snapshot.config),
            unavailable_reasons=list(snapshot.unavailable_reasons),
        )
        self._session.add(row)
        self._session.flush()
        for role, regions in (
            ("REQUESTED", snapshot.requested_scope),
            ("CONTRIBUTING", snapshot.contributing_regions),
        ):
            for region_id, region_code in regions:
                self._session.add(
                    IndustryInventoryScopeModel(
                        snapshot_id=row.id,
                        region_id=region_id,
                        region_code=region_code,
                        scope_role=role,
                    )
                )
        for item in snapshot.input_references:
            self._session.add(
                IndustryInventoryInputModel(
                    snapshot_id=row.id,
                    aggregate_id=item.aggregate_id,
                    role=item.role,
                    observation_date=item.observation_date,
                    period_start=item.period_start,
                    period_end=item.period_end,
                    source_id=item.source_id,
                    available_at=item.available_at.replace(tzinfo=None),
                    contributor_revisions=[
                        list(ref) for ref in item.contributor_revisions
                    ],
                )
            )
        self._session.flush()
        self._session.refresh(row)
        return replace(snapshot, id=row.id)

    def get_by_id(self, snapshot_id: int) -> IndustryInventorySnapshot | None:
        row = self._session.get(IndustryInventorySnapshotModel, snapshot_id)
        if row is None:
            return None
        return _to_domain(row, self._inputs(row.id), self._scopes(row.id))

    def list_by_industry(
        self, industry_id: int, *, as_of: datetime | None = None
    ) -> list[IndustryInventorySnapshot]:
        query = select(IndustryInventorySnapshotModel).where(
            IndustryInventorySnapshotModel.industry_id == industry_id
        )
        if as_of is not None:
            if as_of.tzinfo is None or as_of.utcoffset() is None:
                raise DomainValidationError("as_of must be timezone-aware.")
            query = query.where(
                IndustryInventorySnapshotModel.as_of
                <= as_of.astimezone(UTC).replace(tzinfo=None)
            )
        rows = self._session.scalars(
            query.order_by(
                IndustryInventorySnapshotModel.as_of, IndustryInventorySnapshotModel.id
            )
        )
        return [
            _to_domain(row, self._inputs(row.id), self._scopes(row.id)) for row in rows
        ]

    def _scopes(
        self, snapshot_id: int
    ) -> tuple[tuple[tuple[int, str], ...], tuple[tuple[int, str], ...]]:
        rows = self._session.scalars(
            select(IndustryInventoryScopeModel)
            .where(IndustryInventoryScopeModel.snapshot_id == snapshot_id)
            .order_by(
                IndustryInventoryScopeModel.scope_role,
                IndustryInventoryScopeModel.region_code,
                IndustryInventoryScopeModel.region_id,
            )
        )
        scope_rows = tuple(
            (row.scope_role, row.region_id, row.region_code) for row in rows
        )
        requested = tuple(
            sorted(
                (region_id, code)
                for role, region_id, code in scope_rows
                if role == "REQUESTED"
            )
        )
        contributing = tuple(
            sorted(
                (region_id, code)
                for role, region_id, code in scope_rows
                if role == "CONTRIBUTING"
            )
        )
        return requested, contributing

    def _inputs(self, snapshot_id: int) -> tuple[IndustryInventoryInputReference, ...]:
        rows = self._session.scalars(
            select(IndustryInventoryInputModel)
            .where(IndustryInventoryInputModel.snapshot_id == snapshot_id)
            .order_by(IndustryInventoryInputModel.id)
        )
        return tuple(
            IndustryInventoryInputReference(
                aggregate_id=row.aggregate_id,
                role=row.role,
                observation_date=row.observation_date,
                period_start=row.period_start,
                period_end=row.period_end,
                source_id=row.source_id,
                available_at=_utc(row.available_at),
                contributor_revisions=tuple(
                    (int(ref[0]), int(ref[1]), int(ref[2]))
                    for ref in row.contributor_revisions
                ),
            )
            for row in rows
        )
