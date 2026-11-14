from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from cyclescope.application.use_cases.valuation_inputs import BuildValuationInputs
from cyclescope.domain.entities.financial_data import FinancialItem
from cyclescope.domain.entities.valuation import (
    ValuationInputReference,
    ValuationInputs,
    ValuationMetricCode,
    ValuationResultStatus,
)
from cyclescope.domain.exceptions import DomainValidationError
from cyclescope.domain.services.valuation import (
    calculate_metric,
    default_metric_definitions,
)
from cyclescope.domain.value_objects.financial_data import StatementType, UnitDimension

NOW = datetime(2026, 5, 15, 16, tzinfo=UTC)


def _definition(code: ValuationMetricCode):
    return next(x for x in default_metric_definitions() if x.metric_code == code)


def test_initial_metric_master_defines_all_requested_codes():
    assert {x.metric_code for x in default_metric_definitions()} == set(
        ValuationMetricCode
    )
    assert len({x.calculation_method for x in default_metric_definitions()}) == 8


def test_per_prefers_reported_eps_and_preserves_pit_provenance():
    inputs = ValuationInputs(
        security_id=1,
        observation_date=date(2026, 5, 15),
        as_of=NOW,
        currency="JPY",
        closing_price=Decimal("1500"),
        reported_eps=Decimal("100"),
        net_income=Decimal("999"),
        weighted_average_shares=Decimal("1"),
        price_source_id=2,
        price_revision_number=3,
        price_observation_id=42,
        financial_statement_ids=(8,),
        financial_source_ids=(4,),
        input_references=(
            ValuationInputReference(
                "DAILY_PRICE", 42, 2, 3, NOW, observation_date=date(2026, 5, 15)
            ),
            ValuationInputReference(
                "FINANCIAL_LINE",
                8,
                4,
                1,
                NOW,
                parent_record_id=8,
                financial_item_code="EPS",
                financial_period="FY",
                period_end=date(2025, 12, 31),
            ),
        ),
    )
    result = calculate_metric(_definition(ValuationMetricCode.PER), inputs)
    assert result.value == Decimal("15")
    assert result.status == ValuationResultStatus.AVAILABLE
    assert result.price_observation_id == 42
    assert result.financial_statement_ids == (8,)
    assert result.currency is None


def test_financial_metric_calculations_and_explicit_missing_inputs():
    inputs = ValuationInputs(
        security_id=1,
        observation_date=date(2026, 5, 15),
        as_of=NOW,
        currency="USD",
        closing_price=Decimal("100"),
        net_income=Decimal("20"),
        weighted_average_shares=Decimal("10"),
        total_equity=Decimal("500"),
        shares_outstanding=Decimal("10"),
        cash_and_equivalents=Decimal("50"),
        short_term_debt=Decimal("20"),
        long_term_debt=Decimal("30"),
        operating_profit=Decimal("70"),
        depreciation_amortization=Decimal("10"),
    )
    expected = {
        ValuationMetricCode.EPS: Decimal("2"),
        ValuationMetricCode.BVPS: Decimal("50"),
        ValuationMetricCode.MARKET_CAPITALIZATION: Decimal("1000"),
        ValuationMetricCode.ENTERPRISE_VALUE: Decimal("1000"),
        ValuationMetricCode.EBITDA: Decimal("80"),
        ValuationMetricCode.PER: Decimal("50"),
        ValuationMetricCode.PBR: Decimal("2"),
        ValuationMetricCode.EV_EBITDA: Decimal("12.5"),
    }
    for code, value in expected.items():
        assert calculate_metric(_definition(code), inputs).value == value
    assert (
        calculate_metric(
            _definition(ValuationMetricCode.EPS), inputs
        ).eps_calculation_method
        == "DERIVED_NET_INCOME_OVER_WEIGHTED_SHARES"
    )

    missing = calculate_metric(
        _definition(ValuationMetricCode.MARKET_CAPITALIZATION),
        ValuationInputs(
            security_id=1,
            observation_date=date(2026, 5, 15),
            as_of=NOW,
            currency="USD",
            closing_price=Decimal("100"),
        ),
    )
    assert missing.value is None
    assert missing.status == ValuationResultStatus.INSUFFICIENT_DATA
    assert missing.unavailable_inputs == ("shares_outstanding",)


