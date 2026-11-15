# Inventory Engine v1

Sprint 14 adds point-in-time, company-level analysis of standardized annual FY
inventory and cost-of-goods-sold (COGS) statements. It does not infer industry
supply-demand conditions or turn inventory growth into an excess-inventory
signal.

## Inputs and compatibility

The engine reuses `GetFinancialStatements`, `FinancialItemRepository`, and the
existing `INVENTORIES` and `COST_OF_GOODS_SOLD` FinancialItem codes. Only FY
statements are used. A source must be explicitly selected when more than one
eligible source exists. All selected historical statements must share source,
accounting standard, consolidation scope, and reporting currency. For COGS to
be used with inventory in a year, the two FY statements must also have the same
fiscal year and period end. A period-end mismatch leaves turnover unavailable
with an explicit reason. Interim data is never annualized. Currency conversion
is not supported. Company-level amounts are not multiplied by industry revenue
exposure and are not represented as segment inventory.

Initialization idempotently inserts these two standard FinancialItem masters
when absent. Existing item labels, active state, IDs, and source mappings are
left untouched.

## Formulas

For fiscal year `Y`:

- Closing inventory is the `INVENTORIES` FY balance at the period end.
- Opening inventory is closing inventory from the immediately preceding FY.
  A missing year is not bridged or filled with zero; overlapping FY intervals
  are incompatible and do not supply an opening balance.
- YoY absolute change = closing inventory minus opening inventory.
- YoY growth = absolute change divided by opening inventory; it is unavailable
  when opening inventory is zero or negative.
- Average inventory = (opening inventory + closing inventory) / 2.
- Inventory turnover = annual FY COGS / average inventory. COGS and average
  inventory must both be positive.
- DIO = configured annual day basis / inventory turnover. Version 1 fixes the
  basis at 365 days and records it in `config_snapshot`.

Negative inventory balances are treated as invalid, never as valid negatives.
Negative or zero COGS is unavailable. Calculations use `Decimal` with an
expanded local precision; persisted values use the financial store's
`NUMERIC(38, 12)` scale.

## Trend and availability

Trend is descriptive and uses closing balances only. Configurable
`stable_growth_threshold` and `minimum_trend_observations` are versioned in the
configuration snapshot. The default requires at least three consecutive FY
observations. All observed annual growth rates above the threshold classify as
`INCREASING`; all below its negative as `DECREASING`; rates within the threshold
as `STABLE`; mixed directions or magnitudes classify as `VOLATILE`. Missing FYs,
invalid balances, zero prior balances, or too few contiguous observations yield
`UNKNOWN`. No classification alone means excess inventory or demand weakness.

Each output stores availability across seven numeric metrics (closing,
opening, average, absolute change, growth, turnover, and DIO) plus the trend
classification. Coverage is the number available divided by eight. `AVAILABLE`
means all eight are available; `PARTIAL` means at least one is available;
`INSUFFICIENT_DATA` means none is present. `UNKNOWN` trend lowers coverage and
has an explicit reason. Confidence is `HIGH` at coverage >= 0.85, `MEDIUM` at
>= 0.60, `LOW` above zero, otherwise `INSUFFICIENT`. Unavailable metrics retain
explicit reasons; missing values are never set to zero.

If no PIT-visible annual FY statement exists, the application response is
`UNAVAILABLE` with a reason and does not persist an invented fiscal-year row.

## Point-in-time and provenance

`as_of` must be timezone-aware and is normalized to UTC. Existing financial
query behavior filters `available_at <= as_of` before choosing the highest
visible revision for each source and reporting period. Period end must not be
after the UTC cutoff date. `collected_at` does not determine historical
visibility. Each snapshot retains the exact statement and line IDs, source,
revision, fiscal period, and availability timestamp used for the year, prior
year opening balance, and trend observations. Future revisions cannot replace
visible historical inputs.

## Persistence and limitations

Migration `0018_inventory_snapshots` adds an append-only snapshot table. Every
calculation appends one snapshot per PIT-visible FY observed; repeat runs do not
update prior rows. The repository only creates and reads; the Application does
not commit, so callers own the transaction and can roll back all generated
snapshots. The migration does not alter existing tables or financial data.

Current limitations: only reported company-level FY balances and COGS are
supported; there is no segment inventory, inventory-days sector benchmark,
industry inventory dataset, supply-demand signal, or automated source
reconciliation. Accounting standards and consolidation scopes are required to
match exactly. Trend thresholds are starting defaults and require domain
calibration before they could support a decision signal.
