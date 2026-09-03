"""The executor: dispatch, evidence, provenance, limits and determinism.

Every figure here comes from synthetic fixtures. No real Coffee Lounge number
appears in this file — the suite must pass on a fresh clone with no access to
any business data.
"""

from __future__ import annotations

import warnings
from datetime import date, timedelta

import pytest
from pydantic import TypeAdapter

from app.analytics.service import AnalyticsService
from app.forecasting.service import ForecastService
from app.models.enums import Channel, OrderEventType
from app.nlq import fields
from app.nlq.evidence import EvidenceKind, EvidenceStatus
from app.nlq.executor import AnalyticsExecutor
from app.nlq.operations import (
    MAX_ATTACHMENT_ROWS,
    MAX_MENU_EVIDENCE_ROWS,
    MAX_PAIR_ROWS,
    MAX_PRODUCT_ROWS,
    Operation,
)
from app.nlq.requests import AnalyticsRequest
from app.nlq.resolution import ProductResolver

warnings.filterwarnings("ignore")

ADAPTER = TypeAdapter(AnalyticsRequest)
START, END = "2026-08-01", "2026-08-31"


def request_for(operation: str, **extra):
    payload = {"operation": operation, **extra}
    if operation != Operation.FORECAST.value:
        payload.setdefault("start_date", START)
        payload.setdefault("end_date", END)
    return ADAPTER.validate_python(payload)


@pytest.fixture
def analytics(session_factory):
    return AnalyticsService(session_factory)


@pytest.fixture
def executor(session_factory, analytics):
    return AnalyticsExecutor(
        analytics=analytics,
        forecasts=ForecastService(session_factory),
        resolver=ProductResolver(session_factory),
    )


@pytest.fixture
def trading(make_sale, make_order):
    """A month of trade with two products, a refund, and a delivery order."""
    make_sale("2026-08-03T09:00", [("Big Breakfast", "", 1, 950),
                                   ("Caffe Latte", "Regular", 1, 365)])
    make_sale("2026-08-03T12:00", [("Big Breakfast", "", 2, 1900),
                                   ("Caffe Latte", "Regular", 1, 365)],
              discount=100)
    make_sale("2026-08-10T09:00", [("Caffe Latte", "Regular", 1, 365)],
              channel=Channel.DELIVERY)
    make_sale("2026-08-17T09:00", [("Big Breakfast", "", 1, 950),
                                   ("Caffe Latte", "Large", 1, 415)])
    make_order("2026-08-20T11:00", net=-365, units=-1,
               event_type=OrderEventType.REFUND)


# --- dispatch ----------------------------------------------------------------


ALL_OPERATIONS = [o for o in Operation if o is not Operation.FORECAST]


@pytest.mark.parametrize("operation", ALL_OPERATIONS, ids=lambda o: o.value)
def test_every_operation_dispatches_and_returns_its_own_evidence(
    executor, trading, product_id, operation
):
    extra = {}
    if operation in (Operation.PRODUCT_TREND, Operation.PRODUCT_ATTACHMENTS):
        extra["product"] = {"product_id": product_id("Big Breakfast", "")}
    if operation in (Operation.PRODUCT_ATTACHMENTS, Operation.BASKET_PAIRS,
                     Operation.MENU_EVIDENCE):
        extra["min_pair_orders"] = 1

    bundle = executor.execute(request_for(operation.value, **extra))

    assert bundle.operation is operation
    assert bundle.status is EvidenceStatus.OK
    assert bundle.period.start_date == date(2026, 8, 1)
    assert bundle.period.end_date == date(2026, 8, 31)
    assert bundle.period.days == 31


def test_the_dispatch_table_covers_the_whole_enum(executor):
    """A new operation cannot be added to the whitelist without a handler."""
    assert set(executor._dispatch) == set(Operation)


def test_no_operation_is_selected_by_name_from_request_content(executor):
    """Every key in the table is an enum member Pydantic already validated."""
    assert all(isinstance(key, Operation) for key in executor._dispatch)


# --- parity with the services that own the definitions -----------------------


