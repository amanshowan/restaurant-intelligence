"""The POST /analytics/query boundary.

Two things are under test here that a direct call to the executor cannot show:
that an adversarial body is rejected by the real application before it reaches
any code of ours, and that the published OpenAPI schema — which is what Commit
25 will hand a model as its tool definition — describes the same closed
whitelist the executor enforces.
"""

from __future__ import annotations

import warnings

import pytest
from fastapi.testclient import TestClient

from app.analytics.service import AnalyticsService
from app.api.deps import get_analytics_executor
from app.forecasting.service import ForecastService
from app.main import app
from app.nlq.executor import AnalyticsExecutor
from app.nlq.operations import Operation
from app.nlq.resolution import ProductResolver

warnings.filterwarnings("ignore")

ENDPOINT = "/analytics/query"


@pytest.fixture
def client(session_factory):
    app.dependency_overrides[get_analytics_executor] = lambda: AnalyticsExecutor(
        analytics=AnalyticsService(session_factory),
        forecasts=ForecastService(session_factory),
        resolver=ProductResolver(session_factory),
    )
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def trading(make_sale):
    make_sale("2026-08-03T09:00", [("Big Breakfast", "", 1, 950),
                                   ("Caffe Latte", "Regular", 1, 365)])
    make_sale("2026-08-04T09:00", [("Big Breakfast", "", 1, 950)])


def post(client, payload):
    return client.post(ENDPOINT, json=payload)


# --- the happy path ----------------------------------------------------------


def test_a_valid_request_returns_an_evidence_bundle(client, trading):
    response = post(
        client,
        {"operation": "overview", "start_date": "2026-08-01",
         "end_date": "2026-08-31"},
    )
    assert response.status_code == 200

    body = response.json()
    assert body["operation"] == "overview"
    assert body["status"] == "ok"
    assert body["period"] == {
        "start_date": "2026-08-01", "end_date": "2026-08-31", "days": 31
    }
    assert body["totals"]["net_sales_pence"] == 2265
    assert body["field_provenance"]["net_sales_pence"] == "measured"
    assert body["units"]["net_sales_pence"] == "pence"


def test_defaults_are_applied_and_echoed(client, trading):
    body = post(
        client,
        {"operation": "product_performance", "start_date": "2026-08-01",
         "end_date": "2026-08-31"},
    ).json()
    assert body["parameters"]["sort"] == "net_sales"
    assert body["parameters"]["limit"] == 10
    assert body["parameters"]["kinds"] == ["menu_item"]


def test_a_product_name_is_resolved_over_http(client, trading, product_id):
    body = post(
        client,
        {"operation": "product_trend", "start_date": "2026-08-01",
         "end_date": "2026-08-31", "product": {"name": "big breakfast"}},
    ).json()
    assert body["status"] == "ok"
    assert body["product_resolution"]["resolved"]["product_id"] == product_id(
        "Big Breakfast", ""
    )


def test_an_ambiguous_product_is_a_200_with_candidates(client, make_sale):
    """The candidate list is the useful part of the answer; a 4xx would throw
    it away and leave the caller nothing to ask again with."""
    make_sale("2026-08-03T09:00", [("Caffe Latte", "Regular", 1, 365)])
    make_sale("2026-08-03T10:00", [("Caffe Latte", "Large", 1, 415)])

    response = post(
        client,
        {"operation": "product_trend", "start_date": "2026-08-01",
         "end_date": "2026-08-31", "product": {"name": "Caffe Latte"}},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ambiguous_product"
    assert body["rows"] == []
    assert len(body["product_resolution"]["candidates"]) == 2


def test_pence_survive_json_as_integers(client, trading):
    body = post(
        client,
        {"operation": "overview", "start_date": "2026-08-01",
         "end_date": "2026-08-31"},
    ).json()
    assert isinstance(body["totals"]["net_sales_pence"], int)


# --- rejection, in the standard envelope -------------------------------------


@pytest.mark.parametrize(
    "payload",
    [
        {"operation": "DROP TABLE orders"},
        {"operation": "execute_sql", "sql": "SELECT 1"},
        {"operation": "run_query", "text": "SELECT * FROM orders"},
        {"operation": "overview", "start_date": "2026-08-01",
         "end_date": "2026-08-31", "unexpected_sql": "DROP TABLE orders"},
        {"operation": "overview", "start_date": "2026-08-01",
         "end_date": "2026-08-31", "table": "orders", "columns": ["*"]},
        {"operation": "product_performance", "start_date": "2026-08-01",
         "end_date": "2026-08-31", "limit": 100000000},
        {"operation": "forecast", "horizon_days": 999},
        {"operation": "overview", "start_date": "2026-08-31",
         "end_date": "2026-08-01"},
        {"operation": "product_trend", "start_date": "2026-08-01",
         "end_date": "2026-08-31", "product": {"product_id": "1; DELETE FROM orders"}},
        {"sql": "SELECT * FROM orders"},
        {},
    ],
)
def test_adversarial_bodies_are_rejected(client, payload):
    response = post(client, payload)
    assert response.status_code == 422

    body = response.json()
    assert body["code"] == "validation_error"
    assert body["errors"]


def test_a_rejection_reaches_no_database(client, session_factory, trading):
    """Validation happens in Pydantic, before a session is opened."""
    from sqlalchemy import select

    from app.models import Order

    assert post(client, {"operation": "DROP TABLE orders"}).status_code == 422
    with session_factory() as s:
        assert len(s.scalars(select(Order)).all()) == 2


def test_a_rejection_does_not_echo_the_submitted_value(client):
    """The existing envelope drops `input` and `ctx`; a payload should not be
    reflected back into logs through the AI endpoint either."""
    body = post(
        client,
        {"operation": "overview", "start_date": "2026-08-01",
         "end_date": "2026-08-31", "sql": "SELECT secret FROM orders"},
    ).json()
    assert "SELECT secret" not in str(body)


# --- the published contract --------------------------------------------------


def test_the_schema_offered_to_a_model_is_the_closed_whitelist(client):
    schema = app.openapi()
    reference = schema["paths"][ENDPOINT]["post"]["requestBody"]["content"][
        "application/json"
    ]["schema"]["$ref"]
    body = schema["components"]["schemas"][reference.rsplit("/", 1)[-1]]

    members = {ref["$ref"].rsplit("/", 1)[-1] for ref in body["oneOf"]}
    assert len(members) == len(Operation)
    # The tag is published, so the schema a model is given is the same closed
    # union the endpoint validates against.
    assert body["discriminator"]["propertyName"] == "operation"
    assert set(body["discriminator"]["mapping"]) == {o.value for o in Operation}


def test_no_member_of_the_whitelist_defaults_its_own_operation(client):
    """A body that names no operation must fail, not have one chosen for it."""
    schema = app.openapi()["components"]["schemas"]
    for name in (s for s in schema if s.endswith("Request")):
        properties = schema[name].get("properties", {})
        if "operation" in properties:
            assert "operation" in schema[name].get("required", []), name


def test_the_api_exposes_no_free_text_query_endpoint():
    """There is no route that takes SQL, a query string or an expression."""
    paths = app.openapi()["paths"]
    assert not [p for p in paths if "sql" in p.lower()]
    for path, methods in paths.items():
        for operation in methods.values():
            assert "sql" not in str(operation.get("parameters", "")).lower()
