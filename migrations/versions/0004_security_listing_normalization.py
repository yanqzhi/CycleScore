"""Normalize Security versus Listing and reconcile legacy venue metadata."""

from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op

revision = "0004_security_listing_normalization"
down_revision = "0003_multimarket_master_data"
branch_labels = None
depends_on = None

# ISO 10383 MIC codes and venue metadata from the ISO market identifier code
# registry. Aliases cover common legacy labels without guessing unknown venues.
KNOWN_EXCHANGES: dict[str, tuple[str, str, str, str, str, str]] = {
    "XTKS": ("Tokyo Stock Exchange", "JP", "Asia", "Asia/Tokyo", "JPY", "XTKS"),
    "TSE": ("Tokyo Stock Exchange", "JP", "Asia", "Asia/Tokyo", "JPY", "XTKS"),
    "TSE/TYO": ("Tokyo Stock Exchange", "JP", "Asia", "Asia/Tokyo", "JPY", "XTKS"),
    "XNYS": (
        "New York Stock Exchange",
        "US",
        "Americas",
        "America/New_York",
        "USD",
        "XNYS",
    ),
    "NYSE": (
        "New York Stock Exchange",
        "US",
        "Americas",
        "America/New_York",
        "USD",
        "XNYS",
    ),
    "XNAS": (
        "Nasdaq Stock Market",
        "US",
        "Americas",
        "America/New_York",
        "USD",
        "XNAS",
    ),
    "NASDAQ": (
        "Nasdaq Stock Market",
        "US",
        "Americas",
        "America/New_York",
        "USD",
        "XNAS",
    ),
    "XSHG": ("Shanghai Stock Exchange", "CN", "Asia", "Asia/Shanghai", "CNY", "XSHG"),
    "SSE": ("Shanghai Stock Exchange", "CN", "Asia", "Asia/Shanghai", "CNY", "XSHG"),
    "XSHE": ("Shenzhen Stock Exchange", "CN", "Asia", "Asia/Shanghai", "CNY", "XSHE"),
    "SZSE": ("Shenzhen Stock Exchange", "CN", "Asia", "Asia/Shanghai", "CNY", "XSHE"),
    "XHKG": (
        "Hong Kong Exchanges and Clearing",
        "HK",
        "Asia",
        "Asia/Hong_Kong",
        "HKD",
        "XHKG",
    ),
    "HKEX": (
        "Hong Kong Exchanges and Clearing",
        "HK",
        "Asia",
        "Asia/Hong_Kong",
        "HKD",
        "XHKG",
    ),
}


def _record_unmapped(
    connection: sa.Connection,
    row: sa.Row[tuple[object, ...]],
    reason: str,
    now: str,
) -> None:
    """Retain all original listing fields for explicit downstream reconciliation."""
    exists = connection.execute(
        sa.text(
            "SELECT id FROM legacy_listing_reconciliation "
            "WHERE security_id = :security_id"
        ),
        {"security_id": row.id},
    ).first()
    if exists is None:
        connection.execute(
            sa.text(
                "INSERT INTO legacy_listing_reconciliation "
                "(security_id, ticker, exchange_code, currency, listing_date, "
                "delisting_date, reason, created_at, updated_at) VALUES "
                "(:security_id, :ticker, :exchange_code, :currency, :listing_date, "
                ":delisting_date, :reason, :created_at, :updated_at)"
            ),
            {
                "security_id": row.id,
                "ticker": row.ticker,
                "exchange_code": row.exchange,
                "currency": row.currency,
                "listing_date": row.listing_date,
                "delisting_date": row.delisting_date,
                "reason": reason,
                "created_at": now,
                "updated_at": now,
            },
        )


