"""Provider-independent industry signal observations and controlled vocabularies."""

from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import StrEnum

from cyclescope.domain.exceptions import DomainValidationError


class IndustrySignalType(StrEnum):
    INVENTORY = "INVENTORY"
    PRODUCTION = "PRODUCTION"
    SHIPMENTS = "SHIPMENTS"
    SALES = "SALES"
    ORDERS = "ORDERS"
    CAPACITY = "CAPACITY"
    CAPACITY_UTILIZATION = "CAPACITY_UTILIZATION"
    CAPACITY_ADDITION = "CAPACITY_ADDITION"
    CAPACITY_CLOSURE_ANNOUNCED = "CAPACITY_CLOSURE_ANNOUNCED"
    CAPACITY_CLOSURE_COMPLETED = "CAPACITY_CLOSURE_COMPLETED"


class IndustrySignalTemporalKind(StrEnum):
    POINT = "POINT"
    PERIOD = "PERIOD"
    EVENT = "EVENT"


class IndustrySignalUnit(StrEnum):
    TONNE = "TONNE"
    THOUSAND_TONNE = "THOUSAND_TONNE"
    UNIT = "UNIT"
    THOUSAND_UNITS = "THOUSAND_UNITS"
    CURRENCY = "CURRENCY"
    PERCENTAGE = "PERCENTAGE"
    INDEX = "INDEX"


_TEMPORAL_KIND: dict[IndustrySignalType, IndustrySignalTemporalKind] = {
    IndustrySignalType.INVENTORY: IndustrySignalTemporalKind.POINT,
    IndustrySignalType.PRODUCTION: IndustrySignalTemporalKind.PERIOD,
    IndustrySignalType.SHIPMENTS: IndustrySignalTemporalKind.PERIOD,
    IndustrySignalType.SALES: IndustrySignalTemporalKind.PERIOD,
    IndustrySignalType.ORDERS: IndustrySignalTemporalKind.PERIOD,
    IndustrySignalType.CAPACITY: IndustrySignalTemporalKind.POINT,
    IndustrySignalType.CAPACITY_UTILIZATION: IndustrySignalTemporalKind.POINT,
    IndustrySignalType.CAPACITY_ADDITION: IndustrySignalTemporalKind.EVENT,
    IndustrySignalType.CAPACITY_CLOSURE_ANNOUNCED: IndustrySignalTemporalKind.EVENT,
    IndustrySignalType.CAPACITY_CLOSURE_COMPLETED: IndustrySignalTemporalKind.EVENT,
}
_PHYSICAL_UNITS = frozenset(
    {
        IndustrySignalUnit.TONNE,
        IndustrySignalUnit.THOUSAND_TONNE,
        IndustrySignalUnit.UNIT,
        IndustrySignalUnit.THOUSAND_UNITS,
    }
)
_ALLOWED_UNITS: dict[IndustrySignalType, frozenset[IndustrySignalUnit]] = {
    IndustrySignalType.INVENTORY: _PHYSICAL_UNITS
    | {IndustrySignalUnit.CURRENCY, IndustrySignalUnit.INDEX},
    IndustrySignalType.PRODUCTION: _PHYSICAL_UNITS,
    IndustrySignalType.SHIPMENTS: _PHYSICAL_UNITS,
    IndustrySignalType.SALES: _PHYSICAL_UNITS
    | {IndustrySignalUnit.CURRENCY, IndustrySignalUnit.INDEX},
    IndustrySignalType.ORDERS: _PHYSICAL_UNITS
    | {IndustrySignalUnit.CURRENCY, IndustrySignalUnit.INDEX},
    IndustrySignalType.CAPACITY: _PHYSICAL_UNITS,
    IndustrySignalType.CAPACITY_UTILIZATION: frozenset({IndustrySignalUnit.PERCENTAGE}),
    IndustrySignalType.CAPACITY_ADDITION: _PHYSICAL_UNITS,
    IndustrySignalType.CAPACITY_CLOSURE_ANNOUNCED: _PHYSICAL_UNITS,
    IndustrySignalType.CAPACITY_CLOSURE_COMPLETED: _PHYSICAL_UNITS,
}
_PRECISION = 12
_INTEGER_DIGITS = 26


def temporal_kind_for(
    signal_type: IndustrySignalType,
) -> IndustrySignalTemporalKind:
    """Return the time shape defined for a signal category."""
    try:
        return _TEMPORAL_KIND[signal_type]
    except KeyError as exc:
        raise DomainValidationError("signal_type is invalid.") from exc


