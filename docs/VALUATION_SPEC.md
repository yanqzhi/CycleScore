# Valuation Data Foundation

## Scope and boundaries

Sprint 09 provides versioned metric definitions, PIT input assembly, Decimal calculations, and append-only historical snapshots. Sprint 10's normalized earnings engine reuses these inputs and formulas for normalized PER and EV/EBITDA; this remains a foundation, not a valuation score, percentile model, screening system, or backtest engine. `BuildValuationInputs` reuses `GetFinancialStatements` and `MarketDataAccess`; it does not query SQLAlchemy models. The caller owns the transaction around input calculation and snapshot persistence.

`FinancialItem` remains the one standardized financial taxonomy. The input assembler recognizes these item codes when configured in that existing master: `EPS`, `NET_INCOME`, `TOTAL_EQUITY`, `CASH_AND_CASH_EQUIVALENTS`, `SHORT_TERM_DEBT`, `LONG_TERM_DEBT`, `OPERATING_PROFIT`, `DEPRECIATION_AMORTIZATION`, `SHARES_OUTSTANDING`, and `WEIGHTED_AVERAGE_SHARES`. Source values are stored unchanged with their scale multiplier. Valuation calculations apply `scale_multiplier` to obtain the arithmetic amount; imports do not rewrite the reported value.

## Metric definitions

| Code | Formula | Unit / currency | Validity |
| --- | --- | --- | --- |
| `PER` | Closing price / reported EPS, falling back to TTM net income / period-aligned weighted average shares | Ratio, no currency | Non-positive EPS is `NOT_APPLICABLE`; the loss-making EPS remains in the input snapshot. |
| `PBR` | Closing price / (latest eligible total equity / shares outstanding) | Ratio, no currency | Non-positive book value per share is `NOT_APPLICABLE`. |
| `MARKET_CAPITALIZATION` | Closing price × latest applicable shares outstanding | Market currency | Missing price or shares remains unavailable. |
| `ENTERPRISE_VALUE` | Market capitalization + short-term debt + long-term debt − cash and cash equivalents | Market currency | Both debt components and cash are required. No missing component is treated as zero; total debt is not also added. |
| `EV_EBITDA` | Enterprise value / (TTM operating profit + TTM depreciation and amortization) | Ratio, no currency | Non-positive EBITDA is `NOT_APPLICABLE`. |
| `EPS` | Reported EPS, otherwise TTM net income / weighted average shares | Market/reporting currency per share | Output records `REPORTED` or `DERIVED_NET_INCOME_OVER_WEIGHTED_SHARES`. |
| `BVPS` | Latest eligible total equity / latest eligible shares outstanding | Market/reporting currency per share | Zero shares is invalid input; negative equity remains a negative BVPS. |
| `EBITDA` | TTM operating profit + TTM depreciation and amortization | Market/reporting currency | Negative EBITDA is preserved; only the conventional EV/EBITDA ratio is not applicable. |

Definitions are stored in `valuation_metrics` with input requirements, unit, currency applicability, calculation method/version, validity rules, and active state. Initialization inserts missing defaults and does not overwrite customized existing definitions. Calculations dispatch through the centralized method registry; unknown methods fail explicitly.

## Financial period alignment

Balance-sheet inputs are taken together from the latest eligible balance sheet whose `period_end` is no later than the valuation date. They are point-in-time balances and are never added across quarters.

Income-statement flow values use a reported TTM value when present, otherwise the latest FY value, otherwise a derived TTM from exactly four consecutive fiscal quarters. A quarterly set is usable only when fiscal quarter labels are consecutive, actual period dates are contiguous and non-overlapping, and the combined span is 330–400 days. H1, 9M, incomplete quarter sets, and cumulative periods are not subtracted or annualized; they yield an explicit insufficient-input result unless a compatible FY/TTM value exists. Annual and quarterly values are never summed together. Each flow item must resolve to the same exact period start/end before values can be combined in a metric. Weighted average shares must match that period; four quarterly share averages are duration-weighted over the same four quarters. Fiscal year labels are not inferred from calendar year boundaries.

Directly reported FY/TTM EPS is preferred. Quarterly EPS is never summed: when no direct FY/TTM EPS is available, EPS is derived from TTM net income divided by weighted-average shares aligned to the same FY/TTM period (four quarterly share averages are duration-weighted). The derived result is marked `DERIVED_NET_INCOME_OVER_WEIGHTED_SHARES`; direct EPS is marked `REPORTED`. Input references retain the exact original fiscal-period codes, period bounds, publication date/datetime, available timestamp, statement/source ID, revision, and line IDs used in that calculation. Unsupported period alignment does not silently substitute a different period.

Shares outstanding must be positive for per-share divisors and market capitalization/enterprise value. Cash and cash equivalents are required but may be zero or negative; the EV formula uses the signed reported amount without an arbitrary positivity rule.

## Point-in-time contract

Every input request has a valuation date and an aware `as_of`; the UTC date of `as_of` must equal the valuation date. The price observation must be exactly that date. Market reads reuse `MarketDataAccess`, which applies `available_at <= as_of`, rejects future observation dates, and selects the highest eligible revision per source/date. Financial reads reuse `GetFinancialStatements`, which filters on `available_at <= as_of` before selecting the highest visible revision. `collected_at` is provenance only and never determines visibility. Financial statement period end must also be no later than the valuation date.

When multiple financial sources are eligible, the caller must provide `financial_source_id`; the assembler never mixes them. Different accounting standards, consolidation scopes, or reporting currencies are rejected rather than combined. For market data, an explicit source is honored; when omitted, the eligible source with the lowest source ID is selected deterministically and recorded. This stable fallback is not a preferred-source policy. Market and financial currencies must match because currency conversion is out of scope.

`closing_price` is used in valuation formulas. `adjusted_close` is retained in the input snapshot for traceability but is not substituted into market-capitalization calculations, which require a same-date nominal share price and share count. No currency conversion or share-count adjustment is performed.

## Results, status, and provenance

Calculations return a Decimal value only when status is `AVAILABLE`. `INSUFFICIENT_DATA` identifies missing or period-incompatible inputs; `INVALID_INPUT` identifies invalid arithmetic inputs such as a non-positive share divisor; `NOT_APPLICABLE` marks conventional ratios with non-positive EPS, book value, or EBITDA; `UNAVAILABLE` is reserved for an input contract that cannot be fulfilled. Every non-available result has an explanation, and missing inputs are never replaced with zero.

Each persisted snapshot records security, valuation date, cutoff, metric, value, currency, unit, financial period, only the price and financial source IDs and input values used by that metric, EPS calculation method where applicable, calculation version, status, reason, creation time, and source revision references. Missing-input explanations are kept separately from references to facts actually used. `valuation_snapshot_inputs` uses foreign keys to the exact daily-price row or financial statement line, parent statement, and source; it also records revision and publication/availability metadata. Snapshot inserts are append-only through the repository contract. Recalculation creates another row with a distinct database identity; it does not update earlier results. The caller's transaction makes a batch of calculations atomic.

Application query use cases return typed Domain values in typed response DTOs for one security/date, a date range, snapshots eligible at a cutoff, and snapshot provenance. They do not expose ORM models.

## Known limitations

The source must already provide compatible standardized item codes and discrete quarterly facts or direct FY/TTM values. Cumulative H1/9M-to-quarter derivation, TTM estimates from fewer than four quarters, currency conversion, corporate-action share adjustment, diluted-share policy, preferred-share/minority-interest adjustments to enterprise value, lease liabilities, and alternate cash/debt definitions are not implemented. Source-specific accounting interpretation remains outside this foundation.
