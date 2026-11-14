from datetime import date
from decimal import Decimal

from cyclescope.domain.services.financial_periods import (
    IncomePeriodAmount,
    select_trailing_twelve_months,
)
from cyclescope.domain.value_objects.financial_data import FiscalPeriod


def _quarter(year, period, start, end, value, statement_id):
    return IncomePeriodAmount(
        Decimal(value),
        year,
        period,
        date.fromisoformat(start),
        date.fromisoformat(end),
        statement_id,
    )


def test_four_contiguous_quarters_are_aggregated_to_ttm_once():
    rows = (
        _quarter(2024, FiscalPeriod.Q2, "2024-04-01", "2024-06-30", "10", 1),
        _quarter(2024, FiscalPeriod.Q3, "2024-07-01", "2024-09-30", "20", 2),
        _quarter(2024, FiscalPeriod.Q4, "2024-10-01", "2024-12-31", "30", 3),
        _quarter(2025, FiscalPeriod.Q1, "2025-01-01", "2025-03-31", "40", 4),
    )
    result = select_trailing_twelve_months(rows, date(2025, 5, 15))
    assert result.value == Decimal("100")
    assert result.period_label == "TTM_DERIVED"
    assert result.statement_ids == (1, 2, 3, 4)


def test_quarter_gaps_overlaps_and_future_periods_are_not_summed():
    gap = (
        _quarter(2024, FiscalPeriod.Q1, "2024-01-01", "2024-03-31", "10", 1),
        _quarter(2024, FiscalPeriod.Q2, "2024-04-01", "2024-06-30", "20", 2),
        _quarter(2024, FiscalPeriod.Q4, "2024-10-01", "2024-12-31", "30", 3),
        _quarter(2025, FiscalPeriod.Q1, "2025-01-01", "2025-03-31", "40", 4),
    )
    assert select_trailing_twelve_months(gap, date(2025, 5, 1)).value is None

    overlap = (
        _quarter(2024, FiscalPeriod.Q2, "2024-04-01", "2024-07-15", "10", 1),
        _quarter(2024, FiscalPeriod.Q3, "2024-07-01", "2024-09-30", "20", 2),
        _quarter(2024, FiscalPeriod.Q4, "2024-10-01", "2024-12-31", "30", 3),
        _quarter(2025, FiscalPeriod.Q1, "2025-01-01", "2025-03-31", "40", 4),
    )
    assert select_trailing_twelve_months(overlap, date(2025, 5, 1)).value is None


def test_fy_is_selected_as_one_annual_value_not_added_to_quarters():
    rows = (
        _quarter(2024, FiscalPeriod.Q1, "2024-01-01", "2024-03-31", "10", 1),
        _quarter(2024, FiscalPeriod.Q2, "2024-04-01", "2024-06-30", "20", 2),
        _quarter(2024, FiscalPeriod.Q3, "2024-07-01", "2024-09-30", "30", 3),
        _quarter(2024, FiscalPeriod.Q4, "2024-10-01", "2024-12-31", "40", 4),
        IncomePeriodAmount(
            Decimal("100"),
            2024,
            FiscalPeriod.FY,
            date(2024, 1, 1),
            date(2024, 12, 31),
            5,
        ),
    )
    result = select_trailing_twelve_months(rows, date(2025, 2, 1))
    assert result.value == Decimal("100")
    assert result.period_label == "FY"
    assert result.statement_ids == (5,)
