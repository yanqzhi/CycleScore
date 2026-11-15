# External Industry Classification Master

## Purpose and identifiers

CycleScore's internal `Industry` and `SubIndustry` IDs remain canonical. A
`ClassificationScheme` identifies an external taxonomy (for example GICS or
NAICS); its code is an extensible stable string, not a closed enum. A
`ClassificationVersion` identifies one release, and an
`IndustryClassificationMapping` connects an external code to an existing
internal industry and optionally a sub-industry. No external code replaces an
internal ID.

## Historical semantics

Versions have inclusive effective date ranges and optional source publication
timestamps. Mappings have their own inclusive validity ranges, contained in the
version range. Resolution requires an explicit scheme, version, external code,
and effective date; both date ranges must include that date. There is no fuzzy
matching, fallback to another version, or automatic choice among eligible
mappings. The exact mapping row is returned for audit. `published_at` is
metadata and does not imply effective or public availability. Mapping
resolution does not use observation `collected_at`.

Version effective periods within a scheme and mapping periods for the same code
within a version are required not to overlap. New historical interpretations
are represented with new versions or non-overlapping mapping periods; existing
mapping targets are not updated or deleted. Approximate mapping confidence is
optional and is never invented by the system.

## Industry Signal compatibility

Migration `0021_classification_and_region_masters` adds nullable
`classification_version_id` and `classification_mapping_id` references to new
Industry Signal observations. They must be supplied together. Existing rows
are untouched and retain their original `industry_id`, optional
`sub_industry_id`, and `region_code`; no mapping is backfilled. When supplied,
the importer checks that the mapping belongs to the version, targets the exact
internal scope, and is valid on the observation period end or point date. The
FKs preserve the mapping record that justified ingestion.

The master is not a provider adapter and does not download or discover
classifications. It performs no company-name matching, crosswalk inference,
industry conversion, signal aggregation, or currency/unit conversion.

## Transaction and limitations

Repositories flush but never commit. Callers own transactions and rollback.
Application validation checks interval overlaps, but concurrent registrations
must be serialized by the caller because portable SQL constraints cannot
express inclusive interval exclusion on SQLite. Classification and mapping
records are append-only through the supported repository APIs. The database
does not provide a general exclusion constraint for overlapping intervals.
