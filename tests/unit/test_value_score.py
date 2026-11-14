from datetime import UTC, datetime
from decimal import Decimal

import pytest

from cyclescope.domain.entities.daily_price import DailyPrice
from cyclescope.domain.entities.value_score import (
    ValueScoreComponent,
    ValueScoreComponentCode,
    ValueScoreComponentStatus,
    ValueScoreConfig,
    ValueScoreMeasure,
)
from cyclescope.domain.exceptions import DomainValidationError
from cyclescope.domain.services.value_score import (
    finalize_value_score,
    percentile_score,
    score_debt_to_equity,
    score_historical_price,
    score_peer_relative,
    score_percentile_family,
)


def test_percentile_directionality_and_boundaries() -> None:
    assert percentile_score(Decimal(0)) == Decimal(100)
    assert percentile_score(Decimal(100)) == Decimal(0)
    with pytest.raises(DomainValidationError):
        percentile_score(Decimal(101))


def test_price_rank_uses_selected_adjusted_price_series_and_pit_cutoff() -> None:
    cutoff = datetime(2026, 1, 30, tzinfo=UTC)
    rows = tuple(
        DailyPrice(
            security_id=1,
            observation_date=datetime(2026, 1, day, tzinfo=UTC).date(),
            open=Decimal(day),
            high=Decimal(day),
            low=Decimal(day),
            close=Decimal(day),
            adjusted_close=Decimal(day * 2),
            volume=100,
            currency="JPY",
            source_id=2,
            publication_date=None,
            available_at=(
                datetime(2026, 2, 1, tzinfo=UTC)
                if day == 30
                else datetime(2026, 1, day, tzinfo=UTC)
            ),
            collected_at=datetime(2026, 1, day, tzinfo=UTC),
            revision_number=1,
            created_at=datetime(2026, 1, day, tzinfo=UTC),
            updated_at=datetime(2026, 1, day, tzinfo=UTC),
            id=day,
        )
        for day in range(1, 31)
    )
    result = score_historical_price(
        rows,
        as_of=cutoff,
        selected_source_id=2,
        use_adjusted_close=True,
        minimum_observations=20,
    )
    assert result.score == Decimal(0)
    assert all(ref.observation_date.day < 30 for ref in result.input_references)


def test_default_weights_are_complete_and_versioned() -> None:
    config = ValueScoreConfig()
    assert sum(config.weight_map.values()) == Decimal(1)
    assert config.snapshot()["version"] == 1
    with pytest.raises(DomainValidationError):
        ValueScoreConfig(weights=config.weights[:-1])


@pytest.mark.parametrize(
    "weights",
    [
        (
            ValueScoreConfig().weights[0],
            (ValueScoreComponentCode.HISTORICAL_PRICE, Decimal("0.20")),
            *ValueScoreConfig().weights[2:],
        ),
        (
            ("UNKNOWN", Decimal("0.15")),
            *ValueScoreConfig().weights[1:],
        ),
        tuple(
            (
                code,
                Decimal("-0.1")
                if code == ValueScoreComponentCode.HISTORICAL_PRICE
                else weight,
            )
            for code, weight in ValueScoreConfig().weights
        ),
        tuple(
            (
                code,
                Decimal("NaN")
                if code == ValueScoreComponentCode.HISTORICAL_PRICE
                else weight,
            )
            for code, weight in ValueScoreConfig().weights
        ),
    ],
)
def test_invalid_component_weights_are_rejected(weights) -> None:
    with pytest.raises(DomainValidationError):
        ValueScoreConfig(weights=weights)


def test_missing_submetrics_are_not_zero_filled() -> None:
    result = score_percentile_family(
        ValueScoreComponentCode.HISTORICAL_VALUATION,
        (("PER", Decimal(20), None), ("PBR", None, "negative equity")),
        (),
    )
    assert result.status == ValueScoreComponentStatus.PARTIAL
    assert result.score == Decimal(80)
    assert result.measures[1].score is None
    assert result.measures[1].reason == "negative equity"


