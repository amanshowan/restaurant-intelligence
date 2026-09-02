"""Product analytics API surface."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.analytics.service import AnalyticsService
from app.api.deps import get_analytics_service
from app.main import app
from app.models.enums import ProductKind

BASE = "/analytics/products"
AUG = {"start_date": "2026-08-01", "end_date": "2026-08-31"}


@pytest.fixture
def client(session_factory):
    app.dependency_overrides[get_analytics_service] = lambda: AnalyticsService(
        session_factory
    )
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def test_product_list_response_model(client, make_sale):
    make_sale("2026-08-05T10:00", [("Caffe Latte", "Large", 2, 840)], discount=40)
    body = client.get(BASE, params=AUG).json()

    assert body["kinds"] == ["menu_item"]
    assert body["sort"] == "net_sales"
    assert body["total_net_sales_pence"] == 800
    assert "discount_allocation_note" not in body   # no longer approximated
    (p,) = body["products"]
    assert p["name"] == "Caffe Latte" and p["variation"] == "Large"
    assert p["kind"] == "menu_item"
    assert p["gross_sales_pence"] == 840
    assert p["discounts_pence"] == 40
    assert p["net_sales_pence"] == 800
    assert p["net_units"] == 2
    assert p["payment_order_count"] == 1
    assert p["average_selling_price_pence"] == 400
    assert p["share_of_net_sales_percent"] == 100.0
    assert isinstance(p["product_id"], int)


def test_variations_are_separate_rows_in_the_api(client, make_sale):
    make_sale("2026-08-05T10:00", [("Caffe Latte", "Regular", 1, 365)])
    make_sale("2026-08-05T11:00", [("Caffe Latte", "Large", 1, 420)])
    body = client.get(BASE, params=AUG).json()
    assert [(p["name"], p["variation"]) for p in body["products"]] == [
        ("Caffe Latte", "Large"), ("Caffe Latte", "Regular")
    ]


def test_sorting_and_limit(client, make_sale):
    make_sale("2026-08-05T10:00", [("A", "", 9, 100)])
    make_sale("2026-08-05T11:00", [("B", "", 1, 900)])
    by_units = client.get(BASE, params={**AUG, "sort": "net_units", "limit": 1}).json()
    assert [p["name"] for p in by_units["products"]] == ["A"]
    by_sales = client.get(BASE, params={**AUG, "sort": "net_sales", "limit": 1}).json()
    assert [p["name"] for p in by_sales["products"]] == ["B"]


def test_kind_filter_defaults_to_menu_only(client, make_sale):
    make_sale("2026-08-05T10:00", [("Latte", "", 1, 365)])
    make_sale("2026-08-05T11:00",
              [("Gift Voucher", "", 1, 1000, ProductKind.GIFT_VOUCHER)])
    default = client.get(BASE, params=AUG).json()
    assert [p["name"] for p in default["products"]] == ["Latte"]

    both = client.get(
        BASE, params=[*AUG.items(), ("kind", "menu_item"), ("kind", "gift_voucher")]
    ).json()
    assert {p["name"] for p in both["products"]} == {"Latte", "Gift Voucher"}
    assert both["kinds"] == ["menu_item", "gift_voucher"]


def test_invalid_kind_is_rejected(client):
    response = client.get(BASE, params={**AUG, "kind": "beverage"})
    assert response.status_code == 422
    assert response.json()["code"] == "validation_error"


def test_empty_period_returns_an_empty_list(client):
    body = client.get(BASE, params=AUG).json()
    assert body["products"] == []
    assert body["total_net_sales_pence"] == 0


# --- trend -------------------------------------------------------------------


def test_trend_response_model(client, make_sale, product_id):
    make_sale("2026-08-01T10:00", [("Latte", "", 1, 100)])
    pid = product_id("Latte", "")
    body = client.get(
        f"{BASE}/{pid}/trend",
        params={"start_date": "2026-08-01", "end_date": "2026-08-03"},
    ).json()

    assert body["granularity"] == "day"
    assert body["product"]["product_id"] == pid
    assert len(body["buckets"]) == 3
    assert body["buckets"][0]["net_sales_pence"] == 100
    assert body["buckets"][1]["net_sales_pence"] == 0      # zero-filled


def test_trend_weekly(client, make_sale, product_id):
    make_sale("2026-08-05T10:00", [("Latte", "", 1, 100)])
    body = client.get(
        f"{BASE}/{product_id('Latte', '')}/trend",
        params={"start_date": "2026-08-05", "end_date": "2026-08-07",
                "granularity": "week"},
    ).json()
    assert [b["period_start"] for b in body["buckets"]] == ["2026-08-03"]


def test_unknown_product_returns_a_structured_404(client):
    response = client.get(f"{BASE}/999999/trend", params=AUG)
    assert response.status_code == 404
    assert response.json() == {
        "detail": "no product with id 999999",
        "code": "product_not_found",
    }


def test_non_numeric_product_id_is_rejected(client):
    response = client.get(f"{BASE}/abc/trend", params=AUG)
    assert response.status_code == 422
    assert response.json()["code"] == "validation_error"


# --- movers ------------------------------------------------------------------


def test_movers_response_model(client, make_sale):
    make_sale("2026-08-01T10:00", [("Latte", "", 1, 1000)])
    make_sale("2026-08-09T10:00", [("Latte", "", 2, 1500)])
    body = client.get(
        f"{BASE}/movers",
        params={"start_date": "2026-08-08", "end_date": "2026-08-14"},
    ).json()

    assert body["previous_start_date"] == "2026-08-01"
    assert body["previous_end_date"] == "2026-08-07"
    (m,) = body["movements"]
    assert m["current_net_sales_pence"] == 1500
    assert m["previous_net_sales_pence"] == 1000
    assert m["net_sales_change_pence"] == 500
    assert m["net_sales_percent_change"] == 50.0
    assert m["net_units_change"] == 1
    assert m["status"] == "comparable"


def test_movers_null_percentage_for_a_new_product(client, make_sale):
    make_sale("2026-08-09T10:00", [("Latte", "", 1, 500)])
    body = client.get(
        f"{BASE}/movers",
        params={"start_date": "2026-08-08", "end_date": "2026-08-14"},
    ).json()
    (m,) = body["movements"]
    assert m["net_sales_percent_change"] is None
    assert m["status"] == "new_in_period"


def test_movers_route_is_not_shadowed_by_the_product_id_route(client):
    """/movers must not be parsed as a product id."""
    assert client.get(f"{BASE}/movers", params=AUG).status_code == 200


# --- validation and docs -----------------------------------------------------


@pytest.mark.parametrize("path", [BASE, f"{BASE}/movers"])
def test_reversed_range_returns_the_shared_error_envelope(client, path):
    response = client.get(
        path, params={"start_date": "2026-08-31", "end_date": "2026-08-01"}
    )
    assert response.status_code == 400
    assert response.json()["code"] == "invalid_date_range"


@pytest.mark.parametrize("path", [BASE, f"{BASE}/movers"])
def test_oversized_range_is_rejected(client, path):
    response = client.get(
        path, params={"start_date": "2020-01-01", "end_date": "2026-12-31"}
    )
    assert response.status_code == 400


def test_trend_range_guard(client, make_sale, product_id):
    make_sale("2026-08-01T10:00", [("Latte", "", 1, 100)])
    response = client.get(
        f"{BASE}/{product_id('Latte', '')}/trend",
        params={"start_date": "2026-08-31", "end_date": "2026-08-01"},
    )
    assert response.status_code == 400
    assert response.json()["code"] == "invalid_date_range"


def test_product_endpoints_appear_in_openapi(client):
    schema = client.get("/openapi.json").json()
    for path in ("/analytics/products", "/analytics/products/movers",
                 "/analytics/products/{product_id}/trend"):
        assert path in schema["paths"]
    for model in ("ProductListResponse", "ProductTrendResponse",
                  "ProductMoversResponse", "ProductPerformance"):
        assert model in schema["components"]["schemas"]
    trend = schema["paths"]["/analytics/products/{product_id}/trend"]["get"]
    assert "404" in trend["responses"]
