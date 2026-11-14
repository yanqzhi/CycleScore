"""SQLAlchemy repository for append-only normalized earnings results."""

from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from cyclescope.domain.entities.normalized_earnings import (
    DepreciationAmortizationSignConvention,
    EarningsConfidence,
    EarningsInputReference,
    EarningsMetric,
    EarningsResultStatus,
    NormalizationMethod,
    NormalizedEarningsResult,
)
from cyclescope.domain.entities.valuation import (
    ValuationInputReference,
    ValuationResultStatus,
)
from cyclescope.domain.repositories.contracts import NormalizedEarningsRepository
from cyclescope.domain.value_objects.financial_data import UnitDimension
from cyclescope.infrastructure.database.models.normalized_earnings import (
    NormalizedEarningsInputRefModel,
    NormalizedEarningsResultModel,
)


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _to_domain(row: NormalizedEarningsResultModel) -> NormalizedEarningsResult:
    earnings_refs = tuple(
        EarningsInputReference(
            statement_id=ref.financial_statement_id or 0,
            statement_item_id=ref.financial_statement_item_id or 0,
            source_id=ref.source_id,
            revision_number=ref.revision_number,
            fiscal_year=ref.fiscal_year or 0,
            fiscal_period=ref.fiscal_period or "",
            item_code=ref.item_code or "",
            period_start=ref.period_start or date.min,
            period_end=ref.period_end or date.min,
            available_at=_utc(ref.available_at),
            publication_date=ref.publication_date,
            publication_datetime=_utc(ref.publication_datetime)
            if ref.publication_datetime
            else None,
        )
        for ref in row.input_refs
        if ref.provenance_kind == "EARNINGS"
    )
    valuation_refs = tuple(
        ValuationInputReference(
            record_type=ref.record_type,
            record_id=ref.market_price_id or ref.financial_statement_item_id or 0,
            parent_record_id=ref.financial_statement_id,
            source_id=ref.source_id,
            revision_number=ref.revision_number,
            available_at=_utc(ref.available_at),
            observation_date=ref.observation_date,
            financial_item_code=ref.financial_item_code,
            financial_period=ref.financial_period,
            period_start=ref.period_start,
            period_end=ref.period_end,
            publication_date=ref.publication_date,
            publication_datetime=_utc(ref.publication_datetime)
            if ref.publication_datetime
            else None,
        )
        for ref in row.input_refs
        if ref.provenance_kind == "VALUATION"
    )
    return NormalizedEarningsResult(
        id=row.id,
        company_id=row.company_id,
        security_id=row.security_id,
        metric=EarningsMetric(row.metric),
        method=NormalizationMethod(row.method),
        currency=row.currency,
        unit=UnitDimension(row.unit),
        requested_window_years=row.window_years,
        effective_window_years=row.effective_window_years,
        window_start_fiscal_year=row.window_start_fiscal_year,
        window_end_fiscal_year=row.window_end_fiscal_year,
        as_of=_utc(row.as_of),
        status=EarningsResultStatus(row.status),
        status_reason=row.status_reason,
        normalized_value=row.normalized_value,
        arithmetic_mean=row.arithmetic_mean,
        median=row.median,
        minimum=row.minimum,
        maximum=row.maximum,
        standard_deviation=row.standard_deviation,
        valid_fiscal_years=row.valid_fiscal_years,
        loss_making_years=row.loss_making_years,
        data_coverage=row.data_coverage,
        confidence=EarningsConfidence(row.confidence),
        calculation_period_start=row.calculation_period_start,
        calculation_period_end=row.calculation_period_end,
        fiscal_year_values=tuple(
            (int(value["year"]), Decimal(str(value["value"])))
            for value in row.fiscal_year_values
        ),
        input_references=earnings_refs,
        peak_candidate_year=row.peak_candidate_year,
        trough_candidate_year=row.trough_candidate_year,
        assumptions=tuple(row.assumptions),
        calculation_version=row.calculation_version,
        da_sign_convention=DepreciationAmortizationSignConvention(
            row.da_sign_convention
        ),
        normalized_valuation_status=ValuationResultStatus(
            row.normalized_valuation_status
        )
        if row.normalized_valuation_status
        else None,
        normalized_valuation_reason=row.normalized_valuation_reason,
        normalized_valuation_value=row.normalized_valuation_value,
        valuation_input_references=valuation_refs,
        created_at=_utc(row.created_at),
    )


