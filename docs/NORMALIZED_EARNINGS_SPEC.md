# Normalized Earnings Foundation

## Scope and boundaries

Sprint 10 adds a point-in-time historical earnings analyzer and an append-only result store. It does not implement Value Score, Cycle Score, opportunity ranking, screening, or backtesting. `CalculateNormalizedEarnings` reuses `GetFinancialStatements` and `FinancialItemRepository`; normalized PER and EV/EBITDA delegate arithmetic and applicability rules to the existing valuation calculator. The caller owns the transaction.

The analyzer supports annual FY observations of `OPERATING_PROFIT`, `NET_INCOME`, and reported `EPS`. EBITDA is derived per fiscal year as operating profit plus depreciation and amortization when both lines exist. EPS is not synthesized when the annual EPS item is missing. No financial item taxonomy is duplicated.

## Period selection and point-in-time rules

Each request requires a timezone-aware `as_of`, a 5, 7, or 10 fiscal-year window, an explicit normalization method, and an optional source selection. Statement reads reuse `GetFinancialStatements`, which filters `available_at <= as_of` before choosing the highest visible revision per source and reporting period. `collected_at` does not determine visibility. Statements whose fiscal period ends after the UTC `as_of` date are excluded. Ties resolve by revision, availability timestamp, then statement ID.

Only annual `FY` statements are included. The requested window ends at the latest eligible fiscal-year label. If fewer years of history exist, the effective window is shortened to the available fiscal-year span; missing fiscal labels within that span remain in the coverage denominator. Multiple incompatible FY statements for one fiscal year are rejected instead of selected arbitrarily. Multiple eligible sources require an explicit source ID. Different accounting standards, consolidation scopes, or reporting currencies are not mixed.

## Statistics and normalization

For valid annual observations in the selected window, the result reports arithmetic mean, median, minimum, maximum, population standard deviation, number of valid years, loss-making years, and coverage. Negative values remain in every statistic; zero is not counted as a loss. Coverage is `valid_fiscal_years / effective_window_years`. Derived statistics are rounded to 12 fractional places using Decimal `ROUND_HALF_EVEN`; source fiscal-year values remain available in the result trace.

The caller explicitly selects `ARITHMETIC_MEAN` or `MEDIAN`. No fallback between methods occurs. At least three valid annual observations are required for an available normalized value; otherwise status is `INSUFFICIENT_DATA`, the normalized value is null, and a specific status reason is stored while any computable descriptive statistics remain available. Weighted averages are not offered because there is no agreed weighting policy in the available source data.

Confidence is separate from normalized earnings: `HIGH` requires at least five valid years and coverage >= 0.8; `MEDIUM` requires at least three years and coverage >= 0.6; one or more observations below those levels are `LOW`; no observations are `INSUFFICIENT`. It measures history coverage, not source reliability or accounting quality.

## Cycle extremes and adjustments

The highest and lowest reported earnings years within the eligible historical window are stored as peak and trough candidates. Ties select the later fiscal-year label. These are historical earnings extrema only, not proof of an industry-cycle phase. Since only records visible by `as_of` enter the window, later earnings cannot affect an earlier calculation.

Exceptional items, discontinued operations, and material accounting-policy changes are not automatically removed or adjusted. The current financial data contract does not supply reliable normalized adjustment facts or consistent identification metadata for those cases. Reported figures are preserved and the assumption is attached to every result. Direct annual EPS is used when present; the engine does not add quarterly EPS or infer annual EPS from incomplete share-count data.

## Normalized valuation

If current `ValuationInputs` for the same security and cutoff are supplied, normalized PER is calculated as current eligible closing price divided by normalized EPS. Normalized EV/EBITDA uses the current eligible enterprise value from the existing EV/EBITDA formula and normalized historical EBITDA as its denominator. Existing point-in-time, missing-input, Decimal, and validity rules are reused. Non-positive normalized EPS or EBITDA yields `NOT_APPLICABLE`; unavailable current market or balance inputs yield an explicit insufficient-data status. No missing value is replaced with zero. Normalized valuation status/value are separate from the earnings result/status/value.

## Persistence and provenance

Migration `0013_normalized_earnings` adds `normalized_earnings_results` and `normalized_earnings_input_refs`. Each calculation stores company and optional security, metric, method, requested/effective windows, cutoff, statistics, coverage, confidence, fiscal-year values, extrema, assumptions, calculation version, and optional normalized valuation result. Input rows are FK-backed to source statements/lines or the exact daily-price row and retain source, revision, availability, and period metadata. Recalculation inserts a new result identity; neither prior results nor their references are updated or deleted. A caller transaction controls atomicity and rollback.

## Known limitations

Only standardized annual FY facts are analyzed. Annual EPS requires a reported EPS line; interim-to-annual derivation, diluted EPS policy, missing item mapping, currency conversion, restatement-policy customization, exception-item adjustments, discontinued-operation identification, accounting-change adjustment, quality-report integration, security-class-specific share selection, and corporate-action handling remain future work. Confidence currently measures history quantity and coverage only. Peak/trough candidates are deliberately simple historical extrema.
