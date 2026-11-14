"""Import and point-in-time retrieval use cases for market data."""

from datetime import UTC, date, datetime

from cyclescope.application.dto.market_data import (
    FxImportSummary,
    GetHistoricalFxRatesInput,
    GetHistoricalPricesInput,
    ImportFxRatesInput,
    ImportHistoricalPricesInput,
    PriceImportSummary,
    ValidationIssue,
)
from cyclescope.application.dto.market_data_ingestion import (
    DailyPriceIngestionContext,
    FxRateIngestionContext,
)
from cyclescope.application.interfaces.market_data import (
    FxRateProvider,
    HistoricalPriceProvider,
)
from cyclescope.application.use_cases.market_data_validation import (
    daily_price_from_record,
    fx_rate_from_record,
)
from cyclescope.domain.entities import DailyPrice, FxRate
from cyclescope.domain.repositories.contracts import (
    DailyPriceRepository,
    FxRateRepository,
)
from cyclescope.domain.value_objects.market_data import CurrencyPair, MarketDataPeriod


def _validate_import_metadata(
    source_id: int, available_at: datetime, collected_at: datetime, revision_number: int
) -> tuple[datetime, datetime]:
    if source_id < 1 or revision_number < 1:
        raise ValueError("source_id and revision_number must be positive.")
    if available_at.tzinfo is None or available_at.utcoffset() is None:
        raise ValueError("available_at must be timezone-aware.")
    if collected_at.tzinfo is None or collected_at.utcoffset() is None:
        raise ValueError("collected_at must be timezone-aware.")
    return available_at.astimezone(UTC), collected_at.astimezone(UTC)


class ImportHistoricalPrices:
    """Validate, deduplicate, and save normalized provider price observations."""

    def __init__(
        self,
        provider: HistoricalPriceProvider,
        repository: DailyPriceRepository,
    ) -> None:
        self._provider = provider
        self._repository = repository

    def execute(self, request: ImportHistoricalPricesInput) -> PriceImportSummary:
        """Import rows and return accepted, duplicate, and rejected counts."""
        if request.request.security_id < 1:
            raise ValueError("security_id must be positive.")
        available_at, collected_at = _validate_import_metadata(
            request.source_id,
            request.available_at,
            request.collected_at,
            request.revision_number,
        )
        currency = request.request.currency.strip().upper()
        rows = self._provider.fetch_historical_prices(request.request)
        errors: list[ValidationIssue] = []
        accepted: list[DailyPrice] = []
        duplicate_count = 0
        for row in rows:
            try:
                context = DailyPriceIngestionContext(
                    security_id=request.request.security_id,
                    currency=currency,
                    source_id=request.source_id,
                    available_at=available_at,
                    collected_at=collected_at,
                    revision_number=request.revision_number,
                )
                price = daily_price_from_record(row, context)
                if self._repository.exists(
                    price.security_id,
                    price.observation_date,
                    price.source_id,
                    price.revision_number,
                ):
                    duplicate_count += 1
                elif self._repository.save(price):
                    accepted.append(price)
                else:
                    duplicate_count += 1
            except ValueError as error:
                errors.append(ValidationIssue(row.row_number, str(error)))
        return PriceImportSummary(
            total_records=len(rows),
            imported_records=len(accepted),
            skipped_duplicates=duplicate_count,
            rejected_records=len(errors),
            validation_errors=tuple(errors),
            imported_observations=tuple(accepted),
        )


