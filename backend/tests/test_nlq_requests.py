"""The request whitelist.

These are the security tests. Every one of them asserts the same property from
a different angle: a structured request cannot express anything the executor
was not built to run, and an invalid one fails in Pydantic — before a session
is opened, let alone a statement issued.
"""

from __future__ import annotations

from datetime import date

import pytest
from pydantic import TypeAdapter, ValidationError

from app.analytics.windows import MAX_RANGE_DAYS
from app.forecasting.service import MAX_HORIZON_DAYS
from app.nlq.operations import MAX_PRODUCT_ROWS, Operation
from app.nlq.requests import AnalyticsRequest, ProductSelector

ADAPTER = TypeAdapter(AnalyticsRequest)


def parse(payload: dict):
    return ADAPTER.validate_python(payload)


def dated(operation: str, **extra) -> dict:
    return {
        "operation": operation,
        "start_date": "2026-08-01",
        "end_date": "2026-08-31",
        **extra,
    }


# --- the enum is closed ------------------------------------------------------


def test_every_operation_has_a_schema():
    """No member of the enum is unreachable, and none is missing a schema."""
    for operation in Operation:
        payload = {"operation": operation.value}
        if operation is not Operation.FORECAST:
            payload |= {"start_date": "2026-08-01", "end_date": "2026-08-31"}
        if operation in (Operation.PRODUCT_TREND, Operation.PRODUCT_ATTACHMENTS):
            payload["product"] = {"product_id": 1}
        assert parse(payload).operation is operation


def test_there_is_no_generic_fallback_operation():
    """A catch-all would reopen exactly the hole the enum closes."""
    for forbidden in ("custom", "raw", "sql", "query", "other", "generic"):
        assert forbidden not in {o.value for o in Operation}


@pytest.mark.parametrize(
    "operation",
    [
        "DROP TABLE orders",
        "select",
        "execute_sql",
        "overview; DELETE FROM orders",
        "OVERVIEW",
        "",
    ],
)
def test_unsupported_operations_are_rejected(operation):
    with pytest.raises(ValidationError):
        parse({"operation": operation, "start_date": "2026-08-01",
               "end_date": "2026-08-31"})


def test_a_missing_operation_is_rejected():
    with pytest.raises(ValidationError):
        parse({"start_date": "2026-08-01", "end_date": "2026-08-31"})


# --- unknown fields do not pass through --------------------------------------


@pytest.mark.parametrize(
    "field, value",
    [
        ("sql", "SELECT * FROM orders"),
        ("unexpected_sql", "DROP TABLE orders"),
        ("table", "orders"),
        ("columns", ["net_amount"]),
        ("where", "1=1"),
        ("expression", "__import__('os').system('id')"),
        ("order_by", "net_amount; --"),
    ],
)
def test_unknown_fields_are_rejected_not_ignored(field, value):
    """Silently dropping an unexpected key is how an injection attempt becomes
    an unnoticed one."""
    with pytest.raises(ValidationError) as exc:
        parse(dated("overview", **{field: value}))
    assert "extra" in str(exc.value).lower() or "not permitted" in str(exc.value)


def test_unknown_fields_are_rejected_on_nested_models():
    with pytest.raises(ValidationError):
        parse(
            dated(
                "product_trend",
                product={"product_id": 1, "sql": "DROP TABLE products"},
            )
        )


def test_a_misspelled_field_does_not_silently_default():
    with pytest.raises(ValidationError):
        parse(dated("product_performance", limitt=5))


# --- bounded values ----------------------------------------------------------


@pytest.mark.parametrize("limit", [0, -1, 100000000, MAX_PRODUCT_ROWS + 1])
def test_out_of_range_limits_are_rejected(limit):
    with pytest.raises(ValidationError):
        parse(dated("product_performance", limit=limit))


@pytest.mark.parametrize("horizon", [0, -5, 999, MAX_HORIZON_DAYS + 1])
def test_out_of_range_forecast_horizons_are_rejected(horizon):
    with pytest.raises(ValidationError):
        parse({"operation": "forecast", "horizon_days": horizon})


def test_the_maximum_horizon_is_the_services_own():
    request = parse({"operation": "forecast", "horizon_days": MAX_HORIZON_DAYS})
    assert request.horizon_days == MAX_HORIZON_DAYS


