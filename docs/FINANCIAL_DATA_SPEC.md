# Financial Data Specification

## Model and scope

`FinancialStatement` records a company report and its source-specific revision. `FinancialStatementItem` stores one standardized item value. `FinancialItem` defines the controlled item taxonomy; `FinancialItemMapping` maps source codes into that taxonomy. All master-data foreign keys use RESTRICT semantics. Numeric values use `Decimal` and SQL `NUMERIC(38, 12)`: 26 integer digits and 12 fractional digits, an explicit bound for multi-market reporting.

Statement types are BS (balance sheet), PL (income statement), and CF (cash flow). BS describes an instant and permits a missing start date. PL and CF cover a period and require a start date. Fiscal periods are FY, Q1–Q4, H1, 9M, and TTM. `fiscal_year` is a reporting label; it is not inferred from calendar dates. Sources may report cumulative or discrete quarterly amounts; the system stores the reported period and value unchanged and does not derive discrete quarters.

## Units

Amounts and their reported scale are preserved. `scale_multiplier` is a positive integer and is not applied to the stored Decimal. No conversion occurs. Currency amount lines use `CURRENCY` and require a currency code; per-share lines use `PER_SHARE` and also require a currency. Shares, percentage, ratio, and count use the corresponding unit code and no currency. Currency-bearing line currencies must match statement reporting currency. Negative values are allowed; accounting interpretation belongs to later analysis layers.

## Time and provenance

`period_end` describes the reported period. `publication_date` and optional `publication_datetime` describe source publication. `available_at` records when the system could use the information. `collected_at` records retrieval time. They are distinct, and timestamps are normalized to UTC. Only `available_at <= as_of` determines historical visibility; period end, publication date, and collection time never substitute for it.

## Revisions and queries

A correction is a new statement revision; previous rows and values remain intact. Natural revision identity includes company, source, statement type, accounting standard, consolidation scope, fiscal year/period, period bounds, and revision number. Source is part of identity, so different sources coexist. Query code filters by availability first, then selects the highest visible revision within each source and reporting-period key. Results retain source boundaries; a singular query without source selection raises ambiguity if multiple sources match. The caller owns the transaction; import validates the complete statement before writing its header and lines, and transaction rollback is required if a persistence failure occurs.

## Current limitations

There is no live provider, document parser, currency conversion, taxonomy auto-mapping, cumulative-to-discrete conversion, TTM calculation, or financial analysis engine. A source's reporting convention and licensing metadata are not yet modeled. SQLite timestamp storage may return naive values; the adapter interprets these database values as UTC. Concurrent check-then-insert uniqueness relies on database indexes and the caller's transaction helper.