@pytest.mark.parametrize("shares", [Decimal("0"), Decimal("-1")])
@pytest.mark.parametrize("cash", [Decimal("0"), Decimal("-10")])
def test_enterprise_value_validates_named_shares_and_allows_signed_cash(shares, cash):
    inputs = ValuationInputs(
        security_id=1,
        observation_date=date(2026, 5, 15),
        as_of=NOW,
        currency="USD",
        closing_price=Decimal("10"),
        shares_outstanding=shares,
        short_term_debt=Decimal("3"),
        long_term_debt=Decimal("4"),
        cash_and_equivalents=cash,
        operating_profit=Decimal("10"),
        depreciation_amortization=Decimal("1"),
    )
    result = calculate_metric(_definition(ValuationMetricCode.ENTERPRISE_VALUE), inputs)
    ratio = calculate_metric(_definition(ValuationMetricCode.EV_EBITDA), inputs)
    assert result.status == ValuationResultStatus.INVALID_INPUT
    assert result.unavailable_inputs == ("shares_outstanding must be positive.",)
    assert ratio.status == ValuationResultStatus.INVALID_INPUT
    conflicting = calculate_metric(
        _definition(ValuationMetricCode.EV_EBITDA),
        replace(
            inputs,
            operating_profit=Decimal("-20"),
            depreciation_amortization=Decimal("5"),
        ),
    )
    assert conflicting.status == ValuationResultStatus.INVALID_INPUT


@pytest.mark.parametrize(
    ("cash", "expected"),
    [(Decimal("0"), Decimal("107")), (Decimal("-10"), Decimal("117"))],
)
def test_enterprise_value_accepts_zero_and_negative_cash(cash, expected):
    inputs = ValuationInputs(
        security_id=1,
        observation_date=date(2026, 5, 15),
        as_of=NOW,
        currency="USD",
        closing_price=Decimal("10"),
        shares_outstanding=Decimal("10"),
        short_term_debt=Decimal("3"),
        long_term_debt=Decimal("4"),
        cash_and_equivalents=cash,
    )
    result = calculate_metric(_definition(ValuationMetricCode.ENTERPRISE_VALUE), inputs)
    assert result.status == ValuationResultStatus.AVAILABLE
    assert result.value == expected


@pytest.mark.parametrize(
    ("code", "changes"),
    [
        (ValuationMetricCode.PER, {"reported_eps": Decimal("0")}),
        (ValuationMetricCode.PBR, {"total_equity": Decimal("0")}),
        (ValuationMetricCode.PBR, {"total_equity": Decimal("-500")}),
    ],
)
def test_conventional_ratio_with_nonpositive_denominator_is_not_applicable(
    code, changes
):
    values = dict(
        security_id=1,
        observation_date=date(2026, 5, 15),
        as_of=NOW,
        currency="USD",
        closing_price=Decimal("100"),
        reported_eps=Decimal("2"),
        total_equity=Decimal("500"),
        shares_outstanding=Decimal("10"),
    )
    values.update(changes)
    result = calculate_metric(_definition(code), ValuationInputs(**values))
    assert result.status == ValuationResultStatus.NOT_APPLICABLE
    assert result.value is None
    assert result.unavailable_reason


