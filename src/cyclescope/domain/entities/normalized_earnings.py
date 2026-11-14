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
    requested_window_years: int
    effective_window_years: int
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
    latest_year = max((row.fiscal_year for row in eligible), default=None)
    earliest_year = min((row.fiscal_year for row in eligible), default=None)
    effective = (
        min(window_years, latest_year - earliest_year + 1)
        if latest_year is not None and earliest_year is not None
        else window_years
    )
    start_year = latest_year - effective + 1 if latest_year is not None else 1
    selected = tuple(
        sorted(
            (
                row
                for row in eligible
                if start_year <= row.fiscal_year <= (latest_year or 0)
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
    median = (
        (
            ordered[count // 2]
            if count % 2
            else (ordered[count // 2 - 1] + ordered[count // 2]) / Decimal(2)
        )
        if count
        else None
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
        requested_window_years=window_years,
        effective_window_years=effective,
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
        calculation_version=calculation_version,
    )


def _q(value: Decimal) -> Decimal:
    with localcontext() as context:
        context.prec = 50
        return value.quantize(Decimal("0.000000000001"), rounding=ROUND_HALF_EVEN)
