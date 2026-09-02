"""Basket / attachment API surface."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.analytics.service import AnalyticsService
from app.api.deps import get_analytics_service
from app.main import app
from app.models.enums import ProductKind

PAIRS = "/analytics/baskets/pairs"
AUG = {"start_date": "2026-08-01", "end_date": "2026-08-31"}


@pytest.fixture
def client(session_factory):
    app.dependency_overrides[get_analytics_service] = lambda: AnalyticsService(
        session_factory
    )
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def test_pairs_response_model(client, make_sale):
    make_sale("2026-08-01T10:00", [("Latte", "Regular", 1, 300), ("Toast", "", 1, 500)])
    make_sale("2026-08-02T10:00", [("Latte", "Regular", 1, 300), ("Toast", "", 1, 500)])
    body = client.get(PAIRS, params=AUG).json()

    assert body["kinds"] == ["menu_item"]
    assert body["sort"] == "pair_orders"
    assert body["min_pair_orders"] == 1
    assert body["eligible_order_count"] == 2
    assert body["distinct_product_count"] == 2
    assert body["qualifying_pair_count"] == 1
    (pair,) = body["pairs"]
    assert pair["pair_orders"] == 2
    assert pair["product_a_orders"] == 2
    assert pair["product_b_orders"] == 2
    assert pair["support_percent"] == 100.0
    assert pair["confidence_a_to_b_percent"] == 100.0
    assert pair["confidence_b_to_a_percent"] == 100.0
    assert pair["lift"] == 1.0
    assert {pair["product_a"]["name"], pair["product_b"]["name"]} == {"Latte", "Toast"}


def test_pairs_empty_period(client):
    body = client.get(PAIRS, params=AUG).json()
    assert body["pairs"] == []
    assert body["eligible_order_count"] == 0


def test_pairs_min_threshold_and_limit(client, make_sale):
    make_sale("2026-08-01T10:00", [("A", "", 1, 100), ("B", "", 1, 100)])
    make_sale("2026-08-02T10:00", [("A", "", 1, 100), ("B", "", 1, 100)])
    make_sale("2026-08-03T10:00", [("A", "", 1, 100), ("C", "", 1, 100)])

    strict = client.get(PAIRS, params={**AUG, "min_pair_orders": 2}).json()
    assert strict["qualifying_pair_count"] == 1
    limited = client.get(PAIRS, params={**AUG, "limit": 1}).json()
    assert len(limited["pairs"]) == 1
    assert limited["qualifying_pair_count"] == 2


def test_pairs_sort_options(client, make_sale):
    make_sale("2026-08-01T10:00", [("A", "", 1, 100), ("B", "", 1, 100)])
    for sort in ("pair_orders", "lift", "support"):
        body = client.get(PAIRS, params={**AUG, "sort": sort}).json()
        assert body["sort"] == sort
    assert client.get(PAIRS, params={**AUG, "sort": "magic"}).status_code == 422


def test_pairs_kind_filter(client, make_sale):
    make_sale("2026-08-01T10:00",
              [("A", "", 1, 100),
               ("Voucher", "", 1, 100, ProductKind.GIFT_VOUCHER)])
    assert client.get(PAIRS, params=AUG).json()["pairs"] == []
    both = client.get(
        PAIRS, params=[*AUG.items(), ("kind", "menu_item"), ("kind", "gift_voucher")]
    ).json()
    assert len(both["pairs"]) == 1


def test_pairs_validation_errors_use_the_shared_envelope(client):
    reversed_range = client.get(
        PAIRS, params={"start_date": "2026-08-31", "end_date": "2026-08-01"}
    )
    assert reversed_range.status_code == 400
    assert reversed_range.json()["code"] == "invalid_date_range"

    oversized = client.get(
        PAIRS, params={"start_date": "2020-01-01", "end_date": "2026-12-31"}
    )
    assert oversized.status_code == 400
    assert client.get(PAIRS).status_code == 422
    assert client.get(PAIRS, params={**AUG, "min_pair_orders": 0}).status_code == 422


# --- attachments -------------------------------------------------------------


def test_attachments_response_model(client, make_sale, product_id):
    make_sale("2026-08-01T10:00", [("Latte", "Regular", 1, 300), ("Toast", "", 1, 500)])
    make_sale("2026-08-02T10:00", [("Latte", "Regular", 1, 300)])
    pid = product_id("Latte", "Regular")
    body = client.get(
        f"/analytics/products/{pid}/attachments", params=AUG
    ).json()

    assert body["anchor"]["product_id"] == pid
    assert body["anchor"]["variation"] == "Regular"
    assert body["anchor_order_count"] == 2
    assert body["eligible_order_count"] == 2
    (attached,) = body["attachments"]
    assert attached["product"]["name"] == "Toast"
    assert attached["pair_orders"] == 1
    assert attached["product_orders"] == 1
    assert attached["attachment_rate_percent"] == 50.0
    assert attached["reverse_attachment_rate_percent"] == 100.0
    assert attached["support_percent"] == 50.0
    assert attached["lift"] == 1.0


def test_attachments_unknown_anchor_returns_structured_404(client):
    response = client.get("/analytics/products/999999/attachments", params=AUG)
    assert response.status_code == 404
    assert response.json() == {
        "detail": "no product with id 999999",
        "code": "product_not_found",
    }


def test_attachments_validation(client, make_sale, product_id):
    make_sale("2026-08-01T10:00", [("Latte", "", 1, 300)])
    pid = product_id("Latte", "")
    bad_range = client.get(
        f"/analytics/products/{pid}/attachments",
        params={"start_date": "2026-08-31", "end_date": "2026-08-01"},
    )
    assert bad_range.status_code == 400
    assert bad_range.json()["code"] == "invalid_date_range"
    assert client.get("/analytics/products/abc/attachments",
                      params=AUG).status_code == 422


def test_basket_endpoints_appear_in_openapi(client):
    schema = client.get("/openapi.json").json()
    for path in ("/analytics/baskets/pairs",
                 "/analytics/products/{product_id}/attachments"):
        assert path in schema["paths"]
        params = schema["paths"][path]["get"].get("parameters", [])
        assert all(p.get("description") for p in params), path
    for model in ("ProductPairsResponse", "ProductAttachmentsResponse",
                  "ProductPairEntry", "AttachmentEntry"):
        assert model in schema["components"]["schemas"]
