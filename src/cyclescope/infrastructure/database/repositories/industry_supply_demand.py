"""SQLAlchemy adapter for append-only Industry Supply & Demand snapshots."""

from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from cyclescope.domain.entities.industry_inventory import (
    IndustryInventoryClassification,
    IndustryInventoryTrend,
)
from cyclescope.domain.entities.industry_supply_demand import (
    IndustrySupplyDemandConfig,
    IndustrySupplyDemandInputReference,
    IndustrySupplyDemandPhase,
    IndustrySupplyDemandSnapshot,
    IndustrySupplyDemandStatus,
)
from cyclescope.domain.exceptions import DomainValidationError
from cyclescope.domain.repositories.contracts import IndustrySupplyDemandRepository
from cyclescope.infrastructure.database.models.industry_supply_demand import (
    IndustrySupplyDemandInputModel,
    IndustrySupplyDemandScopeModel,
    IndustrySupplyDemandSnapshotModel,
)


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _config_dict(config: IndustrySupplyDemandConfig) -> dict[str, str | int]:
    return {
        "version": config.version,
        "minimum_coverage": str(config.minimum_coverage),
        "flow_gap_tolerance": str(config.flow_gap_tolerance),
        "strong_demand_growth": str(config.strong_demand_growth),
        "negative_demand_growth": str(config.negative_demand_growth),
        "inventory_accumulation_yoy": str(config.inventory_accumulation_yoy),
        "inventory_drawdown_yoy": str(config.inventory_drawdown_yoy),
        "minimum_evidence_coverage": str(config.minimum_evidence_coverage),
    }


def _config_from(value: dict[str, str | int]) -> IndustrySupplyDemandConfig:
    version = value["version"]
    if not isinstance(version, int):
        raise DomainValidationError("Stored supply-demand config version is invalid.")
    return IndustrySupplyDemandConfig(
        version=version,
        minimum_coverage=Decimal(str(value["minimum_coverage"])),
        flow_gap_tolerance=Decimal(str(value["flow_gap_tolerance"])),
        strong_demand_growth=Decimal(str(value["strong_demand_growth"])),
        negative_demand_growth=Decimal(str(value["negative_demand_growth"])),
        inventory_accumulation_yoy=Decimal(str(value["inventory_accumulation_yoy"])),
        inventory_drawdown_yoy=Decimal(str(value["inventory_drawdown_yoy"])),
        minimum_evidence_coverage=Decimal(str(value["minimum_evidence_coverage"])),
    )


def _to_domain(
    row: IndustrySupplyDemandSnapshotModel,
    inputs: tuple[IndustrySupplyDemandInputReference, ...],
    requested_scope: tuple[tuple[int, str], ...],
    contributing_regions: tuple[tuple[int, str], ...],
) -> IndustrySupplyDemandSnapshot:
    return IndustrySupplyDemandSnapshot(
        industry_id=row.industry_id,
        sub_industry_id=row.sub_industry_id,
        aggregate_region_id=row.aggregate_region_id,
        aggregate_region_code=row.aggregate_region_code,
        requested_scope=requested_scope,
        contributing_regions=contributing_regions,
        source_id=row.source_id,
        unit_code=row.unit_code,
        currency_code=row.currency_code,
        period_start=row.period_start,
        period_end=row.period_end,
        observation_date=row.observation_date,
        as_of=_utc(row.as_of),
        calculated_at=_utc(row.calculated_at),
        phase=IndustrySupplyDemandPhase(row.phase),
        status=IndustrySupplyDemandStatus(row.status),
        production_value=row.production_value,
        shipments_value=row.shipments_value,
        flow_gap=row.flow_gap,
        flow_gap_ratio=row.flow_gap_ratio,
        shipment_growth_yoy=row.shipment_growth_yoy,
        inventory_snapshot_id=row.inventory_snapshot_id,
        inventory_classification=(
            IndustryInventoryClassification(row.inventory_classification)
            if row.inventory_classification is not None
            else None
        ),
        inventory_trend=(
            IndustryInventoryTrend(row.inventory_trend)
            if row.inventory_trend is not None
            else None
        ),
        inventory_yoy_growth=row.inventory_yoy_growth,
        inventory_growth_acceleration=row.inventory_growth_acceleration,
        inventory_coverage=row.inventory_coverage,
        inventory_confidence=row.inventory_confidence,
        coverage=row.coverage,
        evidence_coverage=row.evidence_coverage,
        confidence=row.confidence,
        config=_config_from(row.config_snapshot),
        input_references=inputs,
        unavailable_reasons=tuple(row.unavailable_reasons),
        validation_warnings=tuple(row.validation_warnings),
        id=row.id,
    )


