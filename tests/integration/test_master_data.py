"""Multi-market master-data application and persistence tests."""

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from cyclescope.application.dto.master_data import (
    CompanyIndustryExposureInput,
    CompanyInput,
    ExchangeInput,
    ListingInput,
    ListingStatusInput,
    SecurityIdentifierInput,
    SecurityInput,
)
from cyclescope.application.use_cases.master_data import (
    RegisterCompany,
    RegisterCompanyIndustryExposure,
    RegisterExchange,
    RegisterListing,
    RegisterSecurity,
    RegisterSecurityIdentifier,
    UpdateCompany,
    UpdateCompanyIndustryExposure,
    UpdateExchange,
    UpdateListingStatus,
    UpdateSecurity,
    UpdateSecurityIdentifier,
)
from cyclescope.domain.entities import Company, Industry, Listing, SubIndustry
from cyclescope.domain.exceptions import DomainValidationError
from cyclescope.infrastructure.database.models import (
    CompanyIndustryExposureModel,
    DailyPriceModel,
    DataSourceModel,
    ListingStatusEventModel,
    SecurityIdentifierModel,
)
from cyclescope.infrastructure.database.repositories.master_data import (
    CompanyIndustryExposureSqlAlchemyRepository,
    CompanySqlAlchemyRepository,
    ExchangeSqlAlchemyRepository,
    IndustrySqlAlchemyRepository,
    ListingSqlAlchemyRepository,
    ListingStatusEventSqlAlchemyRepository,
    SecurityIdentifierSqlAlchemyRepository,
    SecuritySqlAlchemyRepository,
    SubIndustrySqlAlchemyRepository,
)


def test_companies_securities_exchanges_and_identifiers(session: Session) -> None:
    companies = CompanySqlAlchemyRepository(session)
    securities = SecuritySqlAlchemyRepository(session)
    exchanges = ExchangeSqlAlchemyRepository(session)
    identifiers = SecurityIdentifierSqlAlchemyRepository(session)
    company = RegisterCompany(companies).execute(CompanyInput("Issuer", "JP"))
    one = RegisterSecurity(securities).execute(
        SecurityInput(company.id or 0, "common_stock")
    )
    two = RegisterSecurity(securities).execute(
        SecurityInput(company.id or 0, "preferred_stock")
    )
    assert one.company_id == two.company_id
    assert securities.list() == [one, two]
    updated_company = UpdateCompany(companies).execute(
        company.id or 0, CompanyInput("Updated Issuer", "JP")
    )
    assert updated_company is not None and updated_company.name == "Updated Issuer"
    updated_security = UpdateSecurity(securities).execute(
        one.id or 0,
        SecurityInput(company.id or 0, "depositary_receipt"),
    )
    assert (
        updated_security is not None
        and updated_security.security_type == "depositary_receipt"
    )

    venue_one = RegisterExchange(exchanges).execute(
        ExchangeInput("XTKS", "Tokyo Stock Exchange", "JP", "Asia", "Asia/Tokyo", "JPY")
    )
    venue_two = RegisterExchange(exchanges).execute(
        ExchangeInput(
            "XNYS",
            "New York Stock Exchange",
            "US",
            "Americas",
            "America/New_York",
            "USD",
        )
    )
    assert venue_one.exchange_id != venue_two.exchange_id
    renamed = UpdateExchange(exchanges).execute(
        venue_one.exchange_id or 0,
        ExchangeInput("XTKS", "Tokyo Exchange", "JP", "Asia", "Asia/Tokyo", "JPY"),
    )
    assert renamed is not None and renamed.exchange_name == "Tokyo Exchange"
    mainland = RegisterExchange(exchanges).execute(
        ExchangeInput(
            "XSHG", "Shanghai Stock Exchange", "CN", "Asia", "Asia/Shanghai", "CNY"
        )
    )
    assert mainland.country_code == "CN"

    created = RegisterSecurityIdentifier(identifiers).execute(
        SecurityIdentifierInput(
            one.id or 0,
            "ISIN",
            "JP0000000001",
            date(2010, 1, 1),
            valid_to=date(2011, 12, 31),
        )
    )
    RegisterSecurityIdentifier(identifiers).execute(
        SecurityIdentifierInput(one.id or 0, "FIGI", "BBG000000001", date(2010, 1, 1))
    )
    with pytest.raises(DomainValidationError, match="identifier"):
        RegisterSecurityIdentifier(identifiers).execute(
            SecurityIdentifierInput(
                two.id or 0,
                "ISIN",
                "JP0000000001",
                date(2011, 1, 1),
                exchange_id=venue_two.exchange_id,
            )
        )
    with pytest.raises(DomainValidationError, match="identifier"):
        RegisterSecurityIdentifier(identifiers).execute(
            SecurityIdentifierInput(
                two.id or 0, "ISIN", "JP0000000001", date(2011, 1, 1)
            )
        )
    historical_reuse = RegisterSecurityIdentifier(identifiers).execute(
        SecurityIdentifierInput(two.id or 0, "ISIN", "JP0000000001", date(2012, 1, 1))
    )
    ticker_code = RegisterSecurityIdentifier(identifiers).execute(
        SecurityIdentifierInput(
            one.id or 0,
            "TRADING_CODE",
            "0001",
            date(2010, 1, 1),
            exchange_id=venue_one.exchange_id,
            valid_to=date(2011, 12, 31),
        )
    )
    with pytest.raises(DomainValidationError, match="identifier"):
        RegisterSecurityIdentifier(identifiers).execute(
            SecurityIdentifierInput(
                two.id or 0,
                "TRADING_CODE",
                "0001",
                date(2011, 1, 1),
                exchange_id=venue_one.exchange_id,
            )
        )
    other_exchange_code = RegisterSecurityIdentifier(identifiers).execute(
        SecurityIdentifierInput(
            two.id or 0,
            "TRADING_CODE",
            "0001",
            date(2010, 1, 1),
            exchange_id=venue_two.exchange_id,
        )
    )
    historical_code = RegisterSecurityIdentifier(identifiers).execute(
        SecurityIdentifierInput(
            two.id or 0,
            "TRADING_CODE",
            "0001",
            date(2012, 1, 1),
            exchange_id=venue_one.exchange_id,
        )
    )
    conflicting_update = RegisterSecurityIdentifier(identifiers).execute(
        SecurityIdentifierInput(two.id or 0, "CUSIP", "123456789", date(2010, 1, 1))
    )
    with pytest.raises(DomainValidationError, match="identifier"):
        UpdateSecurityIdentifier(identifiers).execute(
            conflicting_update.id or 0,
            SecurityIdentifierInput(
                two.id or 0, "ISIN", "JP0000000001", date(2011, 1, 1)
            ),
        )
    assert identifiers.list_by_security(one.id or 0)[0] == created
    assert historical_reuse.valid_from == date(2012, 1, 1)
    assert ticker_code.exchange_id == venue_one.exchange_id
    assert other_exchange_code.exchange_id == venue_two.exchange_id
    assert historical_code.valid_from == date(2012, 1, 1)
    session.add(
        SecurityIdentifierModel(
            security_id=two.id or 0,
            identifier_type="ISIN",
            identifier_value="JP0000000002",
            exchange_id=venue_two.exchange_id,
            valid_from=date(2010, 1, 1),
        )
    )
    session.flush()
    with pytest.raises(DomainValidationError, match="identifier"):
        RegisterSecurityIdentifier(identifiers).execute(
            SecurityIdentifierInput(
                one.id or 0, "ISIN", "JP0000000002", date(2010, 1, 1)
            )
        )
    assert session.query(SecurityIdentifierModel).count() == 8
    session.add(
        SecurityIdentifierModel(
            security_id=two.id or 0,
            identifier_type="ISIN",
            identifier_value="JP0000000001",
            valid_from=date(2010, 1, 1),
        )
    )
    with pytest.raises(IntegrityError):
        session.flush()
    session.rollback()


