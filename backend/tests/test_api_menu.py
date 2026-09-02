"""Menu evidence API surface."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.analytics.service import AnalyticsService
from app.api.deps import get_analytics_service
from app.main import app
from app.models.enums import ProductKind

ENDPOINT = "/analytics/menu/evidence"
WINDOW = {"start_date": "2026-08-08", "end_date": "2026-08-14"}


@pytest.fixture
def client(session_factory):
    app.dependency_overrides[get_analytics_service] = lambda: AnalyticsService(
        session_factory
    )
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def test_evidence_response_model(client, make_sale):
    make_sale("2026-08-03T10:00", [("Latte", "Regular", 1, 1000)])
    make_sale("2026-08-10T10:00",
              [("Latte", "Regular", 2, 2000, ProductKind.MENU_ITEM, 200)],
              discount=200)
    body = client.get(ENDPOINT, params=WINDOW).json()

    assert body["previous_start_date"] == "2026-08-01"
    assert body["previous_end_date"] == "2026-08-07"
    assert body["kinds"] == ["menu_item"]
    assert body["min_pair_orders"] == 5
    assert body["total_net_sales_pence"] == 1800

    (row,) = body["rows"]
    assert row["product"]["name"] == "Latte"
    assert row["product"]["variation"] == "Regular"
    assert row["kind"] == "menu_item"
    assert row["gross_sales_pence"] == 2000
    assert row["discounts_pence"] == 200
    assert row["net_sales_pence"] == 1800
    assert row["discount_rate_percent"] == 10.0
    assert row["net_units"] == 2
    assert row["average_selling_price_pence"] == 900
    assert row["previous_net_sales_pence"] == 1000
    assert row["net_sales_change_pence"] == 800
    assert row["net_sales_percent_change"] == 80.0
    assert row["movement_status"] == "comparable"
    assert row["revenue_direction"] == "increasing"
    assert row["strongest_attachment"] is None


def test_attachment_is_serialised_when_it_qualifies(client, make_sale):
    for day in (8, 9, 10, 11, 12):
        make_sale(f"2026-08-{day:02d}T10:00",
                  [("Latte", "", 1, 300), ("Scone", "", 1, 200)])
    body = client.get(ENDPOINT, params={**WINDOW, "min_pair_orders": 5}).json()
    row = next(r for r in body["rows"] if r["product"]["name"] == "Latte")
    assert row["strongest_attachment"] == {
        "product": {"product_id": row["strongest_attachment"]["product"]["product_id"],
                    "name": "Scone", "variation": ""},
        "pair_orders": 5,
        "attachment_rate_percent": 100.0,
        "lift": 1.0,
    }


def test_empty_window(client):
    body = client.get(ENDPOINT, params=WINDOW).json()
    assert body["rows"] == []
    assert body["total_net_sales_pence"] == 0
    assert body["eligible_order_count"] == 0


def test_limit_and_kind_filter(client, make_sale):
    make_sale("2026-08-10T10:00",
              [("Latte", "", 1, 300),
               ("Voucher", "", 1, 1000, ProductKind.GIFT_VOUCHER)])
    default = client.get(ENDPOINT, params=WINDOW).json()
    assert [r["product"]["name"] for r in default["rows"]] == ["Latte"]

    both = client.get(
        ENDPOINT,
        params=[*WINDOW.items(), ("kind", "menu_item"), ("kind", "gift_voucher")],
    ).json()
    assert len(both["rows"]) == 2

    limited = client.get(ENDPOINT, params={**WINDOW, "limit": 1}).json()
    assert len(limited["rows"]) == 1


def test_validation_errors_use_the_shared_envelope(client):
    reversed_range = client.get(
        ENDPOINT, params={"start_date": "2026-08-31", "end_date": "2026-08-01"}
    )
    assert reversed_range.status_code == 400
    assert reversed_range.json()["code"] == "invalid_date_range"

    oversized = client.get(
        ENDPOINT, params={"start_date": "2020-01-01", "end_date": "2026-12-31"}
    )
    assert oversized.status_code == 400
    assert client.get(ENDPOINT).status_code == 422
    assert client.get(
        ENDPOINT, params={**WINDOW, "min_pair_orders": 0}
    ).status_code == 422
    assert client.get(
        ENDPOINT, params={**WINDOW, "kind": "beverage"}
    ).status_code == 422


def test_response_contains_no_recommendation_language(client, make_sale):
    """The view reports evidence. It must not editorialise."""
    import re

    make_sale("2026-08-10T10:00", [("Latte", "", 1, 300), ("Scone", "", 1, 200)])
    text = client.get(ENDPOINT, params=WINDOW).text.lower()
    # Word boundaries, not substrings: "star" would otherwise match
    # "start_date", which is a legitimate field name.
    for banned in ("star", "dog", "winner", "loser", "opportunity", "promote",
                   "remove from menu", "raise price", "optimal", "profit",
                   "margin", "poor performer", "recommend"):
        assert re.search(rf"\b{banned}\b", text) is None, (
            f"{banned!r} leaked into the response"
        )


def test_endpoint_appears_in_openapi(client):
    schema = client.get("/openapi.json").json()
    assert ENDPOINT in schema["paths"]
    operation = schema["paths"][ENDPOINT]["get"]
    assert all(p.get("description") for p in operation.get("parameters", []))
    for model in ("MenuEvidenceResponse", "MenuEvidenceRowResponse",
                  "AttachmentEvidenceEntry"):
        assert model in schema["components"]["schemas"]