class SQLAlchemyIndustrySupplyDemandRepository(IndustrySupplyDemandRepository):
    """Map snapshot aggregates and audit children without owning transactions."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def create(
        self, snapshot: IndustrySupplyDemandSnapshot
    ) -> IndustrySupplyDemandSnapshot:
        row = IndustrySupplyDemandSnapshotModel(
            industry_id=snapshot.industry_id,
            sub_industry_id=snapshot.sub_industry_id,
            aggregate_region_id=snapshot.aggregate_region_id,
            aggregate_region_code=snapshot.aggregate_region_code,
            source_id=snapshot.source_id,
            unit_code=snapshot.unit_code,
            currency_code=snapshot.currency_code,
            period_start=snapshot.period_start,
            period_end=snapshot.period_end,
            observation_date=snapshot.observation_date,
            as_of=snapshot.as_of.replace(tzinfo=None),
            calculated_at=snapshot.calculated_at.replace(tzinfo=None),
            phase=snapshot.phase.value,
            status=snapshot.status.value,
            production_value=snapshot.production_value,
            shipments_value=snapshot.shipments_value,
            flow_gap=snapshot.flow_gap,
            flow_gap_ratio=snapshot.flow_gap_ratio,
            shipment_growth_yoy=snapshot.shipment_growth_yoy,
            inventory_snapshot_id=snapshot.inventory_snapshot_id,
            inventory_classification=(
                snapshot.inventory_classification.value
                if snapshot.inventory_classification is not None
                else None
            ),
            inventory_trend=(
                snapshot.inventory_trend.value
                if snapshot.inventory_trend is not None
                else None
            ),
            inventory_yoy_growth=snapshot.inventory_yoy_growth,
            inventory_growth_acceleration=snapshot.inventory_growth_acceleration,
            inventory_coverage=snapshot.inventory_coverage,
            inventory_confidence=snapshot.inventory_confidence,
            coverage=snapshot.coverage,
            evidence_coverage=snapshot.evidence_coverage,
            confidence=snapshot.confidence,
            config_version=snapshot.config.version,
            config_snapshot=_config_dict(snapshot.config),
            unavailable_reasons=list(snapshot.unavailable_reasons),
            validation_warnings=list(snapshot.validation_warnings),
        )
        self._session.add(row)
        self._session.flush()
        for role, regions in (
            ("REQUESTED", snapshot.requested_scope),
            ("CONTRIBUTING", snapshot.contributing_regions),
        ):
            for region_id, region_code in regions:
                self._session.add(
                    IndustrySupplyDemandScopeModel(
                        snapshot_id=row.id,
                        region_id=region_id,
                        region_code=region_code,
                        scope_role=role,
                    )
                )
        for item in snapshot.input_references:
            self._session.add(
                IndustrySupplyDemandInputModel(
                    snapshot_id=row.id,
                    aggregate_id=item.aggregate_id,
                    inventory_snapshot_id=item.inventory_snapshot_id,
                    role=item.role,
                    period_start=item.period_start,
                    period_end=item.period_end,
                    source_id=item.source_id,
                    unit_code=item.unit_code,
                    currency_code=item.currency_code,
                    available_at=item.available_at.replace(tzinfo=None),
                    contributing_regions=[
                        {"region_id": region_id, "region_code": region_code}
                        for region_id, region_code in item.contributing_regions
                    ],
                    coverage=item.coverage,
                    policy_code=item.policy_code,
                    policy_version=item.policy_version,
                    calculation_version=item.calculation_version,
                    classification_references=[
                        list(reference) for reference in item.classification_references
                    ],
                    contributor_revisions=[
                        list(reference) for reference in item.contributor_revisions
                    ],
                    included=item.included,
                    exclusion_reason=item.exclusion_reason,
                )
            )
        self._session.flush()
        self._session.refresh(row)
        return replace(snapshot, id=row.id)

    def get_by_id(self, snapshot_id: int) -> IndustrySupplyDemandSnapshot | None:
        row = self._session.get(IndustrySupplyDemandSnapshotModel, snapshot_id)
        if row is None:
            return None
        requested, contributing = self._scopes(row.id)
        return _to_domain(row, self._inputs(row.id), requested, contributing)

    def list_by_industry(
        self, industry_id: int, *, as_of: datetime | None = None
    ) -> list[IndustrySupplyDemandSnapshot]:
        query = select(IndustrySupplyDemandSnapshotModel).where(
            IndustrySupplyDemandSnapshotModel.industry_id == industry_id
        )
        if as_of is not None:
            if as_of.tzinfo is None or as_of.utcoffset() is None:
                raise DomainValidationError("as_of must be timezone-aware.")
            query = query.where(
                IndustrySupplyDemandSnapshotModel.as_of
                <= as_of.astimezone(UTC).replace(tzinfo=None)
            )
        rows = self._session.scalars(
            query.order_by(
                IndustrySupplyDemandSnapshotModel.as_of,
                IndustrySupplyDemandSnapshotModel.id,
            )
        )
        result: list[IndustrySupplyDemandSnapshot] = []
        for row in rows:
            requested, contributing = self._scopes(row.id)
            result.append(
                _to_domain(row, self._inputs(row.id), requested, contributing)
            )
        return result

    def _scopes(
        self, snapshot_id: int
    ) -> tuple[tuple[tuple[int, str], ...], tuple[tuple[int, str], ...]]:
        rows = self._session.scalars(
            select(IndustrySupplyDemandScopeModel)
            .where(IndustrySupplyDemandScopeModel.snapshot_id == snapshot_id)
            .order_by(
                IndustrySupplyDemandScopeModel.scope_role,
                IndustrySupplyDemandScopeModel.region_code,
                IndustrySupplyDemandScopeModel.region_id,
            )
        )
        requested: list[tuple[int, str]] = []
        contributing: list[tuple[int, str]] = []
        for item in rows:
            target = requested if item.scope_role == "REQUESTED" else contributing
            target.append((item.region_id, item.region_code))
        return tuple(requested), tuple(contributing)

    def _inputs(
        self, snapshot_id: int
    ) -> tuple[IndustrySupplyDemandInputReference, ...]:
        rows = self._session.scalars(
            select(IndustrySupplyDemandInputModel)
            .where(IndustrySupplyDemandInputModel.snapshot_id == snapshot_id)
            .order_by(
                IndustrySupplyDemandInputModel.role,
                IndustrySupplyDemandInputModel.period_end,
                IndustrySupplyDemandInputModel.aggregate_id,
                IndustrySupplyDemandInputModel.inventory_snapshot_id,
                IndustrySupplyDemandInputModel.id,
            )
        )
        return tuple(
            IndustrySupplyDemandInputReference(
                role=row.role,
                aggregate_id=row.aggregate_id,
                inventory_snapshot_id=row.inventory_snapshot_id,
                period_start=row.period_start,
                period_end=row.period_end,
                source_id=row.source_id,
                unit_code=row.unit_code,
                currency_code=row.currency_code,
                available_at=_utc(row.available_at),
                contributing_regions=tuple(
                    sorted(
                        (int(item["region_id"]), str(item["region_code"]))
                        for item in row.contributing_regions
                    )
                ),
                coverage=row.coverage,
                policy_code=row.policy_code,
                policy_version=row.policy_version,
                calculation_version=row.calculation_version,
                classification_references=tuple(
                    (ref[0], ref[1]) for ref in row.classification_references
                ),
                contributor_revisions=tuple(
                    (int(ref[0]), int(ref[1]), int(ref[2]))
                    for ref in row.contributor_revisions
                ),
                included=row.included,
                exclusion_reason=row.exclusion_reason,
            )
            for row in rows
        )