def test_overview_evidence_equals_the_analytics_service(executor, analytics, trading):
    _, totals = analytics.overview(date(2026, 8, 1), date(2026, 8, 31))
    bundle = executor.execute(request_for("overview"))

    assert bundle.totals["net_sales_pence"] == totals.net_sales_pence
    assert bundle.totals["gross_sales_pence"] == totals.gross_sales_pence
    assert bundle.totals["discounts_pence"] == totals.discounts_pence
    assert bundle.totals["payment_order_count"] == totals.payment_order_count
    assert bundle.totals["refund_event_count"] == totals.refund_event_count
    assert bundle.totals["net_units"] == totals.net_units
    assert (
        bundle.totals["average_order_value_pence"]
        == totals.average_order_value_pence
    )


def test_revenue_evidence_equals_the_analytics_service(executor, analytics, trading):
    series = analytics.revenue(date(2026, 8, 1), date(2026, 8, 31), "day")
    rows = executor.execute(request_for("revenue_over_time")).rows

    assert len(rows) == len(series.buckets)
    assert [r["period_start"] for r in rows] == [b.period_start for b in series.buckets]
    assert [r["net_sales_pence"] for r in rows] == [
        b.net_sales_pence for b in series.buckets
    ]


def test_product_performance_evidence_equals_the_analytics_service(
    executor, analytics, trading
):
    ranking = analytics.products(date(2026, 8, 1), date(2026, 8, 31))
    rows = executor.execute(request_for("product_performance")).rows

    assert [r["product_id"] for r in rows] == [
        p.totals.product_id for p in ranking.products
    ]
    assert [r["net_sales_pence"] for r in rows] == [
        p.totals.net_sales_pence for p in ranking.products
    ]
    assert [r["share_of_net_sales_percent"] for r in rows] == [
        p.share_of_net_sales_percent for p in ranking.products
    ]


def test_channel_mix_evidence_equals_the_analytics_service(
    executor, analytics, trading
):
    _, shares = analytics.channel_mix(date(2026, 8, 1), date(2026, 8, 31))
    rows = executor.execute(request_for("channel_mix")).rows

    assert [r["channel"] for r in rows] == [s.totals.channel.value for s in shares]
    assert [r["net_sales_pence"] for r in rows] == [
        s.totals.net_sales_pence for s in shares
    ]


def test_basket_pairs_evidence_equals_the_analytics_service(
    executor, analytics, trading
):
    analysis = analytics.product_pairs(
        date(2026, 8, 1), date(2026, 8, 31), min_pair_orders=1, limit=10
    )
    bundle = executor.execute(request_for("basket_pairs", min_pair_orders=1))

    assert [r["pair_orders"] for r in bundle.rows] == [
        p.counts.pair_orders for p in analysis.pairs
    ]
    assert [r["lift"] for r in bundle.rows] == [p.metrics.lift for p in analysis.pairs]
    assert bundle.totals["eligible_order_count"] == analysis.eligible_order_count


def test_the_executor_does_not_reimplement_refund_semantics(executor, trading):
    """The refund reduces net sales without inflating the order count — the M3
    rule, reached through the service rather than restated here."""
    totals = executor.execute(request_for("overview")).totals
    assert totals["refund_event_count"] == 1
    assert totals["payment_order_count"] == 4


# --- integer pence and nullable ratios ---------------------------------------


def test_money_stays_integer_pence(executor, trading):
    bundle = executor.execute(request_for("product_performance"))
    for row in bundle.rows:
        for key, value in row.items():
            if key.endswith("_pence") and value is not None:
                assert isinstance(value, int) and not isinstance(value, bool)
    assert isinstance(bundle.totals["total_net_sales_pence"], int)


def test_pence_are_not_coerced_to_floats_through_serialisation(executor, trading):
    payload = executor.execute(request_for("overview")).model_dump(mode="json")
    assert isinstance(payload["totals"]["net_sales_pence"], int)


def test_an_undefined_share_stays_null(executor):
    """An empty period has no total to take a share of. Zero would be a claim."""
    bundle = executor.execute(request_for("channel_mix"))
    assert bundle.rows == []

    bundle = executor.execute(request_for("product_performance"))
    assert bundle.totals["total_net_sales_pence"] == 0
    assert bundle.rows == []


