"""Local exchange-calendar implementation with explicit weekend/holiday rules."""

from collections.abc import Mapping, Sequence
from datetime import date, timedelta

from cyclescope.domain.exceptions import DomainValidationError


class WeekdayTradingCalendar:
    """Deterministic calendar configured with exchange-specific holiday dates."""

    def __init__(self, holidays: Mapping[str, Sequence[date]]) -> None:
        self._holidays = {key: frozenset(values) for key, values in holidays.items()}

    def expected_sessions(
        self, calendar_id: str, start_date: date, end_date: date
    ) -> tuple[date, ...]:
        if start_date > end_date:
            raise DomainValidationError("Calendar start date must not follow end date.")
        if calendar_id not in self._holidays:
            raise DomainValidationError(f"Unknown trading calendar: {calendar_id}")
        holidays = self._holidays[calendar_id]
        current = start_date
        sessions: list[date] = []
        while current <= end_date:
            if current.weekday() < 5 and current not in holidays:
                sessions.append(current)
            current += timedelta(days=1)
        return tuple(sessions)
