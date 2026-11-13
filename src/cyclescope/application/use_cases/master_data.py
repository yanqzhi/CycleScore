"""Company, security, venue, identifier, listing, and exposure use cases."""

from dataclasses import replace
from datetime import date

from cyclescope.application.dto.master_data import (
    CompanyIndustryExposureInput,
    CompanyInput,
    ExchangeInput,
    ListingInput,
    ListingStatusInput,
    SecurityIdentifierInput,
    SecurityInput,
)
from cyclescope.application.use_cases.exposure_validation import (
    ExposureAggregateValidationError,
    validate_company_exposures,
)
from cyclescope.domain.entities import (
    Company,
    CompanyIndustryExposure,
    Exchange,
    Listing,
    ListingStatusEvent,
    Security,
    SecurityIdentifier,
)
from cyclescope.domain.exceptions import DomainValidationError
from cyclescope.domain.repositories.contracts import (
    CompanyIndustryExposureRepository,
    CompanyRepository,
    ExchangeRepository,
    ListingRepository,
    ListingStatusEventRepository,
    SecurityIdentifierRepository,
    SecurityRepository,
)
from cyclescope.domain.value_objects.security_identifier import resolve_identifier_scope


class RegisterCompany:
    def __init__(self, repository: CompanyRepository) -> None:
        self._repository = repository

    def execute(self, request: CompanyInput) -> Company:
        return self._repository.create(
            Company(
                name=request.name,
                country_code=request.country_code,
                fiscal_year_end=request.fiscal_year_end,
                reporting_currency=request.reporting_currency,
                listing_status=request.listing_status,
            )
        )


class UpdateCompany:
    def __init__(self, repository: CompanyRepository) -> None:
        self._repository = repository

    def execute(self, company_id: int, request: CompanyInput) -> Company | None:
        existing = self._repository.get_by_id(company_id)
        if existing is None:
            return None
        return self._repository.update(
            Company(
                id=company_id,
                name=request.name,
                country_code=request.country_code,
                fiscal_year_end=request.fiscal_year_end,
                reporting_currency=request.reporting_currency,
                listing_status=request.listing_status,
                created_at=existing.created_at,
            )
        )


class RegisterSecurity:
    def __init__(self, repository: SecurityRepository) -> None:
        self._repository = repository

    def execute(self, request: SecurityInput) -> Security:
        return self._repository.create(
            Security(
                company_id=request.company_id,
                security_type=request.security_type,
                is_active=request.is_active,
            )
        )


class UpdateSecurity:
    def __init__(self, repository: SecurityRepository) -> None:
        self._repository = repository

    def execute(self, security_id: int, request: SecurityInput) -> Security | None:
        if self._repository.get_by_id(security_id) is None:
            return None
        return self._repository.update(
            Security(
                id=security_id,
                company_id=request.company_id,
                security_type=request.security_type,
                is_active=request.is_active,
            )
        )


class RegisterExchange:
    def __init__(self, repository: ExchangeRepository) -> None:
        self._repository = repository

    def execute(self, request: ExchangeInput) -> Exchange:
        return self._repository.create(
            Exchange(
                exchange_code=request.exchange_code,
                exchange_name=request.exchange_name,
                country_code=request.country_code,
                market_region=request.market_region,
                timezone=request.timezone,
                currency_code=request.currency_code,
                is_active=request.is_active,
            )
        )


class UpdateExchange:
    def __init__(self, repository: ExchangeRepository) -> None:
        self._repository = repository

    def execute(self, exchange_id: int, request: ExchangeInput) -> Exchange | None:
        if self._repository.get_by_id(exchange_id) is None:
            return None
        return self._repository.update(
            Exchange(
                exchange_id=exchange_id,
                exchange_code=request.exchange_code,
                exchange_name=request.exchange_name,
                country_code=request.country_code,
                market_region=request.market_region,
                timezone=request.timezone,
                currency_code=request.currency_code,
                is_active=request.is_active,
            )
        )


def _ranges_overlap(
    left_start: date | None,
    left_end: date | None,
    right_start: date | None,
    right_end: date | None,
) -> bool:
    return (left_end is None or right_start is None or left_end >= right_start) and (
        right_end is None or left_start is None or right_end >= left_start
    )


class RegisterSecurityIdentifier:
    def __init__(self, repository: SecurityIdentifierRepository) -> None:
        self._repository = repository

    def execute(self, request: SecurityIdentifierInput) -> SecurityIdentifier:
        candidate = SecurityIdentifier(
            security_id=request.security_id,
            identifier_type=request.identifier_type,
            identifier_value=request.identifier_value,
            valid_from=request.valid_from,
            exchange_id=request.exchange_id,
            valid_to=request.valid_to,
        )
        for existing in self._repository.list_by_identifier(
            candidate.identifier_type,
            candidate.identifier_value,
            resolve_identifier_scope(candidate.identifier_type, candidate.exchange_id),
        ):
            if _ranges_overlap(
                existing.valid_from,
                existing.valid_to,
                candidate.valid_from,
                candidate.valid_to,
            ):
                raise DomainValidationError(
                    "An identifier cannot identify multiple securities during "
                    "overlapping dates."
                )
        return self._repository.create(candidate)


