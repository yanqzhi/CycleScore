"""Application and domain validation for company industry exposures."""

from datetime import date
from decimal import Decimal

import pytest

from cyclescope.application.use_cases.exposure_validation import (
    ExposureAggregateValidationError,
    validate_company_exposures,
)
from cyclescope.domain.entities import CompanyIndustryExposure
from cyclescope.domain.exceptions import DomainValidationError


def exposure(
    sub_industry_id: int,
    share: str,
    start: date | None = None,
    end: date | None = None,
) -> CompanyIndustryExposure:
    """Build an exposure for a single example company."""
    return CompanyIndustryExposure(
        company_id=1,
        sub_industry_id=sub_industry_id,
        revenue_share=Decimal(share),
        valid_from=start,
        valid_to=end,
    )


def test_exposure_domain_validates_individual_share() -> None:
    with pytest.raises(DomainValidationError):
        exposure(1, "1.01")
    with pytest.raises(DomainValidationError):
        CompanyIndustryExposure(1, 1, 0.5)  # type: ignore[arg-type]


def test_overlapping_exposures_must_sum_to_at_most_one() -> None:
    first = exposure(1, "0.6", date(2024, 1, 1), date(2024, 12, 31))
    overlapping = exposure(2, "0.5", date(2024, 6, 1), date(2025, 3, 31))
    with pytest.raises(ExposureAggregateValidationError):
        validate_company_exposures([first, overlapping])


def test_non_overlapping_exposures_may_each_total_one() -> None:
    first = exposure(1, "1", date(2023, 1, 1), date(2023, 12, 31))
    second = exposure(2, "1", date(2024, 1, 1), None)
    validate_company_exposures([first, second])


def test_exposure_aggregate_accepts_multiple_industries_and_open_start() -> None:
    validate_company_exposures(
        [
            exposure(1, "0.4", None, date(2024, 5, 31)),
            exposure(2, "0.6", None, None),
        ]
    )
    with pytest.raises(ExposureAggregateValidationError):
        validate_company_exposures([exposure(1, "0.6"), exposure(2, "0.5")])


def test_exposure_aggregate_requires_one_company() -> None:
    first = exposure(1, "0.5")
    second = CompanyIndustryExposure(2, 2, Decimal("0.5"))
    with pytest.raises(ExposureAggregateValidationError):
        validate_company_exposures([first, second])
