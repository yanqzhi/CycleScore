"""Time-bounded company revenue exposure domain entity."""

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

from cyclescope.domain.exceptions import DomainValidationError


@dataclass(frozen=True, slots=True)
class CompanyIndustryExposure:
    """A company's revenue share attributed to a sub-industry over a date range."""

    company_id: int
    sub_industry_id: int
    revenue_share: Decimal
    id: int | None = None
    valid_from: date | None = None
    valid_to: date | None = None
    source_id: int | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    def __post_init__(self) -> None:
        if self.company_id < 1 or self.sub_industry_id < 1:
            raise DomainValidationError(
                "Exposure company and sub-industry IDs must be positive."
            )
        if not isinstance(self.revenue_share, Decimal):
            raise DomainValidationError("revenue_share must be a Decimal.")
        if not self.revenue_share.is_finite() or not Decimal(
            "0"
        ) <= self.revenue_share <= Decimal("1"):
            raise DomainValidationError(
                "revenue_share must be a finite Decimal in [0, 1]."
            )
        if self.valid_from and self.valid_to and self.valid_to < self.valid_from:
            raise DomainValidationError("valid_to must not be before valid_from.")
