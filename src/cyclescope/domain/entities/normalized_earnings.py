"""Immutable normalized earnings results and source provenance."""

from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import ROUND_HALF_EVEN, Decimal, localcontext
from enum import StrEnum

from cyclescope.domain.entities.valuation import (
    ValuationInputReference,
    ValuationResultStatus,
)
from cyclescope.domain.exceptions import DomainValidationError
from cyclescope.domain.value_objects.financial_data import UnitDimension


class EarningsMetric(StrEnum):
    OPERATING_PROFIT = "OPERATING_PROFIT"
    NET_INCOME = "NET_INCOME"
    EPS = "EPS"
    EBITDA = "EBITDA"


class NormalizationMethod(StrEnum):
    ARITHMETIC_MEAN = "ARITHMETIC_MEAN"
    MEDIAN = "MEDIAN"


class EarningsResultStatus(StrEnum):
    AVAILABLE = "AVAILABLE"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"
    UNAVAILABLE = "UNAVAILABLE"


class EarningsConfidence(StrEnum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    INSUFFICIENT = "INSUFFICIENT"


class DepreciationAmortizationSignConvention(StrEnum):
    """How a source encodes D&A expense on its income statement."""

    UNKNOWN = "UNKNOWN"
    POSITIVE_EXPENSE = "POSITIVE_EXPENSE"
    NEGATIVE_EXPENSE = "NEGATIVE_EXPENSE"


def derive_ebitda(
    operating_profit: Decimal,
    depreciation_amortization: Decimal,
    convention: DepreciationAmortizationSignConvention,
) -> Decimal:
    """Add back D&A only under a declared and internally consistent sign rule."""
    if convention == DepreciationAmortizationSignConvention.UNKNOWN:
        raise DomainValidationError(
            "D&A sign convention is unknown; EBITDA cannot be derived safely."
        )
    if convention == DepreciationAmortizationSignConvention.POSITIVE_EXPENSE:
        if depreciation_amortization < 0:
            raise DomainValidationError(
                "D&A is negative but the source convention declares positive expenses."
            )
        return operating_profit + depreciation_amortization
    if convention == DepreciationAmortizationSignConvention.NEGATIVE_EXPENSE:
        if depreciation_amortization > 0:
            raise DomainValidationError(
                "D&A is positive but the source convention declares negative expenses."
            )
        return operating_profit - depreciation_amortization
    raise DomainValidationError("Unsupported D&A sign convention.")


@dataclass(frozen=True, slots=True)
class EarningsInputReference:
    """Reference to one visible financial statement line used in analysis."""

    statement_id: int
    statement_item_id: int
    source_id: int
    revision_number: int
    fiscal_year: int
    fiscal_period: str
    item_code: str
    period_start: date
    period_end: date
    available_at: datetime
    publication_date: date | None = None
    publication_datetime: datetime | None = None

    def __post_init__(self) -> None:
        if (
            min(
                self.statement_id,
                self.statement_item_id,
                self.source_id,
                self.revision_number,
                self.fiscal_year,
            )
            < 1
        ):
            raise DomainValidationError(
                "Earnings input reference IDs must be positive."
            )
        if not self.item_code.strip():
            raise DomainValidationError("Earnings input item code is required.")
        if self.available_at.tzinfo is None or self.available_at.utcoffset() is None:
            raise DomainValidationError("Earnings input available_at must be aware.")
        object.__setattr__(self, "available_at", self.available_at.astimezone(UTC))
        if self.period_start > self.period_end:
            raise DomainValidationError("Earnings reference period is invalid.")
        if self.publication_datetime is not None:
            if (
                self.publication_datetime.tzinfo is None
                or self.publication_datetime.utcoffset() is None
            ):
                raise DomainValidationError(
                    "Earnings publication_datetime must be aware."
                )
            publication = self.publication_datetime.astimezone(UTC)
            if publication > self.available_at:
                raise DomainValidationError(
                    "Earnings availability cannot precede publication."
                )
            object.__setattr__(self, "publication_datetime", publication)


@dataclass(frozen=True, slots=True)
class FiscalEarningsObservation:
    fiscal_year: int
    value: Decimal
    references: tuple[EarningsInputReference, ...]
    period_start: date
    period_end: date

    def __post_init__(self) -> None:
        if self.fiscal_year < 1 or self.period_start > self.period_end:
            raise DomainValidationError("Fiscal earnings period is invalid.")
        if not self.value.is_finite():
            raise DomainValidationError("Fiscal earnings must be finite.")
        exponent = self.value.as_tuple().exponent
        if not isinstance(exponent, int):
            raise DomainValidationError("Fiscal earnings must be finite.")
        integer_digits = max(len(self.value.as_tuple().digits) + exponent, 0)
        if integer_digits > 26 or max(-exponent, 0) > 12:
            raise DomainValidationError(
                "Fiscal earnings exceed NUMERIC(38, 12) precision."
            )
        if not self.references:
            raise DomainValidationError("Fiscal earnings require source references.")


@dataclass(frozen=True, slots=True)
class NormalizedEarningsResult:
    company_id: int
    security_id: int | None
    metric: EarningsMetric
    method: NormalizationMethod
    currency: str | None
    unit: UnitDimension
    requested_window_years: int
    effective_window_years: int
    window_start_fiscal_year: int | None
    window_end_fiscal_year: int | None
    as_of: datetime
    status: EarningsResultStatus
    status_reason: str | None
    normalized_value: Decimal | None
    arithmetic_mean: Decimal | None
    median: Decimal | None
    minimum: Decimal | None
    maximum: Decimal | None
    standard_deviation: Decimal | None
    valid_fiscal_years: int
    loss_making_years: int
    data_coverage: Decimal
    confidence: EarningsConfidence
    calculation_period_start: date | None
    calculation_period_end: date | None
    fiscal_year_values: tuple[tuple[int, Decimal], ...]
    input_references: tuple[EarningsInputReference, ...]
    peak_candidate_year: int | None
    trough_candidate_year: int | None
    assumptions: tuple[str, ...]
    da_sign_convention: DepreciationAmortizationSignConvention
    calculation_version: int = 1
    normalized_valuation_status: ValuationResultStatus | None = None
    normalized_valuation_reason: str | None = None
    normalized_valuation_value: Decimal | None = None
    valuation_input_references: tuple[ValuationInputReference, ...] = ()
    created_at: datetime | None = None
    id: int | None = None

    def __post_init__(self) -> None:
        if self.company_id < 1 or (
            self.security_id is not None and self.security_id < 1
        ):
            raise DomainValidationError("Normalized earnings identity is invalid.")
        if self.requested_window_years not in {5, 7, 10}:
            raise DomainValidationError("Historical window must be 5, 7, or 10 years.")
        if not 1 <= self.effective_window_years <= self.requested_window_years:
            raise DomainValidationError("Effective historical window is invalid.")
        if self.calculation_version < 1 or self.valid_fiscal_years < 0:
            raise DomainValidationError("Calculation version/year count is invalid.")
        expected_unit = (
            UnitDimension.PER_SHARE
            if self.metric == EarningsMetric.EPS
            else UnitDimension.CURRENCY_AMOUNT
        )
        if self.unit != expected_unit:
            raise DomainValidationError(
                "Normalized earnings unit conflicts with metric."
            )
        if self.currency is not None and (
            len(self.currency) != 3
            or not self.currency.isalpha()
            or not self.currency.isupper()
        ):
            raise DomainValidationError("Currency must be a three-letter code.")
        if (self.window_start_fiscal_year is None) != (
            self.window_end_fiscal_year is None
        ):
            raise DomainValidationError("Fiscal-year window boundaries are incomplete.")
        if (
            self.window_start_fiscal_year is not None
            and self.window_end_fiscal_year is not None
            and self.window_start_fiscal_year > self.window_end_fiscal_year
        ):
            raise DomainValidationError("Fiscal-year window boundaries are invalid.")
        if self.as_of.tzinfo is None or self.as_of.utcoffset() is None:
            raise DomainValidationError("as_of must be timezone-aware.")
        object.__setattr__(self, "as_of", self.as_of.astimezone(UTC))
        if not self.data_coverage.is_finite() or not 0 <= self.data_coverage <= 1:
            raise DomainValidationError("Data coverage must be between zero and one.")
        if (self.status == EarningsResultStatus.AVAILABLE) != (
            self.normalized_value is not None
        ):
            raise DomainValidationError("Normalized earnings status/value conflict.")
        if self.status != EarningsResultStatus.AVAILABLE and not self.status_reason:
            raise DomainValidationError(
                "Unavailable normalized earnings must include a reason."
            )
        for value in (
            self.normalized_value,
            self.arithmetic_mean,
            self.median,
            self.minimum,
            self.maximum,
            self.standard_deviation,
            self.normalized_valuation_value,
        ):
            if value is not None and not value.is_finite():
                raise DomainValidationError(
                    "Normalized earnings values must be finite."
                )


def analyze_historical_earnings(
    *,
    company_id: int,
    security_id: int | None,
    metric: EarningsMetric,
    observations: tuple[FiscalEarningsObservation, ...],
    window_years: int,
    method: NormalizationMethod,
    as_of: datetime,
    window_start_fiscal_year: int | None,
    window_end_fiscal_year: int | None,
    effective_window_years: int,
    currency: str | None = None,
    da_sign_convention: DepreciationAmortizationSignConvention = (
        DepreciationAmortizationSignConvention.UNKNOWN
    ),
    calculation_version: int = 1,
) -> NormalizedEarningsResult:
    """Analyze annual fiscal observations visible at one PIT cutoff.

    Missing fiscal labels remain in the denominator. Short history uses the
    fiscal-year span available; gaps within that span lower coverage.
    """
    if window_years not in {5, 7, 10}:
        raise DomainValidationError("Historical window must be 5, 7, or 10 years.")
    if as_of.tzinfo is None or as_of.utcoffset() is None:
        raise DomainValidationError("as_of must be timezone-aware.")
    cutoff = as_of.astimezone(UTC)
    eligible = tuple(
        row
        for row in observations
        if all(ref.available_at <= cutoff for ref in row.references)
        and row.period_end <= cutoff.date()
    )
    if not 1 <= effective_window_years <= window_years:
        raise DomainValidationError("Effective historical window is invalid.")
    if (window_start_fiscal_year is None) != (window_end_fiscal_year is None):
        raise DomainValidationError("Fiscal-year window boundaries are incomplete.")
    if window_start_fiscal_year is None:
        if effective_window_years != window_years:
            raise DomainValidationError(
                "A shortened historical window requires fiscal-year boundaries."
            )
        start_year = None
        end_year = None
    else:
        assert window_end_fiscal_year is not None
        if window_start_fiscal_year > window_end_fiscal_year:
            raise DomainValidationError("Fiscal-year window boundaries are invalid.")
        if (
            window_end_fiscal_year - window_start_fiscal_year + 1
            != effective_window_years
        ):
            raise DomainValidationError(
                "Fiscal-year boundaries do not match the window length."
            )
        start_year = window_start_fiscal_year
        end_year = window_end_fiscal_year
    selected = tuple(
        sorted(
            (
                row
                for row in eligible
                if start_year is not None
                and end_year is not None
                and start_year <= row.fiscal_year <= end_year
            ),
            key=lambda row: row.fiscal_year,
        )
    )
    # A period/source combination must not silently contribute twice in a year.
    years = [row.fiscal_year for row in selected]
    if len(years) != len(set(years)):
        raise DomainValidationError(
            "Multiple annual observations exist for one fiscal year."
        )
    values = [row.value for row in selected]
    count = len(values)
    effective = effective_window_years
    coverage = (
        (Decimal(count) / Decimal(effective)).quantize(
            Decimal("0.0000001"), rounding=ROUND_HALF_EVEN
        )
        if effective
        else Decimal(0)
    )
    mean = None
    mean_exact = None
    if count:
        with localcontext() as context:
            context.prec = 50
            mean_exact = sum(values, Decimal(0)) / count
            mean = _q(mean_exact)
    ordered = sorted(values)
    median = None
    if count:
        with localcontext() as context:
            context.prec = 50
            median = (
                ordered[count // 2]
                if count % 2
                else (ordered[count // 2 - 1] + ordered[count // 2]) / Decimal(2)
            )
    if median is not None:
        median = _q(median)
    minimum, maximum = (min(values), max(values)) if values else (None, None)
    deviation = None
    if count:
        assert mean_exact is not None
        with localcontext() as context:
            context.prec = 50
            deviation = _q(
                (
                    sum(((item - mean_exact) ** 2 for item in values), Decimal(0))
                    / count
                ).sqrt()
            )
    normalized = mean if method == NormalizationMethod.ARITHMETIC_MEAN else median
    status = (
        EarningsResultStatus.AVAILABLE
        if count >= 3 and normalized is not None
        else EarningsResultStatus.INSUFFICIENT_DATA
    )
    confidence = (
        EarningsConfidence.HIGH
        if count >= 5 and coverage >= Decimal("0.8")
        else EarningsConfidence.MEDIUM
        if count >= 3 and coverage >= Decimal("0.6")
        else EarningsConfidence.LOW
        if count >= 1
        else EarningsConfidence.INSUFFICIENT
    )
    peak = max(selected, key=lambda row: (row.value, row.fiscal_year), default=None)
    trough = min(selected, key=lambda row: (row.value, row.fiscal_year), default=None)
    refs = tuple(reference for row in selected for reference in row.references)
    return NormalizedEarningsResult(
        company_id=company_id,
        security_id=security_id,
        metric=metric,
        method=method,
        currency=currency,
        unit=(
            UnitDimension.PER_SHARE
            if metric == EarningsMetric.EPS
            else UnitDimension.CURRENCY_AMOUNT
        ),
        requested_window_years=window_years,
        effective_window_years=effective_window_years,
        window_start_fiscal_year=window_start_fiscal_year,
        window_end_fiscal_year=window_end_fiscal_year,
        as_of=cutoff,
        status=status,
        status_reason=(
            None
            if status == EarningsResultStatus.AVAILABLE
            else (
                f"Only {count} valid fiscal year(s) are available; "
                "at least 3 are required."
            )
        ),
        normalized_value=normalized
        if status == EarningsResultStatus.AVAILABLE
        else None,
        arithmetic_mean=mean,
        median=median,
        minimum=minimum,
        maximum=maximum,
        standard_deviation=deviation,
        valid_fiscal_years=count,
        loss_making_years=sum(value < 0 for value in values),
        data_coverage=coverage,
        confidence=confidence,
        calculation_period_start=min(
            (row.period_start for row in selected), default=None
        ),
        calculation_period_end=max((row.period_end for row in selected), default=None),
        fiscal_year_values=tuple((row.fiscal_year, row.value) for row in selected),
        input_references=refs,
        peak_candidate_year=peak.fiscal_year if peak else None,
        trough_candidate_year=trough.fiscal_year if trough else None,
        assumptions=(
            "Reported annual values are preserved; exceptional-item and "
            "discontinued-operation adjustments are not inferred without "
            "reliable data.",
            "Accounting-policy adjustments are not inferred without "
            "reliable adjustment data.",
            "Peak and trough years are historical earnings extrema, not definitive "
            "cycle-stage labels.",
        ),
        da_sign_convention=da_sign_convention,
        calculation_version=calculation_version,
    )


def _q(value: Decimal) -> Decimal:
    with localcontext() as context:
        context.prec = 50
        return value.quantize(Decimal("0.000000000001"), rounding=ROUND_HALF_EVEN)
