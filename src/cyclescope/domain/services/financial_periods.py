"""Period-safe normalization of financial flows for valuation calculations."""

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from cyclescope.domain.value_objects.financial_data import FiscalPeriod


@dataclass(frozen=True, slots=True)
class IncomePeriodAmount:
    """One already source/revision-selected income statement amount."""

    value: Decimal
    fiscal_year: int
    fiscal_period: FiscalPeriod
    period_start: date
    period_end: date
    statement_id: int


@dataclass(frozen=True, slots=True)
class TrailingAmount:
    value: Decimal | None
    period_label: str | None
    period_start: date | None
    period_end: date | None
    statement_ids: tuple[int, ...]
    unavailable_reason: str | None = None


def select_trailing_twelve_months(
    observations: tuple[IncomePeriodAmount, ...], valuation_date: date
) -> TrailingAmount:
    """Select one FY/TTM amount or sum exactly four contiguous discrete quarters.

    Quarterly facts are only additive when their represented date ranges are
    contiguous, non-overlapping, and form four consecutive fiscal quarters.
    Cumulative H1/9M values and unknown duration combinations remain unavailable.
    """
    eligible = tuple(
        row
        for row in observations
        if row.period_end <= valuation_date and row.period_start <= row.period_end
    )
    direct = [
        row
        for row in eligible
        if row.fiscal_period in {FiscalPeriod.FY, FiscalPeriod.TTM}
        and 330 <= (row.period_end - row.period_start).days + 1 <= 400
    ]
    quarter_rows = [
        row
        for row in eligible
        if row.fiscal_period
        in {FiscalPeriod.Q1, FiscalPeriod.Q2, FiscalPeriod.Q3, FiscalPeriod.Q4}
    ]
    candidates: list[TrailingAmount] = [
        TrailingAmount(
            row.value,
            row.fiscal_period.value,
            row.period_start,
            row.period_end,
            (row.statement_id,),
        )
        for row in direct
    ]
    quarters = _latest_contiguous_quarters(quarter_rows)
    if quarters:
        candidates.append(
            TrailingAmount(
                sum((row.value for row in quarters), Decimal(0)),
                "TTM_DERIVED",
                quarters[0].period_start,
                quarters[-1].period_end,
                tuple(row.statement_id for row in quarters),
            )
        )
    if not candidates:
        return TrailingAmount(
            None,
            None,
            None,
            None,
            (),
            "No eligible FY, TTM, or four-quarter contiguous flow period.",
        )
    # The latest period end wins; a direct TTM is preferred over an FY or a
    # derived quarter sum when the source reports the same endpoint explicitly.
    priority = {"TTM": 3, "FY": 2, "TTM_DERIVED": 1}
    return max(
        candidates,
        key=lambda row: (
            row.period_end or date.min,
            priority.get(row.period_label or "", 0),
        ),
    )


def _latest_contiguous_quarters(
    rows: list[IncomePeriodAmount],
) -> tuple[IncomePeriodAmount, ...]:
    by_sequence: dict[int, IncomePeriodAmount] = {}
    quarter_number = {
        FiscalPeriod.Q1: 1,
        FiscalPeriod.Q2: 2,
        FiscalPeriod.Q3: 3,
        FiscalPeriod.Q4: 4,
    }
    for row in rows:
        sequence = row.fiscal_year * 4 + quarter_number[row.fiscal_period]
        current = by_sequence.get(sequence)
        if current is not None:
            # Distinct records with the same fiscal quarter label may represent
            # incompatible cumulative/discrete periods; do not guess which wins.
            return ()
        by_sequence[sequence] = row
    ordered = sorted(by_sequence.values(), key=lambda row: row.period_end)
    for end in range(len(ordered) - 1, 2, -1):
        quarters = tuple(ordered[end - 3 : end + 1])
        sequences = [
            row.fiscal_year * 4 + quarter_number[row.fiscal_period] for row in quarters
        ]
        if sequences != list(range(sequences[0], sequences[0] + 4)):
            continue
        if any(
            previous.period_end + timedelta(days=1) != current.period_start
            for previous, current in zip(quarters, quarters[1:], strict=False)
        ):
            continue
        total_days = (quarters[-1].period_end - quarters[0].period_start).days + 1
        if total_days < 330 or total_days > 400:
            continue
        return quarters
    return ()
