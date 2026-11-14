"""Shared price/FX row validation used by legacy and pipeline imports."""

from datetime import UTC, datetime

from cyclescope.application.dto.market_data import RawDailyPriceRecord, RawFxRateRecord
from cyclescope.application.dto.market_data_ingestion import (
    DailyPriceIngestionContext,
    FxRateIngestionContext,
)
from cyclescope.domain.entities.daily_price import DailyPrice
from cyclescope.domain.entities.fx_rate import FxRate
from cyclescope.domain.value_objects.market_data import CurrencyPair


def daily_price_from_record(
    row: RawDailyPriceRecord, context: DailyPriceIngestionContext
) -> DailyPrice:
    if row.parsing_errors:
        raise ValueError("; ".join(row.parsing_errors))
    if row.observation_date is None:
        raise ValueError("date is required.")
    prices = (row.open, row.high, row.low, row.close)
    if any(value is None for value in prices):
        raise ValueError("open, high, low, and close are required.")
    if row.volume is None:
        raise ValueError("volume is required.")
    now = datetime.now(UTC)
    return DailyPrice(
        security_id=context.security_id,
        observation_date=row.observation_date,
        open=row.open,  # type: ignore[arg-type]
        high=row.high,  # type: ignore[arg-type]
        low=row.low,  # type: ignore[arg-type]
        close=row.close,  # type: ignore[arg-type]
        adjusted_close=row.adjusted_close,
        volume=row.volume,
        currency=context.currency,
        source_id=context.source_id,
        publication_date=row.publication_date,
        available_at=context.available_at,
        collected_at=context.collected_at,
        revision_number=context.revision_number,
        created_at=now,
        updated_at=now,
    )


def fx_rate_from_record(
    row: RawFxRateRecord, context: FxRateIngestionContext
) -> FxRate:
    if row.parsing_errors:
        raise ValueError("; ".join(row.parsing_errors))
    if row.base_currency is None or row.quote_currency is None:
        raise ValueError("base_currency and quote_currency are required.")
    pair = CurrencyPair(
        row.base_currency.strip().upper(), row.quote_currency.strip().upper()
    )
    if (
        pair.base_currency != context.base_currency
        or pair.quote_currency != context.quote_currency
    ):
        raise ValueError("CSV currency pair does not match the ingestion context.")
    if row.observation_date is None:
        raise ValueError("date is required.")
    if row.rate is None:
        raise ValueError("rate is required.")
    return FxRate(
        base_currency=pair.base_currency,
        quote_currency=pair.quote_currency,
        observation_date=row.observation_date,
        rate=row.rate,
        source_id=context.source_id,
        publication_date=row.publication_date,
        available_at=context.available_at,
        collected_at=context.collected_at,
        revision_number=context.revision_number,
    )