def test_zero_ebitda_is_not_applicable_and_negative_earnings_never_make_positive_per():
    base = dict(
        security_id=1,
        observation_date=date(2026, 5, 15),
        as_of=NOW,
        currency="USD",
        closing_price=Decimal("100"),
        total_equity=Decimal("500"),
        shares_outstanding=Decimal("10"),
        short_term_debt=Decimal("0"),
        long_term_debt=Decimal("0"),
        cash_and_equivalents=Decimal("0"),
        operating_profit=Decimal("0"),
        depreciation_amortization=Decimal("0"),
    )
    zero_ebitda = calculate_metric(
        _definition(ValuationMetricCode.EV_EBITDA), ValuationInputs(**base)
    )
    assert zero_ebitda.status == ValuationResultStatus.NOT_APPLICABLE
    assert zero_ebitda.value is None

    loss = calculate_metric(
        _definition(ValuationMetricCode.PER),
        ValuationInputs(**(base | {"reported_eps": Decimal("-2")})),
    )
    assert loss.status == ValuationResultStatus.NOT_APPLICABLE
    assert loss.value is None
    assert loss.unavailable_reason
    assert dict(loss.input_snapshot)["reported_eps"] == Decimal("-2")

    negative_ebitda = calculate_metric(
        _definition(ValuationMetricCode.EV_EBITDA),
        ValuationInputs(
            **(
                base
                | {
                    "operating_profit": Decimal("-20"),
                    "depreciation_amortization": Decimal("5"),
                }
            )
        ),
    )
    assert negative_ebitda.status == ValuationResultStatus.NOT_APPLICABLE
    assert negative_ebitda.value is None


def test_invalid_market_currency_and_future_input_availability_are_rejected():
    with pytest.raises(DomainValidationError, match="currency"):
        ValuationInputs(
            security_id=1,
            observation_date=date(2026, 5, 15),
            as_of=NOW,
            currency="jpy",
        )
    bad_eps_item = FinancialItem(
        "EPS",
        "EPS",
        StatementType.PL,
        "income",
        UnitDimension.CURRENCY_AMOUNT,
    )
    with pytest.raises(DomainValidationError, match="incompatible unit dimension"):
        BuildValuationInputs._validate_item_unit(bad_eps_item, "CURRENCY", "USD")


def test_decimal_ratio_uses_explicit_12_place_rounding():
    result = calculate_metric(
        _definition(ValuationMetricCode.PER),
        ValuationInputs(
            security_id=1,
            observation_date=date(2026, 5, 15),
            as_of=NOW,
            currency="USD",
            closing_price=Decimal("1"),
            reported_eps=Decimal("3"),
        ),
    )
    assert result.value == Decimal("0.333333333333")
    with pytest.raises(DomainValidationError, match="Price input"):
        ValuationInputs(
            security_id=1,
            observation_date=date(2026, 5, 15),
            as_of=NOW,
            currency="JPY",
            price_available_at=NOW.replace(hour=17),
        )
    with pytest.raises(DomainValidationError, match="NUMERIC"):
        calculate_metric(
            _definition(ValuationMetricCode.MARKET_CAPITALIZATION),
            ValuationInputs(
                security_id=1,
                observation_date=date(2026, 5, 15),
                as_of=NOW,
                currency="USD",
                closing_price=Decimal("1E+20"),
                shares_outstanding=Decimal("1E+10"),
            ),
        )


def test_input_reference_preserves_publication_and_availability_instants():
    reference = ValuationInputReference(
        record_type="FINANCIAL_LINE",
        record_id=3,
        parent_record_id=2,
        source_id=1,
        revision_number=1,
        available_at=NOW,
        financial_item_code="NET_INCOME",
        financial_period="FY",
        period_start=date(2025, 1, 1),
        period_end=date(2025, 12, 31),
        publication_date=date(2026, 2, 1),
        publication_datetime=NOW,
    )
    assert reference.publication_date == date(2026, 2, 1)
    assert reference.available_at == NOW