@pytest.mark.parametrize(
    ("equity", "expected_status"),
    [
        (Decimal(100), ValueScoreComponentStatus.AVAILABLE),
        (Decimal(0), ValueScoreComponentStatus.INVALID_INPUT),
        (Decimal(-1), ValueScoreComponentStatus.INVALID_INPUT),
    ],
)
def test_balance_sheet_direction_and_negative_equity(equity, expected_status) -> None:
    result = score_debt_to_equity(
        short_term_debt=Decimal(20),
        long_term_debt=Decimal(30),
        total_equity=equity,
        maximum_ratio=Decimal(2),
        references=(),
    )
    assert result.status == expected_status
    if equity > 0:
        assert result.measures[0].score == Decimal("75.0000000")


def test_missing_balance_inputs_are_unavailable_not_zero() -> None:
    result = score_debt_to_equity(
        short_term_debt=None,
        long_term_debt=Decimal(0),
        total_equity=Decimal(10),
        maximum_ratio=Decimal(2),
        references=(),
    )
    assert result.status == ValueScoreComponentStatus.UNAVAILABLE
    assert result.score is None


def test_peer_median_relative_score_and_sample_provenance() -> None:
    result = score_peer_relative(
        (("PER", Decimal(10), Decimal(10)),), peer_security_ids=(2, 3, 4), references=()
    )
    assert result.score == Decimal("50.0000000")
    assert result.peer_security_ids == (2, 3, 4)


def test_weight_redistribution_and_coverage_gate() -> None:
    available = ValueScoreComponent(
        ValueScoreComponentCode.HISTORICAL_PRICE,
        ValueScoreComponentStatus.AVAILABLE,
        Decimal(80),
        None,
        measures=(ValueScoreMeasure("price", Decimal(20), "PERCENTILE", Decimal(80)),),
    )
    unavailable = ValueScoreComponent(
        ValueScoreComponentCode.HISTORICAL_VALUATION,
        ValueScoreComponentStatus.UNAVAILABLE,
        None,
        "no data",
    )
    # All six components must be represented exactly once by the domain result.
    codes = {
        ValueScoreComponentCode.HISTORICAL_PRICE,
        ValueScoreComponentCode.HISTORICAL_VALUATION,
        ValueScoreComponentCode.NORMALIZED_EARNINGS_VALUATION,
        ValueScoreComponentCode.CASH_FLOW_VALUATION,
        ValueScoreComponentCode.BALANCE_SHEET,
        ValueScoreComponentCode.RELATIVE_VALUATION,
    }
    components = [available, unavailable]
    for code in codes - {available.code, unavailable.code}:
        components.append(
            ValueScoreComponent(
                code, ValueScoreComponentStatus.UNAVAILABLE, None, "no data"
            )
        )
    result = finalize_value_score(
        security_id=1,
        company_id=1,
        as_of=datetime(2026, 1, 1, tzinfo=UTC),
        components=tuple(components),
        config=ValueScoreConfig(),
    )
    assert result.score is None
    assert result.coverage == Decimal("0.15")
    assert all(item.effective_weight == 0 for item in result.components)


def test_sufficient_partial_coverage_redistributes_and_classifies_confidence() -> None:
    components = []
    for index, code in enumerate(ValueScoreComponentCode):
        if index < 5:
            components.append(
                ValueScoreComponent(
                    code,
                    ValueScoreComponentStatus.AVAILABLE,
                    Decimal(60),
                    None,
                    measures=(
                        ValueScoreMeasure(
                            f"metric-{index}", Decimal(1), "RATIO", Decimal(60)
                        ),
                    ),
                )
            )
        else:
            components.append(
                ValueScoreComponent(
                    code, ValueScoreComponentStatus.UNAVAILABLE, None, "missing"
                )
            )
    result = finalize_value_score(
        security_id=1,
        company_id=1,
        as_of=datetime(2026, 1, 1, tzinfo=UTC),
        components=tuple(components),
        config=ValueScoreConfig(),
    )
    assert result.coverage == Decimal("0.90")
    assert result.status.value == "PARTIAL"
    assert result.confidence.value == "HIGH"
    assert result.score == Decimal(60)
    assert sum(item.effective_weight for item in result.components) == Decimal(1)