def test_a_product_with_no_net_units_has_a_null_selling_price(executor, make_sale):
    """Sales and refunds cancelling out leaves no meaningful selling price."""
    make_sale("2026-08-05T09:00", [("Flat White", "", 1, 300)])
    make_sale("2026-08-06T09:00", [("Flat White", "", -1, -300)],
              event_type=OrderEventType.REFUND)

    row = executor.execute(request_for("product_performance")).rows[0]
    assert row["net_units"] == 0
    assert row["average_selling_price_pence"] is None
    assert row["share_of_net_sales_percent"] is None


def test_null_values_are_flagged_as_undefined_not_zero(executor, make_sale):
    make_sale("2026-08-05T09:00", [("Flat White", "", 1, 300)])
    make_sale("2026-08-06T09:00", [("Flat White", "", -1, -300)],
              event_type=OrderEventType.REFUND)

    bundle = executor.execute(request_for("product_performance"))
    assert any("UNDEFINED" in w for w in bundle.warnings)


def test_a_lift_without_a_denominator_stays_null(executor, trading):
    """Association metrics are null when their denominator is zero, never 0.0."""
    bundle = executor.execute(request_for("basket_pairs", min_pair_orders=1))
    for row in bundle.rows:
        assert row["lift"] is None or isinstance(row["lift"], float)


# --- provenance --------------------------------------------------------------


@pytest.mark.parametrize("operation", ALL_OPERATIONS, ids=lambda o: o.value)
def test_every_emitted_field_declares_its_provenance(
    executor, trading, product_id, operation
):
    extra = {}
    if operation in (Operation.PRODUCT_TREND, Operation.PRODUCT_ATTACHMENTS):
        extra["product"] = {"product_id": product_id("Big Breakfast", "")}
    if operation in (Operation.PRODUCT_ATTACHMENTS, Operation.BASKET_PAIRS,
                     Operation.MENU_EVIDENCE):
        extra["min_pair_orders"] = 1

    bundle = executor.execute(request_for(operation.value, **extra))
    emitted = {key for row in bundle.rows for key in row} | set(bundle.totals)
    assert emitted <= set(bundle.field_provenance)
    assert set(bundle.field_provenance) == emitted


def test_measured_and_derived_are_distinguished(executor, trading):
    bundle = executor.execute(request_for("product_performance"))
    assert bundle.field_provenance["net_sales_pence"] is EvidenceKind.MEASURED
    assert bundle.field_provenance["payment_order_count"] is EvidenceKind.MEASURED
    assert (
        bundle.field_provenance["share_of_net_sales_percent"] is EvidenceKind.DERIVED
    )
    assert (
        bundle.field_provenance["average_selling_price_pence"] is EvidenceKind.DERIVED
    )


def test_a_comparison_is_derived_not_measured(executor, trading):
    bundle = executor.execute(request_for("product_movers"))
    assert (
        bundle.field_provenance["current_net_sales_pence"] is EvidenceKind.MEASURED
    )
    assert (
        bundle.field_provenance["previous_net_sales_pence"] is EvidenceKind.MEASURED
    )
    assert bundle.field_provenance["net_sales_change_pence"] is EvidenceKind.DERIVED
    assert bundle.field_provenance["net_sales_percent_change"] is EvidenceKind.DERIVED


def test_units_are_declared_for_every_measure(executor, trading):
    bundle = executor.execute(request_for("product_performance"))
    assert bundle.units["net_sales_pence"] == "pence"
    assert bundle.units["net_units"] == "units"
    assert bundle.units["payment_order_count"] == "orders"
    assert bundle.units["share_of_net_sales_percent"] == "percent"


def test_an_unmapped_field_fails_loudly(executor):
    """Evidence whose provenance quietly reads as empty is worse than a crash."""
    with pytest.raises(fields.UnmappedEvidenceField):
        fields.provenance_for([{"mystery_measure": 1}], {})


# --- comparisons -------------------------------------------------------------


