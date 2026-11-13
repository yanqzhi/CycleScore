"""Application-level consistency checks for company exposure aggregates."""

from collections.abc import Sequence
from datetime import date
from decimal import Decimal

from cyclescope.domain.entities import CompanyIndustryExposure


class ExposureAggregateValidationError(ValueError):
    """Raised when a company's exposure aggregate is inconsistent."""


def validate_company_exposures(
    exposures: Sequence[CompanyIndustryExposure],
) -> None:
    """Require one company's time-overlapping revenue shares to total at most 1.

    Shares are summed across all sub-industries on every interval where records
    overlap. Since values change only at interval start dates, checking each
    distinct start point is sufficient, including ``date.min`` for open starts.
    Callers must supply the company's complete persisted exposure set together
    with any proposed create or update so existing overlaps are included.
    """
    if not exposures:
        return
    company_ids = {exposure.company_id for exposure in exposures}
    if len(company_ids) != 1:
        raise ExposureAggregateValidationError(
            "An exposure aggregate must contain records for exactly one company."
        )

    candidates = {exposure.valid_from or date.min for exposure in exposures}
    for point in candidates:
        active_share = sum(
            (
                exposure.revenue_share
                for exposure in exposures
                if (exposure.valid_from is None or exposure.valid_from <= point)
                and (exposure.valid_to is None or point <= exposure.valid_to)
            ),
            start=Decimal("0"),
        )
        if active_share > Decimal("1"):
            raise ExposureAggregateValidationError(
                f"Revenue exposure shares exceed 1 on {point.isoformat()}."
            )