def test_listing_history_scoped_tickers_and_status_events(session: Session) -> None:
    with pytest.raises(DomainValidationError, match="delisting_date"):
        Listing(
            security_id=1,
            exchange_id=1,
            ticker="BAD",
            trading_currency="USD",
            listing_date=date(2022, 1, 1),
            delisting_date=date(2021, 1, 1),
            status="delisted",
        )
    company = CompanySqlAlchemyRepository(session).create(
        Company(name="Dual Listed", country_code="HK")
    )
    security_repo = SecuritySqlAlchemyRepository(session)
    security_a = RegisterSecurity(security_repo).execute(
        SecurityInput(company.id or 0, "common_stock")
    )
    security_b = RegisterSecurity(security_repo).execute(
        SecurityInput(company.id or 0, "preferred_stock")
    )
    exchange_repo = ExchangeSqlAlchemyRepository(session)
    hk = RegisterExchange(exchange_repo).execute(
        ExchangeInput(
            "XHKG", "Hong Kong Exchange", "HK", "Asia", "Asia/Hong_Kong", "HKD"
        )
    )
    ny = RegisterExchange(exchange_repo).execute(
        ExchangeInput(
            "XNYS",
            "New York Stock Exchange",
            "US",
            "Americas",
            "America/New_York",
            "USD",
        )
    )
    listing_repo = ListingSqlAlchemyRepository(session)
    event_repo = ListingStatusEventSqlAlchemyRepository(session)
    register = RegisterListing(listing_repo, event_repo)
    listing = register.execute(
        ListingInput(
            security_a.id or 0, hk.exchange_id or 0, "DUAL", "HKD", date(2020, 1, 1)
        )
    )
    other_market_listing = register.execute(
        ListingInput(
            security_a.id or 0, ny.exchange_id or 0, "DUAL", "USD", date(2021, 1, 1)
        )
    )
    security_listings = listing_repo.list_by_security(security_a.id or 0)
    assert security_listings == [listing, other_market_listing]
    assert all(item.security_id == security_a.id for item in security_listings)
    assert (listing.exchange_id, listing.trading_currency, listing.listing_date) == (
        hk.exchange_id,
        "HKD",
        date(2020, 1, 1),
    )
    assert (
        other_market_listing.exchange_id,
        other_market_listing.trading_currency,
    ) == (
        ny.exchange_id,
        "USD",
    )
    source = DataSourceModel(code="MASTER_TEST", name="Test", provider_type="manual")
    session.add(source)
    session.flush()
    session.add(
        DailyPriceModel(
            security_id=security_a.id,
            observation_date=date(2024, 1, 2),
            open=1,
            high=1,
            low=1,
            close=1,
            volume=1,
            currency="HKD",
            source_id=source.id,
            available_at=datetime(2024, 1, 3, tzinfo=UTC),
            collected_at=datetime(2024, 1, 3, tzinfo=UTC),
            revision_number=1,
        )
    )
    session.flush()
    assert session.query(DailyPriceModel).one().security_id == security_a.id
    with pytest.raises(DomainValidationError, match="start active"):
        register.execute(
            ListingInput(
                security_a.id or 0,
                hk.exchange_id or 0,
                "PAUSED",
                "HKD",
                date(2024, 1, 1),
                status="suspended",
            )
        )
    with pytest.raises(DomainValidationError, match="overlapping"):
        register.execute(
            ListingInput(
                security_b.id or 0, hk.exchange_id or 0, "DUAL", "HKD", date(2022, 1, 1)
            )
        )

    update = UpdateListingStatus(listing_repo, event_repo)
    suspended = update.execute(
        ListingStatusInput(listing.id or 0, "suspended", date(2022, 1, 1))
    )
    delisted = update.execute(
        ListingStatusInput(listing.id or 0, "delisted", date(2023, 1, 1))
    )
    assert suspended is not None and suspended.listing_date == date(2020, 1, 1)
    assert delisted is not None and delisted.delisting_date == date(2023, 1, 1)
    assert [event.status for event in event_repo.list_by_listing(listing.id or 0)] == [
        "active",
        "suspended",
        "delisted",
    ]
    assert event_repo.list_by_listing(listing.id or 0)[0].effective_date == date(
        2020, 1, 1
    )
    with pytest.raises(DomainValidationError):
        update.execute(ListingStatusInput(listing.id or 0, "active", date(2024, 1, 1)))
    relisted = register.execute(
        ListingInput(
            security_b.id or 0,
            hk.exchange_id or 0,
            "DUAL",
            "HKD",
            date(2024, 1, 1),
        )
    )
    assert relisted.security_id == security_b.id
    assert session.query(ListingStatusEventModel).count() == 5