def test_metric_provenance_only_contains_actual_dependencies():
    refs = (
        ValuationInputReference(
            "DAILY_PRICE", 90, 2, 1, NOW, observation_date=date(2026, 5, 15)
        ),
        *(
            ValuationInputReference(
                "FINANCIAL_LINE",
                index,
                3,
                1,
                NOW,
                parent_record_id=100 + index,
                financial_item_code=code,
                financial_period="FY",
                period_end=date(2025, 12, 31),
            )
            for index, code in enumerate(
                (
                    "EPS",
                    "NET_INCOME",
                    "WEIGHTED_AVERAGE_SHARES",
                    "TOTAL_EQUITY",
                    "SHARES_OUTSTANDING",
                    "CASH_AND_CASH_EQUIVALENTS",
                    "SHORT_TERM_DEBT",
                    "LONG_TERM_DEBT",
                    "OPERATING_PROFIT",
                    "DEPRECIATION_AMORTIZATION",
                    "UNRELATED_LINE",
                ),
                1,
            )
        ),
    )
    inputs = ValuationInputs(
        security_id=1,
        observation_date=date(2026, 5, 15),
        as_of=NOW,
        currency="USD",
        closing_price=Decimal("100"),
        reported_eps=Decimal("5"),
        net_income=Decimal("100"),
        weighted_average_shares=Decimal("20"),
        total_equity=Decimal("500"),
        shares_outstanding=Decimal("20"),
        cash_and_equivalents=Decimal("10"),
        short_term_debt=Decimal("5"),
        long_term_debt=Decimal("15"),
        operating_profit=Decimal("80"),
        depreciation_amortization=Decimal("10"),
        price_observation_id=90,
        price_source_id=2,
        price_revision_number=1,
        price_available_at=NOW,
        input_references=refs,
    )
    expected = {
        ValuationMetricCode.PER: {"EPS"},
        ValuationMetricCode.PBR: {"TOTAL_EQUITY", "SHARES_OUTSTANDING"},
        ValuationMetricCode.MARKET_CAPITALIZATION: {"SHARES_OUTSTANDING"},
        ValuationMetricCode.ENTERPRISE_VALUE: {
            "SHARES_OUTSTANDING",
            "SHORT_TERM_DEBT",
            "LONG_TERM_DEBT",
            "CASH_AND_CASH_EQUIVALENTS",
        },
        ValuationMetricCode.EBITDA: {"OPERATING_PROFIT", "DEPRECIATION_AMORTIZATION"},
        ValuationMetricCode.EV_EBITDA: {
            "SHARES_OUTSTANDING",
            "SHORT_TERM_DEBT",
            "LONG_TERM_DEBT",
            "CASH_AND_CASH_EQUIVALENTS",
            "OPERATING_PROFIT",
            "DEPRECIATION_AMORTIZATION",
        },
    }
    for code, financial_codes in expected.items():
        result = calculate_metric(_definition(code), inputs)
        recorded = {
            ref.financial_item_code
            for ref in result.input_references
            if ref.financial_item_code is not None
        }
        assert recorded == financial_codes
        assert "UNRELATED_LINE" not in recorded
        assert any(
            ref.record_type == "DAILY_PRICE" for ref in result.input_references
        ) == (code != ValuationMetricCode.EBITDA)
    derived = calculate_metric(
        _definition(ValuationMetricCode.EPS),
        replace(inputs, reported_eps=None),
    )
    assert {ref.financial_item_code for ref in derived.input_references} == {
        "NET_INCOME",
        "WEIGHTED_AVERAGE_SHARES",
    }
    derived_per = calculate_metric(
        _definition(ValuationMetricCode.PER), replace(inputs, reported_eps=None)
    )
    assert {
        ref.financial_item_code
        for ref in derived_per.input_references
        if ref.financial_item_code is not None
    } == {"NET_INCOME", "WEIGHTED_AVERAGE_SHARES"}


def test_valuation_inputs_reject_observation_after_cutoff():
    with pytest.raises(DomainValidationError, match="Observation date"):
        ValuationInputs(
            security_id=1,
            observation_date=date(2026, 5, 16),
            as_of=NOW,
            currency="JPY",
        )
