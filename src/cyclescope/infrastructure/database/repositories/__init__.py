"""SQLAlchemy repository implementations."""

from cyclescope.infrastructure.database.repositories.classification import (
    SQLAlchemyClassificationSchemeRepository,
    SQLAlchemyClassificationVersionRepository,
    SQLAlchemyIndustryClassificationMappingRepository,
)
from cyclescope.infrastructure.database.repositories.cycle_score import (
    SQLAlchemyCycleScoreRepository,
)
from cyclescope.infrastructure.database.repositories.data_quality import (
    SQLAlchemyDataQualityRepository,
)
from cyclescope.infrastructure.database.repositories.industry_inventory import (
    SQLAlchemyIndustryInventoryRepository,
)
from cyclescope.infrastructure.database.repositories.industry_signal import (
    SQLAlchemyIndustrySignalObservationRepository,
)
from cyclescope.infrastructure.database.repositories.industry_signal_aggregate import (
    SQLAlchemyIndustrySignalAggregateRepository,
)
from cyclescope.infrastructure.database.repositories.inventory import (
    SQLAlchemyInventorySnapshotRepository,
)
from cyclescope.infrastructure.database.repositories.market_data import (
    SQLAlchemyDailyPriceRepository,
    SQLAlchemyFxRateRepository,
)
from cyclescope.infrastructure.database.repositories.master_data import (
    CompanyIndustryExposureSqlAlchemyRepository,
    CompanySqlAlchemyRepository,
    ExchangeSqlAlchemyRepository,
    ListingSqlAlchemyRepository,
    SecurityIdentifierSqlAlchemyRepository,
    SecuritySqlAlchemyRepository,
)
from cyclescope.infrastructure.database.repositories.region import (
    SQLAlchemyRegionRelationshipRepository,
    SQLAlchemyRegionRepository,
)

__all__ = [
    "CompanyIndustryExposureSqlAlchemyRepository",
    "CompanySqlAlchemyRepository",
    "ExchangeSqlAlchemyRepository",
    "ListingSqlAlchemyRepository",
    "SecurityIdentifierSqlAlchemyRepository",
    "SecuritySqlAlchemyRepository",
    "SQLAlchemyDailyPriceRepository",
    "SQLAlchemyFxRateRepository",
    "SQLAlchemyDataQualityRepository",
    "SQLAlchemyIngestionRunRepository",
    "SQLAlchemyRawDataRepository",
    "SQLAlchemyFinancialItemMappingRepository",
    "SQLAlchemyFinancialItemRepository",
    "SQLAlchemyFinancialStatementItemRepository",
    "SQLAlchemyFinancialStatementRepository",
    "SQLAlchemyNormalizedEarningsRepository",
    "SQLAlchemyValuationPercentileRepository",
    "SQLAlchemyValueScoreRepository",
    "SQLAlchemyCycleScoreRepository",
    "SQLAlchemyInventorySnapshotRepository",
    "SQLAlchemyIndustrySignalObservationRepository",
    "SQLAlchemyIndustrySignalAggregateRepository",
    "SQLAlchemyIndustryInventoryRepository",
    "SQLAlchemyClassificationSchemeRepository",
    "SQLAlchemyClassificationVersionRepository",
    "SQLAlchemyIndustryClassificationMappingRepository",
    "SQLAlchemyRegionRepository",
    "SQLAlchemyRegionRelationshipRepository",
]

from cyclescope.infrastructure.database.repositories.financial_data import (
    SQLAlchemyFinancialItemMappingRepository,
    SQLAlchemyFinancialItemRepository,
    SQLAlchemyFinancialStatementItemRepository,
    SQLAlchemyFinancialStatementRepository,
)
from cyclescope.infrastructure.database.repositories.ingestion import (
    SQLAlchemyIngestionRunRepository,
    SQLAlchemyRawDataRepository,
)
from cyclescope.infrastructure.database.repositories.normalized_earnings import (
    SQLAlchemyNormalizedEarningsRepository,
)
from cyclescope.infrastructure.database.repositories.valuation_percentile import (
    SQLAlchemyValuationPercentileRepository,
)
from cyclescope.infrastructure.database.repositories.value_score import (
    SQLAlchemyValueScoreRepository,
)