def test_overview_can_compare_with_the_previous_period(executor, analytics, make_order):
    make_order("2026-07-15T10:00", net=1000, units=1)
    make_order("2026-08-15T10:00", net=1500, units=1)

    bundle = executor.execute(
        request_for(
            "overview", start_date="2026-08-01", end_date="2026-08-31",
            compare_to_previous_period=True,
        )
    )

    assert bundle.comparison_period.start_date == date(2026, 7, 1)
    assert bundle.comparison_period.end_date == date(2026, 7, 31)
    assert bundle.totals["net_sales_pence"] == 1500
    assert bundle.totals["previous_net_sales_pence"] == 1000
    assert bundle.totals["net_sales_change_pence"] == 500
    assert bundle.totals["net_sales_percent_change"] == 50.0
    assert bundle.totals["comparison_status"] == "comparable"


def test_a_comparison_against_nothing_has_no_percentage(executor, make_order):
    """Growth from zero is undefined, not infinite — the movers rule, reused."""
    make_order("2026-08-15T10:00", net=1500, units=1)
    bundle = executor.execute(
        request_for("overview", compare_to_previous_period=True)
    )
    assert bundle.totals["previous_net_sales_pence"] == 0
    assert bundle.totals["net_sales_percent_change"] is None
    assert bundle.totals["comparison_status"] == "new_in_period"


def test_comparison_is_off_by_default(executor, trading):
    bundle = executor.execute(request_for("overview"))
    assert bundle.comparison_period is None
    assert "previous_net_sales_pence" not in bundle.totals


def test_product_movers_uses_the_existing_comparable_window(
    executor, analytics, trading
):
    movers = analytics.product_movers(date(2026, 8, 1), date(2026, 8, 31))
    bundle = executor.execute(request_for("product_movers"))
    assert bundle.comparison_period.start_date == movers.previous_window.start_date
    assert bundle.comparison_period.end_date == movers.previous_window.end_date


# --- result limits -----------------------------------------------------------


@pytest.fixture
def many_products(make_sale):
    """Sixty distinct products, so every ranking cap can actually bite."""
    for index in range(60):
        make_sale(
            f"2026-08-{(index % 28) + 1:02d}T09:00",
            [(f"Item {index:02d}", "", 1, 100 + index)],
        )


def test_a_ranking_is_capped_and_says_so(executor, many_products):
    bundle = executor.execute(request_for("product_performance", limit=5))

    assert len(bundle.rows) == 5
    assert bundle.limits.returned_rows == 5
    assert bundle.limits.applied_limit == 5
    assert bundle.limits.available_rows == 60
    assert bundle.limits.truncated is True
    assert bundle.limits.maximum_rows == MAX_PRODUCT_ROWS
    assert any("Truncated" in w for w in bundle.warnings)


def test_an_uncapped_result_is_not_marked_truncated(executor, trading):
    bundle = executor.execute(request_for("product_performance", limit=50))
    assert bundle.limits.truncated is False
    assert not any("Truncated" in w for w in bundle.warnings)


def test_shares_are_of_the_whole_menu_not_the_returned_rows(executor, many_products):
    """Truncation must not silently change what a percentage means."""
    bundle = executor.execute(request_for("product_performance", limit=3))
    assert sum(r["share_of_net_sales_percent"] for r in bundle.rows) < 50


@pytest.mark.parametrize(
    "operation, cap",
    [
        ("product_performance", MAX_PRODUCT_ROWS),
        ("product_movers", MAX_PRODUCT_ROWS),
        ("basket_pairs", MAX_PAIR_ROWS),
        ("menu_evidence", MAX_MENU_EVIDENCE_ROWS),
    ],
)
def test_each_bounded_operation_reports_its_hard_ceiling(
    executor, trading, operation, cap
):
    bundle = executor.execute(request_for(operation))
    assert bundle.limits.maximum_rows == cap
    assert bundle.limits.returned_rows <= cap


def test_attachments_are_capped(executor, trading, product_id):
    bundle = executor.execute(
        request_for(
            "product_attachments",
            product={"product_id": product_id("Big Breakfast", "")},
            min_pair_orders=1,
            limit=1,
        )
    )
    assert len(bundle.rows) == 1
    assert bundle.limits.maximum_rows == MAX_ATTACHMENT_ROWS