class UpdateSecurityIdentifier:
    def __init__(self, repository: SecurityIdentifierRepository) -> None:
        self._repository = repository

    def execute(
        self, identifier_id: int, request: SecurityIdentifierInput
    ) -> SecurityIdentifier | None:
        existing_record = self._repository.get_by_id(identifier_id)
        if existing_record is None:
            return None
        candidate = SecurityIdentifier(
            id=identifier_id,
            security_id=request.security_id,
            identifier_type=request.identifier_type,
            identifier_value=request.identifier_value,
            valid_from=request.valid_from,
            exchange_id=request.exchange_id,
            valid_to=request.valid_to,
        )
        for existing in self._repository.list_by_identifier(
            candidate.identifier_type,
            candidate.identifier_value,
            resolve_identifier_scope(candidate.identifier_type, candidate.exchange_id),
        ):
            if existing.id != identifier_id and _ranges_overlap(
                existing.valid_from,
                existing.valid_to,
                candidate.valid_from,
                candidate.valid_to,
            ):
                raise DomainValidationError(
                    "An identifier cannot identify multiple securities during "
                    "overlapping dates."
                )
        return self._repository.update(candidate)


class RegisterListing:
    def __init__(
        self,
        repository: ListingRepository,
        events: ListingStatusEventRepository,
    ) -> None:
        self._repository = repository
        self._events = events

    def execute(self, request: ListingInput) -> Listing:
        candidate = Listing(
            security_id=request.security_id,
            exchange_id=request.exchange_id,
            ticker=request.ticker,
            trading_currency=request.trading_currency,
            listing_date=request.listing_date,
            delisting_date=request.delisting_date,
            status=request.status,
        )
        if candidate.status != "active":
            raise DomainValidationError(
                "New listings must start active; record later status changes as events."
            )
        for existing in self._repository.list_by_exchange_ticker(
            candidate.exchange_id, candidate.ticker
        ):
            if _ranges_overlap(
                existing.listing_date,
                existing.delisting_date,
                candidate.listing_date,
                candidate.delisting_date,
            ):
                raise DomainValidationError(
                    "Ticker is already assigned on this exchange during "
                    "overlapping dates."
                )
        created = self._repository.create(candidate)
        self._events.create(
            ListingStatusEvent(
                listing_id=created.id or 0,
                status=created.status,
                effective_date=created.listing_date,
            )
        )
        return created


class UpdateListingStatus:
    """Append a status event while keeping listing identity and dates intact."""

    def __init__(
        self,
        listings: ListingRepository,
        events: ListingStatusEventRepository,
    ) -> None:
        self._listings = listings
        self._events = events

    def execute(self, request: ListingStatusInput) -> Listing | None:
        listing = self._listings.get_by_id(request.listing_id)
        if listing is None:
            return None
        history = self._events.list_by_listing(request.listing_id)
        if history and request.effective_date <= history[-1].effective_date:
            raise DomainValidationError("Listing status events must advance in time.")
        if request.effective_date < listing.listing_date:
            raise DomainValidationError("Status event cannot precede the listing date.")
        if listing.status == "delisted":
            raise DomainValidationError("A delisted listing cannot transition again.")
        if request.status == listing.status:
            raise DomainValidationError(
                "Listing status must change for a transition event."
            )
        delisting_date = listing.delisting_date
        if request.status == "delisted":
            delisting_date = request.effective_date
        updated = replace(listing, status=request.status, delisting_date=delisting_date)
        # No commit: caller's transaction covers both the snapshot and its event.
        persisted = self._listings.update(updated)
        if persisted is None:
            return None
        self._events.create(
            ListingStatusEvent(
                listing_id=request.listing_id,
                status=request.status,
                effective_date=request.effective_date,
            )
        )
        return persisted


class RegisterCompanyIndustryExposure:
    def __init__(self, repository: CompanyIndustryExposureRepository) -> None:
        self._repository = repository

    def execute(self, request: CompanyIndustryExposureInput) -> CompanyIndustryExposure:
        candidate = CompanyIndustryExposure(
            company_id=request.company_id,
            sub_industry_id=request.sub_industry_id,
            revenue_share=request.revenue_share,
            valid_from=request.valid_from,
            valid_to=request.valid_to,
            source_id=request.source_id,
        )
        try:
            validate_company_exposures(
                [*self._repository.list_by_company(candidate.company_id), candidate]
            )
        except ExposureAggregateValidationError as error:
            raise DomainValidationError(str(error)) from error
        return self._repository.create(candidate)


class UpdateCompanyIndustryExposure:
    def __init__(self, repository: CompanyIndustryExposureRepository) -> None:
        self._repository = repository

    def execute(
        self, exposure_id: int, request: CompanyIndustryExposureInput
    ) -> CompanyIndustryExposure | None:
        if self._repository.get_by_id(exposure_id) is None:
            return None
        candidate = CompanyIndustryExposure(
            id=exposure_id,
            company_id=request.company_id,
            sub_industry_id=request.sub_industry_id,
            revenue_share=request.revenue_share,
            valid_from=request.valid_from,
            valid_to=request.valid_to,
            source_id=request.source_id,
        )
        proposed = [
            exposure
            for exposure in self._repository.list_by_company(candidate.company_id)
            if exposure.id != exposure_id
        ]
        proposed.append(candidate)
        try:
            validate_company_exposures(proposed)
        except ExposureAggregateValidationError as error:
            raise DomainValidationError(str(error)) from error
        return self._repository.update(candidate)