class SQLAlchemyNormalizedEarningsRepository(NormalizedEarningsRepository):
    """Persist immutable normalized results with FK-backed input references."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def create(self, result: NormalizedEarningsResult) -> NormalizedEarningsResult:
        row = NormalizedEarningsResultModel(
            company_id=result.company_id,
            security_id=result.security_id,
            metric=result.metric.value,
            method=result.method.value,
            currency=result.currency,
            unit=result.unit.value,
            window_years=result.requested_window_years,
            effective_window_years=result.effective_window_years,
            window_start_fiscal_year=result.window_start_fiscal_year,
            window_end_fiscal_year=result.window_end_fiscal_year,
            as_of=result.as_of,
            status=result.status.value,
            status_reason=result.status_reason,
            normalized_value=result.normalized_value,
            arithmetic_mean=result.arithmetic_mean,
            median=result.median,
            minimum=result.minimum,
            maximum=result.maximum,
            standard_deviation=result.standard_deviation,
            valid_fiscal_years=result.valid_fiscal_years,
            loss_making_years=result.loss_making_years,
            data_coverage=result.data_coverage,
            confidence=result.confidence.value,
            calculation_period_start=result.calculation_period_start,
            calculation_period_end=result.calculation_period_end,
            fiscal_year_values=[
                {"year": year, "value": str(value)}
                for year, value in result.fiscal_year_values
            ],
            peak_candidate_year=result.peak_candidate_year,
            trough_candidate_year=result.trough_candidate_year,
            assumptions=list(result.assumptions),
            calculation_version=result.calculation_version,
            da_sign_convention=result.da_sign_convention.value,
            normalized_valuation_status=result.normalized_valuation_status.value
            if result.normalized_valuation_status
            else None,
            normalized_valuation_reason=result.normalized_valuation_reason,
            normalized_valuation_value=result.normalized_valuation_value,
        )
        row.input_refs = [
            NormalizedEarningsInputRefModel(
                provenance_kind="EARNINGS",
                record_type="FINANCIAL_LINE",
                financial_statement_id=ref.statement_id,
                financial_statement_item_id=ref.statement_item_id,
                source_id=ref.source_id,
                revision_number=ref.revision_number,
                available_at=ref.available_at,
                fiscal_year=ref.fiscal_year,
                fiscal_period=ref.fiscal_period,
                item_code=ref.item_code,
                period_start=ref.period_start or date.min,
                period_end=ref.period_end or datetime.min.date(),
                publication_date=ref.publication_date,
                publication_datetime=ref.publication_datetime,
            )
            for ref in result.input_references
        ] + [
            NormalizedEarningsInputRefModel(
                provenance_kind="VALUATION",
                record_type=ref.record_type,
                market_price_id=ref.record_id
                if ref.record_type == "DAILY_PRICE"
                else None,
                financial_statement_id=ref.parent_record_id,
                financial_statement_item_id=ref.record_id
                if ref.record_type == "FINANCIAL_LINE"
                else None,
                source_id=ref.source_id,
                revision_number=ref.revision_number,
                available_at=ref.available_at,
                observation_date=ref.observation_date,
                financial_item_code=ref.financial_item_code,
                financial_period=ref.financial_period,
                period_start=ref.period_start,
                period_end=ref.period_end,
                publication_date=ref.publication_date,
                publication_datetime=ref.publication_datetime,
            )
            for ref in result.valuation_input_references
        ]
        self.session.add(row)
        self.session.flush()
        return _to_domain(row)

    def get_by_id(self, result_id: int) -> NormalizedEarningsResult | None:
        row = self.session.get(NormalizedEarningsResultModel, result_id)
        return _to_domain(row) if row else None

    def list_by_company(
        self,
        company_id: int,
        *,
        metric: EarningsMetric | None = None,
        as_of: datetime | None = None,
        start_date: date | None = None,
    ) -> list[NormalizedEarningsResult]:
        query = select(NormalizedEarningsResultModel).where(
            NormalizedEarningsResultModel.company_id == company_id
        )
        if metric is not None:
            query = query.where(NormalizedEarningsResultModel.metric == metric.value)
        if start_date is not None:
            query = query.where(
                NormalizedEarningsResultModel.as_of
                >= datetime.combine(start_date, datetime.min.time(), UTC)
            )
        if as_of is not None:
            if as_of.tzinfo is None or as_of.utcoffset() is None:
                from cyclescope.domain.exceptions import DomainValidationError

                raise DomainValidationError("as_of must be timezone-aware.")
            query = query.where(
                NormalizedEarningsResultModel.as_of <= as_of.astimezone(UTC)
            )
        rows = self.session.scalars(
            query.order_by(
                NormalizedEarningsResultModel.as_of,
                NormalizedEarningsResultModel.id,
            )
        )
        return [_to_domain(row) for row in rows]