def upgrade() -> None:
    """Migrate known legacy listings and retain unknown rows for reconciliation."""
    op.create_table(
        "legacy_listing_reconciliation",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "security_id",
            sa.Integer(),
            sa.ForeignKey("securities.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("ticker", sa.String(32), nullable=False),
        sa.Column("exchange_code", sa.String(32), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("listing_date", sa.Date()),
        sa.Column("delisting_date", sa.Date()),
        sa.Column("reason", sa.String(240), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("security_id", name="uq_legacy_listing_security"),
    )

    connection = op.get_bind()
    now = datetime.now(UTC).isoformat(sep=" ")
    security_rows = connection.execute(
        sa.text(
            "SELECT id, ticker, exchange, currency, listing_date, delisting_date, "
            "is_active FROM securities ORDER BY id"
        )
    )
    for row in security_rows:
        raw_code = (row.exchange or "").strip().upper()
        known = KNOWN_EXCHANGES.get(raw_code)
        exchange = connection.execute(
            sa.text("SELECT id FROM exchanges WHERE exchange_code = :code"),
            {"code": raw_code},
        ).first()
        if exchange is not None:
            exchange_id = exchange.id
        elif known is not None:
            name, country, region, timezone, currency, canonical_code = known
            existing = connection.execute(
                sa.text("SELECT id FROM exchanges WHERE exchange_code = :code"),
                {"code": canonical_code},
            ).first()
            if existing is None:
                connection.execute(
                    sa.text(
                        "INSERT INTO exchanges (exchange_code, exchange_name, "
                        "country_code, market_region, timezone, currency_code, "
                        "is_active, created_at, updated_at) VALUES (:code, :name, "
                        ":country, :region, :timezone, "
                        ":currency, 1, :created_at, :updated_at)"
                    ),
                    {
                        "code": canonical_code,
                        "name": name,
                        "country": country,
                        "region": region,
                        "timezone": timezone,
                        "currency": currency,
                        "created_at": now,
                        "updated_at": now,
                    },
                )
                exchange_id = connection.execute(
                    sa.text("SELECT id FROM exchanges WHERE exchange_code = :code"),
                    {"code": canonical_code},
                ).scalar_one()
            else:
                exchange_id = existing.id
        else:
            _record_unmapped(
                connection, row, "Unknown exchange code; metadata not inferred.", now
            )
            continue

        if row.listing_date is None:
            _record_unmapped(connection, row, "Legacy listing date is missing.", now)
            continue
        if not row.is_active and row.delisting_date is None:
            _record_unmapped(
                connection,
                row,
                "Inactive legacy Security has no delisting date; listing status "
                "is ambiguous.",
                now,
            )
            continue

        status = "delisted" if row.delisting_date is not None else "active"
        existing_listing = connection.execute(
            sa.text(
                "SELECT id, security_id FROM listings WHERE exchange_id = :exchange_id "
                "AND ticker = :ticker AND listing_date = :listing_date"
            ),
            {
                "exchange_id": exchange_id,
                "ticker": row.ticker,
                "listing_date": row.listing_date,
            },
        ).first()
        if existing_listing is not None and existing_listing.security_id != row.id:
            _record_unmapped(
                connection,
                row,
                "Matching listing key is already assigned to another Security.",
                now,
            )
            continue
        if existing_listing is None:
            connection.execute(
                sa.text(
                    "INSERT INTO listings (security_id, exchange_id, ticker, "
                    "trading_currency, listing_date, delisting_date, status, "
                    "created_at, updated_at) VALUES "
                    "(:security_id, :exchange_id, :ticker, :currency, :listing_date, "
                    ":delisting_date, :status, :created_at, :updated_at)"
                ),
                {
                    "security_id": row.id,
                    "exchange_id": exchange_id,
                    "ticker": row.ticker,
                    "currency": row.currency,
                    "listing_date": row.listing_date,
                    "delisting_date": row.delisting_date,
                    "status": status,
                    "created_at": now,
                    "updated_at": now,
                },
            )
            listing_id = connection.execute(
                sa.text(
                    "SELECT id FROM listings WHERE exchange_id = :exchange_id "
                    "AND ticker = :ticker AND listing_date = :listing_date "
                    "AND security_id = :security_id"
                ),
                {
                    "exchange_id": exchange_id,
                    "ticker": row.ticker,
                    "listing_date": row.listing_date,
                    "security_id": row.id,
                },
            ).scalar_one()
        else:
            listing_id = existing_listing.id
        event_date = row.delisting_date if status == "delisted" else row.listing_date
        event_exists = connection.execute(
            sa.text(
                "SELECT id FROM listing_status_events WHERE listing_id = :listing_id "
                "AND effective_date = :effective_date"
            ),
            {"listing_id": listing_id, "effective_date": event_date},
        ).first()
        if event_exists is None:
            connection.execute(
                sa.text(
                    "INSERT INTO listing_status_events (listing_id, status, "
                    "effective_date, created_at, updated_at) "
                    "VALUES (:listing_id, :status, :effective_date, "
                    ":created_at, :updated_at)"
                ),
                {
                    "listing_id": listing_id,
                    "status": status,
                    "effective_date": event_date,
                    "created_at": now,
                    "updated_at": now,
                },
            )

    # Rebuild the SQLite table to remove the old ticker uniqueness and legacy
    # listing columns after all their values have been normalized or retained.
    if connection.dialect.name == "sqlite":
        with op.batch_alter_table("securities", recreate="always") as batch_op:
            batch_op.drop_constraint("uq_securities_exchange_ticker", type_="unique")
            batch_op.drop_column("ticker")
            batch_op.drop_column("exchange")
            batch_op.drop_column("currency")
            batch_op.drop_column("listing_date")
            batch_op.drop_column("delisting_date")
    else:
        op.drop_constraint(
            "uq_securities_exchange_ticker", "securities", type_="unique"
        )
        for column in (
            "ticker",
            "exchange",
            "currency",
            "listing_date",
            "delisting_date",
        ):
            op.drop_column("securities", column)


def downgrade() -> None:
    """Restore optional legacy columns without deleting normalized listing data."""
    with op.batch_alter_table("securities", recreate="always") as batch_op:
        batch_op.add_column(sa.Column("ticker", sa.String(32), nullable=True))
        batch_op.add_column(sa.Column("exchange", sa.String(32), nullable=True))
        batch_op.add_column(sa.Column("currency", sa.String(3), nullable=True))
        batch_op.add_column(sa.Column("listing_date", sa.Date(), nullable=True))
        batch_op.add_column(sa.Column("delisting_date", sa.Date(), nullable=True))