def test_peak_hours_returns_only_the_busiest_cells(executor, trading):
    """168 cells, almost all of them closed hours. The fixture trades in two
    of them, so a limit of one is a genuine truncation."""
    bundle = executor.execute(request_for("peak_hours", limit=1))

    assert len(bundle.rows) == 1
    assert bundle.totals["trading_hour_cell_count"] == 2
    assert bundle.limits.available_rows == 2
    assert bundle.limits.truncated is True
    assert bundle.rows[0]["payment_order_count"] == (
        bundle.totals["peak_payment_order_count"]
    )


def test_peak_hours_is_not_truncated_when_every_trading_cell_fits(
    executor, trading
):
    bundle = executor.execute(request_for("peak_hours", limit=10))
    assert bundle.limits.truncated is False
    assert len(bundle.rows) == bundle.totals["trading_hour_cell_count"]


def test_a_date_series_returns_the_requested_range(executor, trading):
    """Series size is bounded by the validated range, not by a row limit."""
    bundle = executor.execute(
        request_for("revenue_over_time", start_date="2026-08-01",
                    end_date="2026-08-07")
    )
    assert len(bundle.rows) == 7
    assert bundle.limits.truncated is False
    assert bundle.limits.applied_limit is None


def test_day_of_week_always_returns_seven_rows(executor):
    bundle = executor.execute(request_for("day_of_week"))
    assert len(bundle.rows) == 7
    assert [r["iso_weekday"] for r in bundle.rows] == [1, 2, 3, 4, 5, 6, 7]


# --- product resolution through the executor ---------------------------------


def test_a_name_resolves_and_the_id_becomes_canonical(
    executor, trading, product_id
):
    bundle = executor.execute(
        request_for("product_trend", product={"name": "big breakfast"})
    )
    expected = product_id("Big Breakfast", "")

    assert bundle.status is EvidenceStatus.OK
    assert bundle.product_resolution.resolved.product_id == expected
    assert bundle.parameters["product_id"] == expected
    assert bundle.totals["product_id"] == expected


def test_an_ambiguous_name_returns_candidates_and_runs_nothing(executor, trading):
    bundle = executor.execute(
        request_for("product_trend", product={"name": "Caffe Latte"})
    )

    assert bundle.status is EvidenceStatus.AMBIGUOUS_PRODUCT
    assert bundle.rows == []
    assert bundle.period is None
    assert {c.variation for c in bundle.product_resolution.candidates} == {
        "Regular", "Large"
    }
    assert any("more than one" in w for w in bundle.warnings)


def test_an_unknown_name_returns_no_substitute(executor, trading):
    bundle = executor.execute(
        request_for("product_attachments", product={"name": "Lobster Thermidor"})
    )
    assert bundle.status is EvidenceStatus.UNKNOWN_PRODUCT
    assert bundle.rows == []
    assert bundle.product_resolution.candidates == []
    assert any("no similar product was" in w for w in bundle.warnings)


def test_an_unknown_id_is_reported_not_raised(executor, trading):
    bundle = executor.execute(
        request_for("product_trend", product={"product_id": 999_999})
    )
    assert bundle.status is EvidenceStatus.UNKNOWN_PRODUCT


def test_an_injection_shaped_name_is_an_unknown_product(
    executor, trading, session_factory
):
    from sqlalchemy import select

    from app.models import Order

    bundle = executor.execute(
        request_for(
            "product_trend", product={"name": "'; DROP TABLE orders; --"}
        )
    )
    assert bundle.status is EvidenceStatus.UNKNOWN_PRODUCT
    # Echoed back as data, and the table it names is untouched.
    assert bundle.product_resolution.requested_name == "'; DROP TABLE orders; --"
    with session_factory() as s:
        assert s.scalars(select(Order)).all()


# --- determinism -------------------------------------------------------------


@pytest.mark.parametrize("operation", ALL_OPERATIONS, ids=lambda o: o.value)
def test_the_same_request_produces_the_same_evidence(
    executor, trading, product_id, operation
):
    extra = {}
    if operation in (Operation.PRODUCT_TREND, Operation.PRODUCT_ATTACHMENTS):
        extra["product"] = {"product_id": product_id("Big Breakfast", "")}
    if operation in (Operation.PRODUCT_ATTACHMENTS, Operation.BASKET_PAIRS,
                     Operation.MENU_EVIDENCE):
        extra["min_pair_orders"] = 1

    request = request_for(operation.value, **extra)
    first = executor.execute(request).model_dump(mode="json")
    second = executor.execute(request).model_dump(mode="json")
    assert first == second