def test_exposure_aggregate_validates_overlapping_and_non_overlapping_periods(
    session: Session,
) -> None:
    company = CompanySqlAlchemyRepository(session).create(
        Company(name="Exposure Co", country_code="JP")
    )
    industry_repo = IndustrySqlAlchemyRepository(session)
    industry = industry_repo.create(Industry(code="TECH", name="Technology"))
    subs = SubIndustrySqlAlchemyRepository(session)
    sub_a = subs.create(SubIndustry(industry.id or 0, "SOFT", "Software"))
    sub_b = subs.create(SubIndustry(industry.id or 0, "HARD", "Hardware"))
    repository = CompanyIndustryExposureSqlAlchemyRepository(session)
    register = RegisterCompanyIndustryExposure(repository)
    start_a = CompanyIndustryExposureInput(
        company.id or 0,
        sub_a.id or 0,
        Decimal("0.6"),
        date(2020, 1, 1),
        date(2020, 12, 31),
    )
    first = register.execute(start_a)
    second = register.execute(
        CompanyIndustryExposureInput(
            company.id or 0, sub_b.id or 0, Decimal("0.6"), date(2021, 1, 1), None
        )
    )
    assert len(repository.list_by_company(company.id or 0)) == 2
    with pytest.raises(DomainValidationError, match="exceed"):
        register.execute(
            CompanyIndustryExposureInput(
                company.id or 0,
                sub_b.id or 0,
                Decimal("0.5"),
                date(2020, 6, 1),
                date(2020, 8, 1),
            )
        )
    updated = UpdateCompanyIndustryExposure(repository).execute(
        second.id or 0,
        CompanyIndustryExposureInput(
            company.id or 0,
            sub_b.id or 0,
            Decimal("0.4"),
            date(2020, 1, 1),
            date(2020, 12, 31),
        ),
    )
    assert updated is not None and updated.revenue_share == Decimal("0.4")
    assert first.revenue_share == Decimal("0.6")
    assert session.query(CompanyIndustryExposureModel).count() == 2


def test_exposure_persistence_failure_rolls_back_transaction(session: Session) -> None:
    company = CompanySqlAlchemyRepository(session).create(
        Company(name="Rollback Co", country_code="US")
    )
    session.commit()
    with pytest.raises(IntegrityError):
        with session.begin():
            RegisterCompanyIndustryExposure(
                CompanyIndustryExposureSqlAlchemyRepository(session)
            ).execute(
                CompanyIndustryExposureInput(
                    company.id or 0, 999, Decimal("0.5"), date(2020, 1, 1), None
                )
            )
    assert session.query(CompanyIndustryExposureModel).count() == 0