class ImportFxRates:
    """Validate, deduplicate, and save normalized provider FX observations."""

    def __init__(self, provider: FxRateProvider, repository: FxRateRepository) -> None:
        self._provider = provider
        self._repository = repository

    def execute(self, request: ImportFxRatesInput) -> FxImportSummary:
        """Import FX rows and return explicit accepted, duplicate, and reject counts."""
        available_at, collected_at = _validate_import_metadata(
            request.source_id,
            request.available_at,
            request.collected_at,
            request.revision_number,
        )
        rows = self._provider.fetch_fx_rates(request.request)
        errors: list[ValidationIssue] = []
        accepted: list[FxRate] = []
        duplicate_count = 0
        for row in rows:
            try:
                if row.base_currency is None or row.quote_currency is None:
                    raise ValueError("base_currency and quote_currency are required.")
                pair = CurrencyPair(
                    row.base_currency.strip().upper(),
                    row.quote_currency.strip().upper(),
                )
                context = FxRateIngestionContext(
                    base_currency=pair.base_currency,
                    quote_currency=pair.quote_currency,
                    source_id=request.source_id,
                    available_at=available_at,
                    collected_at=collected_at,
                    revision_number=request.revision_number,
                )
                rate = fx_rate_from_record(row, context)
                if self._repository.exists(
                    pair,
                    rate.observation_date,
                    rate.source_id,
                    rate.revision_number,
                ):
                    duplicate_count += 1
                elif self._repository.save(rate):
                    accepted.append(rate)
                else:
                    duplicate_count += 1
            except ValueError as error:
                errors.append(ValidationIssue(row.row_number, str(error)))
        return FxImportSummary(
            total_records=len(rows),
            imported_records=len(accepted),
            skipped_duplicates=duplicate_count,
            rejected_records=len(errors),
            validation_errors=tuple(errors),
            imported_observations=tuple(accepted),
        )


class GetHistoricalPrices:
    """Retrieve latest available revisions without look-ahead observations."""

    def __init__(self, repository: DailyPriceRepository) -> None:
        self._repository = repository

    def execute(self, request: GetHistoricalPricesInput) -> list[DailyPrice]:
        """Return one deterministic source-selected observation per market date."""
        if request.as_of.tzinfo is None or request.as_of.utcoffset() is None:
            raise ValueError("as_of must be timezone-aware.")
        if request.security_id < 1:
            raise ValueError("security_id must be positive.")
        period = MarketDataPeriod(request.start_date, request.end_date)
        cutoff = request.as_of.astimezone(UTC)
        eligible = self._repository.get_by_security_and_period(
            request.security_id,
            period,
            cutoff,
            request.source_id,
        )
        selected: dict[date, DailyPrice] = {}
        for price in eligible:
            if (
                price.observation_date < period.start_date
                or price.observation_date > min(period.end_date, cutoff.date())
                or price.available_at > cutoff
                or (
                    request.source_id is not None
                    and price.source_id != request.source_id
                )
            ):
                continue
            current = selected.get(price.observation_date)
            if current is None or (
                price.available_at,
                price.revision_number,
                -price.source_id,
            ) > (
                current.available_at,
                current.revision_number,
                -current.source_id,
            ):
                selected[price.observation_date] = price
        return [selected[day] for day in sorted(selected)]


class GetHistoricalFxRates:
    """Retrieve latest available revisions for an FX pair."""

    def __init__(self, repository: FxRateRepository) -> None:
        self._repository = repository

    def execute(self, request: GetHistoricalFxRatesInput) -> list[FxRate]:
        """Return one deterministic source-selected rate per market date."""
        if request.as_of.tzinfo is None or request.as_of.utcoffset() is None:
            raise ValueError("as_of must be timezone-aware.")
        pair = CurrencyPair(
            request.base_currency.strip().upper(),
            request.quote_currency.strip().upper(),
        )
        period = MarketDataPeriod(request.start_date, request.end_date)
        cutoff = request.as_of.astimezone(UTC)
        eligible = self._repository.get_by_pair_and_period(
            pair, period, cutoff, request.source_id
        )
        selected: dict[date, FxRate] = {}
        for rate in eligible:
            if (
                rate.observation_date < period.start_date
                or rate.observation_date > min(period.end_date, cutoff.date())
                or rate.available_at > cutoff
                or rate.base_currency != pair.base_currency
                or rate.quote_currency != pair.quote_currency
                or (
                    request.source_id is not None
                    and rate.source_id != request.source_id
                )
            ):
                continue
            current = selected.get(rate.observation_date)
            if current is None or (
                rate.available_at,
                rate.revision_number,
                -rate.source_id,
            ) > (
                current.available_at,
                current.revision_number,
                -current.source_id,
            ):
                selected[rate.observation_date] = rate
        return [selected[day] for day in sorted(selected)]