def _utc(name: str, value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise DomainValidationError(f"{name} must be timezone-aware.")
    return value.astimezone(UTC)


def _validate_value_precision(value: Decimal) -> None:
    parts = value.as_tuple()
    if not isinstance(parts.exponent, int):
        raise DomainValidationError("value must be finite.")
    integer_digits = max(len(parts.digits) + parts.exponent, 0)
    fractional_digits = max(-parts.exponent, 0)
    if integer_digits > _INTEGER_DIGITS or fractional_digits > _PRECISION:
        raise DomainValidationError("value exceeds NUMERIC(38, 12) precision.")


@dataclass(frozen=True, slots=True)
class IndustrySignalObservation:
    industry_id: int
    source_id: int
    signal_type: IndustrySignalType
    region_code: str
    unit_code: IndustrySignalUnit
    value: Decimal | None
    publication_date: date
    publication_datetime: datetime | None
    available_at: datetime
    collected_at: datetime
    revision_number: int
    sub_industry_id: int | None = None
    currency_code: str | None = None
    observation_date: date | None = None
    period_start: date | None = None
    period_end: date | None = None
    source_reference: str | None = None
    missing_reason: str | None = None
    temporal_kind: IndustrySignalTemporalKind = field(init=False)
    id: int | None = None
    created_at: datetime | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.signal_type, IndustrySignalType):
            raise DomainValidationError("signal_type is invalid.")
        if self.industry_id < 1 or self.source_id < 1 or self.revision_number < 1:
            raise DomainValidationError(
                "industry, source, and revision identifiers must be positive."
            )
        if self.sub_industry_id is not None and self.sub_industry_id < 1:
            raise DomainValidationError("sub_industry_id must be positive.")
        if (
            not self.region_code
            or len(self.region_code) > 64
            or self.region_code != self.region_code.strip()
        ):
            raise DomainValidationError("region_code is required and normalized.")
        if (
            not self.region_code.isascii()
            or not (self.region_code[0].isupper() or self.region_code[0].isdigit())
            or not all(
                char.isupper() or char.isdigit() or char in "_.:-"
                for char in self.region_code
            )
        ):
            raise DomainValidationError("region_code must be an uppercase scope code.")
        expected_kind = temporal_kind_for(self.signal_type)
        object.__setattr__(self, "temporal_kind", expected_kind)
        self._validate_temporal_fields(expected_kind)
        self._validate_unit()
        if self.value is None:
            if (
                self.missing_reason is None
                or not self.missing_reason.strip()
                or len(self.missing_reason) > 500
            ):
                raise DomainValidationError(
                    "missing_reason is required and limited to 500 characters "
                    "when value is unavailable."
                )
        else:
            if not isinstance(self.value, Decimal) or not self.value.is_finite():
                raise DomainValidationError("value must be a finite Decimal.")
            _validate_value_precision(self.value)
            if self.missing_reason is not None:
                raise DomainValidationError(
                    "missing_reason must be absent when value is present."
                )
            if (
                self.signal_type is IndustrySignalType.CAPACITY_UTILIZATION
                and not Decimal(0) <= self.value <= Decimal(100)
            ):
                raise DomainValidationError(
                    "capacity utilization percentage must be between 0 and 100."
                )
        for name, value in (
            ("available_at", self.available_at),
            ("collected_at", self.collected_at),
        ):
            object.__setattr__(self, name, _utc(name, value))
        if self.publication_datetime is not None:
            publication_datetime = _utc(
                "publication_datetime", self.publication_datetime
            )
            if self.available_at < publication_datetime:
                raise DomainValidationError(
                    "available_at must not precede publication_datetime."
                )
            object.__setattr__(self, "publication_datetime", publication_datetime)
        if self.created_at is not None:
            object.__setattr__(self, "created_at", _utc("created_at", self.created_at))
        if self.source_reference is not None and (
            not self.source_reference.strip() or len(self.source_reference) > 500
        ):
            raise DomainValidationError(
                "source_reference must be non-blank and at most 500 characters."
            )

    def _validate_temporal_fields(self, expected: IndustrySignalTemporalKind) -> None:
        if expected in {
            IndustrySignalTemporalKind.POINT,
            IndustrySignalTemporalKind.EVENT,
        }:
            if (
                self.observation_date is None
                or self.period_start is not None
                or self.period_end is not None
            ):
                raise DomainValidationError(
                    f"{expected.value} signals require observation_date only."
                )
        elif (
            self.observation_date is not None
            or self.period_start is None
            or self.period_end is None
            or self.period_start > self.period_end
        ):
            raise DomainValidationError(
                "PERIOD signals require an ordered period_start and period_end only."
            )

    def _validate_unit(self) -> None:
        if not isinstance(self.unit_code, IndustrySignalUnit):
            raise DomainValidationError("unit_code is invalid.")
        allowed = _ALLOWED_UNITS[self.signal_type]
        if self.unit_code not in allowed:
            raise DomainValidationError(
                f"unit {self.unit_code.value} is incompatible with "
                f"{self.signal_type.value}."
            )
        if self.unit_code is IndustrySignalUnit.CURRENCY:
            if self.currency_code is None:
                raise DomainValidationError("currency_code is required for CURRENCY.")
        elif self.currency_code is not None:
            raise DomainValidationError(
                "currency_code is only valid for CURRENCY unit."
            )
        if self.currency_code is not None and (
            len(self.currency_code) != 3
            or not self.currency_code.isascii()
            or not self.currency_code.isalpha()
            or not self.currency_code.isupper()
        ):
            raise DomainValidationError(
                "currency_code must be three uppercase letters."
            )

    @property
    def observation_key(self) -> tuple[object, ...]:
        """Natural key excluding source revision and mutable values."""
        return (
            self.industry_id,
            self.sub_industry_id,
            self.source_id,
            self.signal_type,
            self.region_code,
            self.temporal_kind,
            self.observation_date,
            self.period_start,
            self.period_end,
        )

    @property
    def revision_key(self) -> tuple[object, ...]:
        """Natural revision key used to reject duplicate source revisions."""
        return (*self.observation_key, self.revision_number)