@pytest.mark.parametrize(
    "payload",
    [
        dated("product_performance", sort="net_amount"),
        dated("product_performance", sort="net_sales; DROP TABLE orders"),
        dated("revenue_over_time", granularity="hour"),
        dated("basket_pairs", sort="whatever"),
        {"operation": "forecast", "target": "profit"},
        dated("product_performance", kinds=["not_a_kind"]),
    ],
)
def test_enum_fields_accept_only_declared_values(payload):
    with pytest.raises(ValidationError):
        parse(payload)


def test_min_pair_orders_is_bounded():
    with pytest.raises(ValidationError):
        parse(dated("basket_pairs", min_pair_orders=0))
    with pytest.raises(ValidationError):
        parse(dated("basket_pairs", min_pair_orders=10_000_000))


# --- date ranges -------------------------------------------------------------


def test_a_reversed_range_is_rejected():
    with pytest.raises(ValidationError):
        parse(
            {"operation": "overview", "start_date": "2026-08-31",
             "end_date": "2026-08-01"}
        )


def test_a_range_longer_than_the_existing_maximum_is_rejected():
    """The AI layer inherits the HTTP API's span limit rather than setting one."""
    start = date(2025, 1, 1)
    end = date.fromordinal(start.toordinal() + MAX_RANGE_DAYS)
    with pytest.raises(ValidationError) as exc:
        parse(
            {"operation": "overview", "start_date": start.isoformat(),
             "end_date": end.isoformat()}
        )
    assert str(MAX_RANGE_DAYS) in str(exc.value)


def test_the_maximum_range_itself_is_accepted():
    start = date(2025, 9, 1)
    end = date.fromordinal(start.toordinal() + MAX_RANGE_DAYS - 1)
    assert parse(
        {"operation": "overview", "start_date": start.isoformat(),
         "end_date": end.isoformat()}
    ).end_date == end


@pytest.mark.parametrize("value", ["not-a-date", "2026-13-01", "'; DROP TABLE x", 20260801])
def test_malformed_dates_are_rejected(value):
    with pytest.raises(ValidationError):
        parse({"operation": "overview", "start_date": value,
               "end_date": "2026-08-31"})


def test_a_forecast_request_has_no_date_range():
    """Nominating an origin would let a caller receive a past period labelled
    as a prediction."""
    with pytest.raises(ValidationError):
        parse({"operation": "forecast", "start_date": "2026-08-01",
               "end_date": "2026-08-31"})


# --- product references ------------------------------------------------------


def test_a_product_reference_needs_exactly_one_identifier():
    with pytest.raises(ValidationError):
        ProductSelector()
    with pytest.raises(ValidationError):
        ProductSelector(product_id=1, name="Big Breakfast")


def test_a_variation_cannot_accompany_an_id():
    with pytest.raises(ValidationError):
        ProductSelector(product_id=1, variation="Large")


@pytest.mark.parametrize("value", ["1; DELETE FROM orders", "1 OR 1=1", "abc", 0, -3])
def test_product_ids_must_be_positive_integers(value):
    with pytest.raises(ValidationError):
        parse(dated("product_trend", product={"product_id": value}))


def test_an_injection_shaped_name_is_accepted_as_a_plain_string():
    """It is a VALUE. Rejecting it here would be theatre; what matters is that
    it can only ever be compared, never executed."""
    request = parse(
        dated("product_trend", product={"name": "'; DROP TABLE orders; --"})
    )
    assert request.product.name == "'; DROP TABLE orders; --"
    assert request.product.product_id is None


def test_an_over_long_name_is_rejected():
    with pytest.raises(ValidationError):
        parse(dated("product_trend", product={"name": "x" * 256}))


# --- immutability ------------------------------------------------------------


def test_a_validated_request_cannot_be_mutated_afterwards():
    """Nothing between validation and execution can widen what was approved."""
    request = parse(dated("product_performance", limit=5))
    with pytest.raises(ValidationError):
        request.limit = 100000


@pytest.mark.parametrize("name", ["Big Breakfast\x00", "Big\tBreakfast\x07", "\x00"])
def test_control_characters_in_a_product_name_are_rejected(name):
    """PostgreSQL text cannot hold a NUL, so such a name can match nothing and
    would otherwise surface as a driver error rather than an answer."""
    with pytest.raises(ValidationError):
        parse(dated("product_trend", product={"name": name}))
