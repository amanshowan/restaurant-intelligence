"""The forecast service and endpoint."""

from __future__ import annotations

import warnings
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_forecast_service
from app.forecasting.service import (
    MAX_HORIZON_DAYS,
    ForecastService,
    InsufficientHistoryError,
)
from app.main import app

warnings.filterwarnings("ignore")

ENDPOINT = "/analytics/forecast"
WEEK_SHAPE = [1000, 1100, 1200, 1300, 2000, 4000, 3800]


@pytest.fixture
def seeded(session_factory, make_order):
    """A year of trade, one order per day, following a weekly cycle."""
    start = date(2025, 9, 1)
    for i in range(200):
        day = start + timedelta(days=i)
        amount = WEEK_SHAPE[i % 7]
        make_order(f"{day.isoformat()}T12:00", net=amount, units=amount // 100)
    return start + timedelta(days=199)


@pytest.fixture
def client(session_factory, seeded):
    service = ForecastService(session_factory)
    app.dependency_overrides[get_forecast_service] = lambda: service
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


# --- service -----------------------------------------------------------------


def test_service_trains_through_the_latest_observed_day(session_factory, seeded):
    """Not the wall clock: forecasting past the data would treat unimported
    days as closures."""
    result = ForecastService(session_factory).forecast("net_sales_pence", 5)

    assert result.trained_through == seeded
    assert result.forecast_start == seeded + timedelta(days=1)
    assert result.forecast_end == seeded + timedelta(days=5)


def test_service_returns_one_point_per_day_in_order(session_factory, seeded):
    result = ForecastService(session_factory).forecast("net_sales_pence", 14)

    assert len(result.points) == 14
    days = [p.day for p in result.points]
    assert days == sorted(days)
    assert days[0] == seeded + timedelta(days=1)
    assert all(
        b.day - a.day == timedelta(days=1) for a, b in zip(result.points, result.points[1:])
    )


def test_service_forecasts_a_single_day(session_factory, seeded):
    result = ForecastService(session_factory).forecast("net_sales_pence", 1)
    assert len(result.points) == 1
    assert result.forecast_start == result.forecast_end


def test_service_rejects_a_horizon_outside_one_to_fourteen(session_factory, seeded):
    service = ForecastService(session_factory)
    for horizon in (0, -1, MAX_HORIZON_DAYS + 1):
        with pytest.raises(ValueError, match="between 1 and 14"):
            service.forecast("net_sales_pence", horizon)


def test_service_values_are_integers_in_the_targets_unit(session_factory, seeded):
    money = ForecastService(session_factory).forecast("net_sales_pence", 3)
    counts = ForecastService(session_factory).forecast("payment_order_count", 3)

    assert money.unit == "pence"
    assert all(isinstance(p.predicted_value, int) for p in money.points)
    assert counts.unit == "orders"
    assert all(isinstance(p.predicted_value, int) for p in counts.points)


def test_count_forecasts_are_never_negative(session_factory, seeded):
    for target in ("payment_order_count", "net_units"):
        result = ForecastService(session_factory).forecast(target, 14)
        assert all(p.predicted_value >= 0 for p in result.points)


def test_service_reports_measured_historical_error(session_factory, seeded):
    """Accuracy must be measured, not asserted."""
    result = ForecastService(session_factory).forecast("net_sales_pence", 7)

    assert result.backtest_folds > 0
    assert result.backtest_horizon_days == 14
    assert result.historical_wape_percent is not None
    assert result.historical_wape_percent >= 0


def test_service_refuses_when_there_is_no_history(session_factory):
    with pytest.raises(InsufficientHistoryError, match="nothing to forecast"):
        ForecastService(session_factory).forecast("net_sales_pence", 7)


def test_service_refuses_when_history_is_too_short(session_factory, make_order):
    for i in range(40):
        day = date(2026, 1, 1) + timedelta(days=i)
        make_order(f"{day.isoformat()}T12:00", net=1000)

    with pytest.raises(InsufficientHistoryError, match="not enough"):
        ForecastService(session_factory).forecast("net_sales_pence", 7)


# --- endpoint ----------------------------------------------------------------


def test_endpoint_returns_a_forecast(client, seeded):
    response = client.get(ENDPOINT, params={"target": "net_sales", "horizon_days": 14})

    assert response.status_code == 200
    body = response.json()
    assert body["target"] == "net_sales"
    assert body["unit"] == "pence"
    assert body["method"]
    assert body["trained_through"] == seeded.isoformat()
    assert len(body["points"]) == 14
    assert all(isinstance(p["predicted_value"], int) for p in body["points"])


def test_endpoint_supports_every_target(client):
    for target, unit in (
        ("net_sales", "pence"),
        ("payment_orders", "orders"),
        ("net_units", "units"),
    ):
        response = client.get(ENDPOINT, params={"target": target, "horizon_days": 3})
        assert response.status_code == 200, target
        assert response.json()["unit"] == unit


def test_endpoint_rejects_an_unknown_target(client):
    response = client.get(ENDPOINT, params={"target": "profit"})

    assert response.status_code == 422
    body = response.json()
    assert body["code"] == "validation_error"
    assert body["errors"]


@pytest.mark.parametrize("horizon", [0, 15, -3])
def test_endpoint_rejects_a_horizon_outside_the_supported_range(client, horizon):
    response = client.get(
        ENDPOINT, params={"target": "net_sales", "horizon_days": horizon}
    )

    assert response.status_code == 422
    assert response.json()["code"] == "validation_error"


def test_endpoint_errors_use_the_shared_envelope(client):
    body = client.get(ENDPOINT, params={"horizon_days": 99}).json()

    assert set(body) >= {"detail", "code"}
    assert isinstance(body["detail"], str)


def test_endpoint_reports_insufficient_history_structurally(session_factory):
    """An empty database is a 422 with its own code, not a 500."""
    app.dependency_overrides[get_forecast_service] = lambda: ForecastService(
        session_factory
    )
    with TestClient(app) as c:
        response = c.get(ENDPOINT, params={"target": "net_sales"})
    app.dependency_overrides.clear()

    assert response.status_code == 422
    assert response.json()["code"] == "insufficient_history"


def test_endpoint_defaults_to_a_fourteen_day_net_sales_forecast(client):
    body = client.get(ENDPOINT).json()

    assert body["target"] == "net_sales"
    assert body["horizon_days"] == 14
    assert len(body["points"]) == 14


def test_endpoint_does_not_fabricate_prediction_intervals(client):
    """Unvalidated intervals invite false confidence; none are returned."""
    body = client.get(ENDPOINT, params={"horizon_days": 3}).json()
    point = body["points"][0]

    assert set(point) == {"date", "predicted_value"}
    assert not any("interval" in k or "lower" in k or "upper" in k for k in body)
