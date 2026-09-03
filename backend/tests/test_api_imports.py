"""API surface for the Square import workflow."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.api.deps import get_import_service
from app.main import app
from app.models import ImportBatch, Order, OrderItem, Product
from app.services.importer import SquareImportService
from tests.conftest import (
    ITEM_COLUMNS,
    SUMMARY_COLUMNS,
    TRANSACTION_COLUMNS,
    item_row,
    summary_row,
    transaction_row,
    write_square_export,
)

ENDPOINT = "/imports/square"


@pytest.fixture
def client(session_factory):
    """A TestClient whose import service uses the per-test session factory."""
    app.dependency_overrides[get_import_service] = lambda: SquareImportService(
        session_factory
    )
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture
def export_set(tmp_path):
    """Build a self-consistent set of Square files on disk."""

    def _make(transactions=None, items=None, summary=None, tag="a"):
        tx = write_square_export(
            tmp_path / f"transactions-{tag}.csv",
            TRANSACTION_COLUMNS,
            transactions
            if transactions is not None
            else [
                transaction_row(**{"Transaction ID": f"TX-{tag}",
                                   "Payment ID": f"PAY-{tag}",
                                   "Gross Sales": "£3.65", "Net Sales": "£3.65"})
            ],
        )
        it = write_square_export(
            tmp_path / f"items-{tag}.csv",
            ITEM_COLUMNS,
            items
            if items is not None
            else [item_row(**{"Transaction ID": f"TX-{tag}", "Product Sales": "£3.65"})],
        )
        sm = (
            write_square_export(tmp_path / f"summary-{tag}.csv", SUMMARY_COLUMNS, summary)
            if summary is not None
            else None
        )
        return tx, it, sm

    return _make


def upload(paths, label="august-2026"):
    tx, it, sm = paths
    files = [
        ("transactions", (tx.name, tx.read_bytes(), "text/csv")),
        ("items", (it.name, it.read_bytes(), "text/csv")),
    ]
    if sm is not None:
        files.append(("summary", (sm.name, sm.read_bytes(), "text/csv")))
    return {"files": files, "data": {"label": label} if label else {}}


# --- success -----------------------------------------------------------------


def test_successful_import_returns_201_and_a_typed_summary(
    client, export_set, session_factory
):
    paths = export_set(
        summary=[summary_row(**{"Units Sold": "1", "Product Sales": "£3.65",
                                "Net Sales": "£3.65"})]
    )
    response = client.post(ENDPOINT, **upload(paths))

    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "completed"
    assert body["label"] == "august-2026"
    assert body["orders_imported"] == 1
    assert body["order_items_imported"] == 1
    assert body["products_created"] == 1
    assert body["products_reused"] == 0
    assert body["rows_skipped"] == 0
    assert body["net_sales_pence"] == 365          # integer pence, never a float
    assert body["period_start"] == "2026-08-15"
    assert body["period_end"] == "2026-08-15"
    assert body["reconciliation"] == {
        "performed": True, "matches": True,
        "net_sales_pence_ours": 365, "net_sales_pence_theirs": 365,
        "line_totals_pence_ours": 365, "line_totals_pence_theirs": 365,
        "units_ours": 1, "units_theirs": 1,
    }

    with session_factory() as s:
        assert s.scalar(select(func.count()).select_from(Order)) == 1
        assert s.get(ImportBatch, body["batch_id"]) is not None


def test_summary_file_is_optional(client, export_set):
    response = client.post(ENDPOINT, **upload(export_set()))
    assert response.status_code == 201
    assert response.json()["reconciliation"]["performed"] is False


def test_label_is_optional(client, export_set):
    response = client.post(ENDPOINT, **upload(export_set(), label=None))
    assert response.status_code == 201
    assert response.json()["label"] is None


def test_issue_counts_are_reported(client, export_set):
    paths = export_set(
        transactions=[
            transaction_row(**{"Transaction ID": "TX-OK", "Net Sales": "£3.65",
                               "Gross Sales": "£3.65"}),
            transaction_row(**{"Transaction ID": "TX-ZERO", "Net Sales": "£0.00",
                               "Gross Sales": "£0.00"}),
        ],
        items=[item_row(**{"Transaction ID": "TX-OK", "Product Sales": "£3.65"})],
    )
    body = client.post(ENDPOINT, **upload(paths)).json()
    assert body["rows_skipped"] == 1
    assert body["issue_counts"]["zero_value_transaction"] == 1


# --- validation --------------------------------------------------------------


def test_missing_required_transactions_file_is_rejected(client, export_set):
    _, it, _ = export_set()
    response = client.post(
        ENDPOINT, files=[("items", (it.name, it.read_bytes(), "text/csv"))]
    )
    assert response.status_code == 422
    assert "transactions" in response.text


def test_missing_required_items_file_is_rejected(client, export_set):
    tx, _, _ = export_set()
    response = client.post(
        ENDPOINT, files=[("transactions", (tx.name, tx.read_bytes(), "text/csv"))]
    )
    assert response.status_code == 422


def test_malformed_encoding_returns_422_with_a_useful_message(client, export_set, tmp_path):
    tx, it, _ = export_set()
    bad = write_square_export(
        tmp_path / "bad.csv", TRANSACTION_COLUMNS, [transaction_row()], encoding="utf-8"
    )
    response = client.post(
        ENDPOINT,
        files=[
            ("transactions", (bad.name, bad.read_bytes(), "text/csv")),
            ("items", (it.name, it.read_bytes(), "text/csv")),
        ],
    )
    assert response.status_code == 422
    detail = response.json()
    assert detail["code"] == "invalid_source_file"
    assert "UTF-16" in detail["detail"]


def test_wrong_file_in_the_transactions_slot_returns_422(client, export_set):
    tx, it, _ = export_set()
    response = client.post(
        ENDPOINT,
        files=[
            ("transactions", (it.name, it.read_bytes(), "text/csv")),  # items file
            ("items", (it.name, it.read_bytes(), "text/csv")),
        ],
    )
    assert response.status_code == 422
    assert response.json()["code"] == "invalid_source_file"


def test_overlong_label_is_rejected(client, export_set):
    response = client.post(ENDPOINT, **upload(export_set(), label="x" * 300))
    assert response.status_code == 400
    assert response.json()["code"] == "invalid_request"


# --- conflicts ---------------------------------------------------------------


def test_duplicate_files_return_409(client, export_set, session_factory):
    paths = export_set()
    assert client.post(ENDPOINT, **upload(paths)).status_code == 201

    before = _counts(session_factory)
    response = client.post(ENDPOINT, **upload(paths, label="again"))

    assert response.status_code == 409
    assert response.json()["code"] == "duplicate_file"
    assert "already ingested" in response.json()["detail"]
    assert _counts(session_factory) == before          # nothing written, no batch


def test_conflicting_order_returns_409(client, export_set, session_factory, tmp_path):
    first = export_set(tag="one")
    assert client.post(ENDPOINT, **upload(first)).status_code == 201

    # Same transaction id, different money; ignored column varies so the file
    # checksum differs and preflight lets it reach conflict detection.
    conflicting = (
        write_square_export(
            tmp_path / "transactions-two.csv", TRANSACTION_COLUMNS,
            [transaction_row(**{"Transaction ID": "TX-one", "Payment ID": "PAY-one",
                                "Gross Sales": "£99.00", "Net Sales": "£99.00"})],
        ),
        write_square_export(
            tmp_path / "items-two.csv", ITEM_COLUMNS,
            [item_row(**{"Transaction ID": "TX-one", "Product Sales": "£3.65",
                         "SKU": "RE-EXPORT"})],
        ),
        None,
    )
    response = client.post(ENDPOINT, **upload(conflicting, label="two"))

    assert response.status_code == 409
    assert response.json()["code"] == "conflicting_order"
    with session_factory() as s:
        assert s.scalar(select(Order.net_amount)) == 365      # unchanged


def test_unresolved_channel_returns_422_with_its_own_code(
    client, export_set, session_factory, tmp_path
):
    """An unmappable Source/Dining Option is reported AS ITSELF.

    Distinct from reconciliation_failed on purpose: the source is telling us
    about a fulfilment combination we do not cover, and calling that an
    arithmetic mismatch sends the reader to audit a file that is correct.
    """
    tx = write_square_export(
        tmp_path / "unmapped.csv", TRANSACTION_COLUMNS,
        [transaction_row(**{"Transaction ID": "TX-1", "Net Sales": "£3.65",
                            "Gross Sales": "£3.65", "Dining Option": "Kerbside"})],
    )
    it = write_square_export(
        tmp_path / "unmapped-items.csv", ITEM_COLUMNS,
        [item_row(**{"Transaction ID": "TX-1", "Product Sales": "£3.65"})],
    )
    response = client.post(ENDPOINT, files=[
        ("transactions", (tx.name, tx.read_bytes(), "text/csv")),
        ("items", (it.name, it.read_bytes(), "text/csv")),
    ])

    assert response.status_code == 422
    body = response.json()
    assert body["code"] == "unresolved_channel"
    # Enough to extend the mapping from the response alone.
    assert "Kerbside" in body["detail"].lower() or "kerbside" in body["detail"].lower()
    assert "TX-1" in body["detail"]

    counts = _counts(session_factory)
    assert counts["orders"] == 0 and counts["items"] == 0 and counts["products"] == 0


def test_unresolved_channel_error_carries_no_pii(client, export_set, tmp_path):
    """The fixtures carry customer, card and staff columns throughout; none of
    them may appear in the message that names the unmapped combination."""
    tx = write_square_export(
        tmp_path / "pii.csv", TRANSACTION_COLUMNS,
        [transaction_row(**{"Transaction ID": "TX-1", "Net Sales": "£3.65",
                            "Gross Sales": "£3.65", "Dining Option": "Kerbside"})],
    )
    it = write_square_export(
        tmp_path / "pii-items.csv", ITEM_COLUMNS,
        [item_row(**{"Transaction ID": "TX-1", "Product Sales": "£3.65"})],
    )
    response = client.post(ENDPOINT, files=[
        ("transactions", (tx.name, tx.read_bytes(), "text/csv")),
        ("items", (it.name, it.read_bytes(), "text/csv")),
    ])

    text = response.text
    for secret in ("A Person", "CUST-9", "Visa", "4242", "A Barista"):
        assert secret not in text
    assert "Traceback" not in text


def test_reconciliation_failure_returns_422_and_writes_nothing(
    client, export_set, session_factory
):
    paths = export_set(
        summary=[summary_row(**{"Units Sold": "99", "Product Sales": "£99.00",
                                "Net Sales": "£99.00"})]
    )
    response = client.post(ENDPOINT, **upload(paths))

    assert response.status_code == 422
    assert response.json()["code"] == "reconciliation_failed"
    counts = _counts(session_factory)
    assert counts["orders"] == 0 and counts["items"] == 0 and counts["products"] == 0


# --- safety ------------------------------------------------------------------


def test_errors_never_leak_pii_or_stack_traces(client, export_set, tmp_path):
    """Fixtures carry customer, card and staff columns throughout."""
    tx, it, _ = export_set()
    bad = write_square_export(
        tmp_path / "bad.csv", TRANSACTION_COLUMNS, [transaction_row()], encoding="utf-8"
    )
    responses = [
        client.post(ENDPOINT, files=[
            ("transactions", (bad.name, bad.read_bytes(), "text/csv")),
            ("items", (it.name, it.read_bytes(), "text/csv"))]),
        client.post(ENDPOINT, **upload(export_set(tag="dup"))),
        client.post(ENDPOINT, **upload(export_set(tag="dup"))),
    ]
    for response in responses:
        text = response.text
        for forbidden in ("A Person", "CUST-9", "Visa", "4242", "A Barista",
                          "Traceback", "sqlalchemy", "File \""):
            assert forbidden not in text, f"{forbidden!r} leaked in {response.status_code}"


def test_unexpected_failure_returns_a_safe_500(client, export_set, monkeypatch):
    def explode(self, request):
        raise RuntimeError("connection to server at 10.0.0.5 failed: password auth")

    monkeypatch.setattr(SquareImportService, "run", explode)
    response = client.post(ENDPOINT, **upload(export_set()))

    assert response.status_code == 500
    body = response.json()
    assert body["code"] == "internal_error"
    assert body["detail"] == "An internal error occurred while processing the import."
    assert "password" not in response.text and "10.0.0.5" not in response.text


def test_client_filename_is_not_trusted_for_the_period(client, export_set):
    """Rows are dated 2026-08-15; the filename claims 1999."""
    tx, it, _ = export_set()
    response = client.post(
        ENDPOINT,
        files=[
            ("transactions", ("transactions-1999-01-01-1999-01-31.csv",
                              tx.read_bytes(), "text/csv")),
            ("items", ("items-1999-01-01-1999-01-31.csv", it.read_bytes(), "text/csv")),
        ],
    )
    assert response.status_code == 201
    assert response.json()["period_start"] == "2026-08-15"


def test_path_traversal_in_a_filename_is_neutralised(client, export_set, session_factory):
    from app.models import ImportFile

    tx, it, _ = export_set()
    response = client.post(
        ENDPOINT,
        files=[
            ("transactions", ("../../../etc/passwd", tx.read_bytes(), "text/csv")),
            ("items", (it.name, it.read_bytes(), "text/csv")),
        ],
    )
    assert response.status_code == 201
    with session_factory() as s:
        names = {f.filename for f in s.scalars(select(ImportFile)).all()}
    assert "passwd" in names
    assert not any("/" in n or ".." in n for n in names)


def test_endpoint_and_response_model_appear_in_openapi(client):
    schema = client.get("/openapi.json").json()
    assert "/imports/square" in schema["paths"]
    operation = schema["paths"]["/imports/square"]["post"]
    assert set(operation["responses"]) >= {"201", "400", "409", "413", "422", "500"}
    assert "ImportSummary" in schema["components"]["schemas"]
    assert "ReconciliationResult" in schema["components"]["schemas"]
    assert client.get("/docs").status_code == 200


def _counts(session_factory) -> dict[str, int]:
    with session_factory() as s:
        return {
            "orders": s.scalar(select(func.count()).select_from(Order)),
            "items": s.scalar(select(func.count()).select_from(OrderItem)),
            "products": s.scalar(select(func.count()).select_from(Product)),
            "batches": s.scalar(select(func.count()).select_from(ImportBatch)),
        }
