"""Analytics API surface."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.analytics.service import AnalyticsService
from app.api.deps import get_analytics_service
from app.main import app
from app.models.enums import OrderEventType


@pytest.fixture
def client(session_factory):
    app.dependency_overrides[get_analytics_service] = lambda: AnalyticsService(
        session_factory
    )
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def test_overview_response_model(client, make_order):
    make_order("2026-08-10T09:00", net=1000, discount=200, units=2)
    make_order("2026-08-10T09:30", net=-100, units=-1,
               event_type=OrderEventType.REFUND)

    response = client.get(
        "/analytics/overview",
        params={"start_date": "2026-08-01", "end_date": "2026-08-31"},
    )
    assert response.status_code == 200
    assert response.json() == {
        "start_date": "2026-08-01",
        "end_date": "2026-08-31",
        "net_sales_pence": 900,
        "gross_sales_pence": 1100,
        "discounts_pence": 200,
        "payment_order_count": 1,
        "refund_event_count": 1,
        "net_units": 1,
        "average_order_value_pence": 900,
    }


def test_overview_on_an_empty_period(client):
    body = client.get(
        "/analytics/overview",
        params={"start_date": "2026-08-01", "end_date": "2026-08-31"},
    ).json()
    assert body["net_sales_pence"] == 0
    assert body["average_order_value_pence"] == 0


def test_revenue_response_model(client, make_order):
    make_order("2026-08-01T10:00", net=100, units=1)
    body = client.get(
        "/analytics/revenue",
        params={"start_date": "2026-08-01", "end_date": "2026-08-03"},
    ).json()

    assert body["granularity"] == "day"
    assert len(body["buckets"]) == 3
    assert body["buckets"][0] == {
        "period_start": "2026-08-01",
        "net_sales_pence": 100,
        "gross_sales_pence": 100,
        "discounts_pence": 0,
        "payment_order_count": 1,
        "net_units": 1,
    }
    assert body["buckets"][1]["net_sales_pence"] == 0     # explicit zero bucket


def test_revenue_defaults_to_daily(client):
    body = client.get(
        "/analytics/revenue",
        params={"start_date": "2026-08-01", "end_date": "2026-08-02"},
    ).json()
    assert body["granularity"] == "day"


def test_revenue_weekly_granularity(client, make_order):
    make_order("2026-08-05T10:00", net=100)
    body = client.get(
        "/analytics/revenue",
        params={"start_date": "2026-08-03", "end_date": "2026-08-09",
                "granularity": "week"},
    ).json()
    assert body["granularity"] == "week"
    assert [b["period_start"] for b in body["buckets"]] == ["2026-08-03"]


def test_invalid_granularity_is_rejected(client):
    response = client.get(
        "/analytics/revenue",
        params={"start_date": "2026-08-01", "end_date": "2026-08-02",
                "granularity": "month"},
    )
    assert response.status_code == 422


def test_reversed_range_returns_400(client):
    response = client.get(
        "/analytics/overview",
        params={"start_date": "2026-08-31", "end_date": "2026-08-01"},
    )
    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "invalid_date_range"


def test_oversized_range_returns_400(client):
    response = client.get(
        "/analytics/revenue",
        params={"start_date": "2020-01-01", "end_date": "2026-12-31"},
    )
    assert response.status_code == 400
    assert "exceeds the maximum" in response.json()["detail"]["detail"]


def test_missing_dates_are_rejected(client):
    assert client.get("/analytics/overview").status_code == 422


def test_malformed_date_is_rejected(client):
    response = client.get(
        "/analytics/overview",
        params={"start_date": "not-a-date", "end_date": "2026-08-01"},
    )
    assert response.status_code == 422


def test_endpoints_appear_in_openapi(client):
    schema = client.get("/openapi.json").json()
    assert "/analytics/overview" in schema["paths"]
    assert "/analytics/revenue" in schema["paths"]
    assert "OverviewResponse" in schema["components"]["schemas"]
    assert "RevenueResponse" in schema["components"]["schemas"]
    assert "RevenueBucketResponse" in schema["components"]["schemas"]


# --- day-of-week -------------------------------------------------------------


def test_day_of_week_response_model(client, make_order):
    make_order("2026-08-03T10:00", net=1000, units=2)          # Monday
    body = client.get(
        "/analytics/day-of-week",
        params={"start_date": "2026-08-01", "end_date": "2026-08-31"},
    ).json()

    assert [w["weekday"] for w in body["weekdays"]] == [
        "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"
    ]
    assert body["weekdays"][0] == {
        "iso_weekday": 1, "weekday": "Monday", "net_sales_pence": 1000,
        "payment_order_count": 1, "net_units": 2,
        "average_order_value_pence": 1000,
    }
    assert body["weekdays"][1]["net_sales_pence"] == 0          # explicit zero row


# --- peak hours --------------------------------------------------------------


def test_peak_hours_response_model(client, make_order):
    make_order("2026-08-03T14:30", net=500, units=1)
    body = client.get(
        "/analytics/peak-hours",
        params={"start_date": "2026-08-01", "end_date": "2026-08-31"},
    ).json()

    assert len(body["cells"]) == 168
    assert body["peak_payment_order_count"] == 1
    assert body["busiest"] == [{
        "iso_weekday": 1, "weekday": "Monday", "hour": 14,
        "payment_order_count": 1, "net_sales_pence": 500, "net_units": 1,
    }]
    assert body["cells"][0]["hour"] == 0
    assert body["cells"][0]["payment_order_count"] == 0


def test_peak_hours_on_an_empty_period(client):
    body = client.get(
        "/analytics/peak-hours",
        params={"start_date": "2026-08-01", "end_date": "2026-08-07"},
    ).json()
    assert len(body["cells"]) == 168
    assert body["peak_payment_order_count"] == 0
    assert body["busiest"] == []


# --- channels ----------------------------------------------------------------


def test_channels_response_model(client, make_order):
    from app.models.enums import Channel

    make_order("2026-08-03T10:00", net=750, units=1, channel=Channel.IN_STORE)
    make_order("2026-08-03T11:00", net=250, units=1, channel=Channel.DELIVERY)
    body = client.get(
        "/analytics/channels",
        params={"start_date": "2026-08-01", "end_date": "2026-08-31"},
    ).json()

    assert [c["channel"] for c in body["channels"]] == ["in_store", "delivery"]
    assert body["channels"][0] == {
        "channel": "in_store", "net_sales_pence": 750, "payment_order_count": 1,
        "net_units": 1, "average_order_value_pence": 750,
        "share_of_payment_orders_percent": 50.0,
        "share_of_net_sales_percent": 75.0,
    }


def test_channels_null_shares_serialise_as_null(client, make_order):
    from app.models.enums import Channel, OrderEventType

    make_order("2026-08-03T10:00", net=-100, units=-1,
               event_type=OrderEventType.REFUND, channel=Channel.UNKNOWN)
    body = client.get(
        "/analytics/channels",
        params={"start_date": "2026-08-01", "end_date": "2026-08-31"},
    ).json()
    assert body["channels"][0]["share_of_net_sales_percent"] is None
    assert body["channels"][0]["share_of_payment_orders_percent"] is None


def test_channels_on_an_empty_period(client):
    body = client.get(
        "/analytics/channels",
        params={"start_date": "2026-08-01", "end_date": "2026-08-31"},
    ).json()
    assert body["channels"] == []


# --- validation applies to every endpoint ------------------------------------


@pytest.mark.parametrize(
    "path", ["/analytics/day-of-week", "/analytics/peak-hours", "/analytics/channels"]
)
def test_breakdown_endpoints_reject_reversed_ranges(client, path):
    response = client.get(
        path, params={"start_date": "2026-08-31", "end_date": "2026-08-01"}
    )
    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "invalid_date_range"


@pytest.mark.parametrize(
    "path", ["/analytics/day-of-week", "/analytics/peak-hours", "/analytics/channels"]
)
def test_breakdown_endpoints_reject_oversized_ranges(client, path):
    response = client.get(
        path, params={"start_date": "2020-01-01", "end_date": "2026-12-31"}
    )
    assert response.status_code == 400


@pytest.mark.parametrize(
    "path", ["/analytics/day-of-week", "/analytics/peak-hours", "/analytics/channels"]
)
def test_breakdown_endpoints_require_dates(client, path):
    assert client.get(path).status_code == 422


def test_breakdown_endpoints_appear_in_openapi(client):
    schema = client.get("/openapi.json").json()
    for path in ("/analytics/day-of-week", "/analytics/peak-hours",
                 "/analytics/channels"):
        assert path in schema["paths"]
    for model in ("DayOfWeekResponse", "PeakHoursResponse", "ChannelMixResponse",
                  "PeakHourCell", "ChannelMixEntry", "WeekdayTotalsResponse"):
        assert model in schema["components"]["schemas"]