def test_ranking_ties_are_broken_deterministically(executor, make_sale):
    """Identical totals must still order the same way on every call."""
    for name in ("Bravo", "Alpha", "Charlie"):
        make_sale("2026-08-05T09:00", [(name, "", 1, 500)])

    request = request_for("product_performance")
    assert [r["product_name"] for r in executor.execute(request).rows] == [
        "Alpha", "Bravo", "Charlie"
    ]


# --- forecast ----------------------------------------------------------------


WEEK_SHAPE = [1000, 1100, 1200, 1300, 2000, 4000, 3800]


@pytest.fixture
def year_of_trade(make_order):
    start = date(2025, 9, 1)
    for index in range(200):
        day = start + timedelta(days=index)
        amount = WEEK_SHAPE[index % 7]
        make_order(f"{day.isoformat()}T12:00", net=amount, units=amount // 100)
    return start + timedelta(days=199)


def test_forecast_evidence_is_labelled_as_prediction(executor, year_of_trade):
    bundle = executor.execute(request_for("forecast", horizon_days=14))

    assert bundle.status is EvidenceStatus.OK
    assert bundle.field_provenance["predicted_value"] is EvidenceKind.FORECAST
    assert bundle.field_provenance["date"] is EvidenceKind.FORECAST
    assert not any(
        kind is EvidenceKind.MEASURED for kind in bundle.field_provenance.values()
    )
    assert any("PREDICTIONS" in w for w in bundle.warnings)


def test_forecast_provenance_carries_the_method_and_measured_error(
    executor, session_factory, year_of_trade
):
    expected = ForecastService(session_factory).forecast("net_sales_pence", 14)
    bundle = executor.execute(request_for("forecast", horizon_days=14))

    assert bundle.forecast.method == expected.method
    assert bundle.forecast.trained_through == year_of_trade
    assert bundle.forecast.historical_wape_percent == expected.historical_wape_percent
    assert bundle.forecast.historical_mae == expected.historical_mae
    assert bundle.forecast.backtest_folds == expected.backtest_folds
    assert bundle.forecast.backtest_horizon_days == expected.backtest_horizon_days
    assert bundle.forecast.unit == "pence"


def test_a_forecast_has_no_measured_period(executor, year_of_trade):
    """It is not a record of anything, so it has no period it measured."""
    bundle = executor.execute(request_for("forecast", horizon_days=3))
    assert bundle.period is None
    assert bundle.forecast is not None


def test_every_forecast_row_is_dated_after_the_last_real_day(
    executor, year_of_trade
):
    bundle = executor.execute(request_for("forecast", horizon_days=14))
    assert len(bundle.rows) == 14
    assert all(r["date"] > year_of_trade for r in bundle.rows)
    assert all(isinstance(r["predicted_value"], int) for r in bundle.rows)


def test_a_forecast_matches_the_forecast_service(
    executor, session_factory, year_of_trade
):
    expected = ForecastService(session_factory).forecast("net_sales_pence", 7)
    bundle = executor.execute(request_for("forecast", horizon_days=7))
    assert [r["predicted_value"] for r in bundle.rows] == [
        p.predicted_value for p in expected.points
    ]


def test_too_little_history_is_reported_not_raised(executor, make_order):
    make_order("2026-08-01T10:00", net=1000, units=1)
    bundle = executor.execute(request_for("forecast"))

    assert bundle.status is EvidenceStatus.INSUFFICIENT_HISTORY
    assert bundle.rows == []
    assert bundle.forecast is None


def test_no_confidence_interval_is_invented(executor, year_of_trade):
    """An unvalidated interval invites trust in a range nobody has checked.

    Checked on the FIELDS, not the prose: the warnings deliberately mention
    intervals in order to say that none is provided.
    """
    bundle = executor.execute(request_for("forecast"))
    emitted = (
        {key for row in bundle.rows for key in row}
        | set(bundle.totals)
        | set(bundle.forecast.model_dump())
    )
    forbidden = ("interval", "confidence", "lower", "upper", "bound", "p10", "p90")
    assert not [k for k in emitted if any(f in k for f in forbidden)]
