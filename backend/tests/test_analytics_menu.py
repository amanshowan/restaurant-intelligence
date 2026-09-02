"""Menu evidence view."""

from __future__ import annotations

from datetime import date

import pytest

from app.analytics.service import AnalyticsService, MovementStatus, RevenueDirection
from app.models.enums import OrderEventType, ProductKind

CURRENT = (date(2026, 8, 8), date(2026, 8, 14))
LATTE = ("Latte", "Regular")
TOAST = ("Toast", "")
SCONE = ("Scone", "")


@pytest.fixture
def analytics(session_factory) -> AnalyticsService:
    return AnalyticsService(session_factory)


def rows_by_name(evidence):
    return {r.product.name: r for r in evidence.rows}


# --- agreement with existing endpoints ---------------------------------------


def test_evidence_agrees_with_the_products_endpoint(analytics, make_sale):
    make_sale("2026-08-10T10:00",
              [(*LATTE, 2, 800, ProductKind.MENU_ITEM, 100),
               (*TOAST, 1, 500, ProductKind.MENU_ITEM, 0)], discount=100)
    evidence = analytics.menu_evidence(*CURRENT)
    ranking = {(p.totals.name): p.totals for p in analytics.products(*CURRENT).products}

    for row in evidence.rows:
        totals = ranking[row.product.name]
        assert row.gross_sales_pence == totals.gross_sales_pence
        assert row.discounts_pence == totals.discounts_pence
        assert row.net_sales_pence == totals.net_sales_pence
        assert row.net_units == totals.net_units
        assert row.payment_order_count == totals.payment_order_count
        assert row.average_selling_price_pence == totals.average_selling_price_pence
    assert evidence.total_net_sales_pence == sum(
        t.net_sales_pence for t in ranking.values()
    )


def test_discount_rate_uses_exact_source_line_discounts(analytics, make_sale):
    """A discount on ONE line of a two-line order stays on that product."""
    make_sale("2026-08-10T10:00",
              [(*LATTE, 1, 1000, ProductKind.MENU_ITEM, 250),
               (*TOAST, 1, 1000, ProductKind.MENU_ITEM, 0)], discount=250)
    rows = rows_by_name(analytics.menu_evidence(*CURRENT))

    assert rows["Latte"].discounts_pence == 250
    assert rows["Latte"].gross_sales_pence == 1000
    assert rows["Latte"].discount_rate_percent == 25.0
    assert rows["Toast"].discounts_pence == 0
    assert rows["Toast"].discount_rate_percent == 0.0


def test_discount_rate_is_null_when_gross_is_not_positive(analytics, make_sale):
    make_sale("2026-08-10T10:00", [(*LATTE, 1, 0)])
    (row,) = analytics.menu_evidence(*CURRENT).rows
    assert row.gross_sales_pence == 0
    assert row.discount_rate_percent is None


# --- period movement ---------------------------------------------------------


def test_previous_window_is_equal_length_and_immediately_prior(analytics):
    evidence = analytics.menu_evidence(*CURRENT)
    assert evidence.window.days == 7
    assert evidence.previous_window.days == 7
    assert evidence.previous_window.end_date == date(2026, 8, 7)
    assert evidence.previous_window.start_date == date(2026, 8, 1)


def test_increasing_revenue(analytics, make_sale):
    make_sale("2026-08-03T10:00", [(*LATTE, 1, 1000)])
    make_sale("2026-08-10T10:00", [(*LATTE, 2, 1500)])
    (row,) = analytics.menu_evidence(*CURRENT).rows

    assert row.previous_net_sales_pence == 1000
    assert row.net_sales_pence == 1500
    assert row.net_sales_change_pence == 500
    assert row.net_sales_percent_change == 50.0
    assert row.movement_status is MovementStatus.COMPARABLE
    assert row.revenue_direction is RevenueDirection.INCREASING
    assert row.net_units_change == 1


def test_decreasing_revenue(analytics, make_sale):
    make_sale("2026-08-03T10:00", [(*LATTE, 4, 2000)])
    make_sale("2026-08-10T10:00", [(*LATTE, 1, 500)])
    (row,) = analytics.menu_evidence(*CURRENT).rows
    assert row.net_sales_percent_change == -75.0
    assert row.revenue_direction is RevenueDirection.DECREASING


def test_unchanged_revenue(analytics, make_sale):
    make_sale("2026-08-03T10:00", [(*LATTE, 1, 500)])
    make_sale("2026-08-10T10:00", [(*LATTE, 1, 500)])
    (row,) = analytics.menu_evidence(*CURRENT).rows
    assert row.net_sales_change_pence == 0
    assert row.net_sales_percent_change == 0.0
    assert row.revenue_direction is RevenueDirection.UNCHANGED


def test_new_in_period_has_no_percentage(analytics, make_sale):
    make_sale("2026-08-10T10:00", [(*LATTE, 1, 500)])
    (row,) = analytics.menu_evidence(*CURRENT).rows
    assert row.previous_net_sales_pence == 0
    assert row.net_sales_percent_change is None
    assert row.movement_status is MovementStatus.NEW_IN_PERIOD
    assert row.revenue_direction is RevenueDirection.INCREASING


def test_negative_previous_period_is_not_comparable(analytics, make_sale):
    make_sale("2026-08-03T10:00", [(*LATTE, -1, -500)],
              event_type=OrderEventType.REFUND)
    make_sale("2026-08-10T10:00", [(*LATTE, 1, 500)])
    (row,) = analytics.menu_evidence(*CURRENT).rows
    assert row.previous_net_sales_pence == -500
    assert row.net_sales_percent_change is None
    assert row.movement_status is MovementStatus.NOT_COMPARABLE


# --- attachment evidence -----------------------------------------------------


def test_product_with_a_qualifying_attachment(analytics, make_sale):
    for day in (8, 9, 10, 11, 12):
        make_sale(f"2026-08-{day:02d}T10:00", [(*LATTE, 1, 300), (*SCONE, 1, 200)])
    rows = rows_by_name(analytics.menu_evidence(*CURRENT, min_pair_orders=5))

    attachment = rows["Latte"].strongest_attachment
    assert attachment is not None
    assert attachment.product.name == "Scone"
    assert attachment.pair_orders == 5
    assert attachment.attachment_rate_percent == 100.0
    assert attachment.lift == 1.0


def test_product_with_no_qualifying_attachment(analytics, make_sale):
    make_sale("2026-08-10T10:00", [(*LATTE, 1, 300), (*SCONE, 1, 200)])
    rows = rows_by_name(analytics.menu_evidence(*CURRENT, min_pair_orders=5))
    assert rows["Latte"].strongest_attachment is None
    assert rows["Scone"].strongest_attachment is None


def test_product_sold_alone_has_no_attachment(analytics, make_sale):
    make_sale("2026-08-10T10:00", [(*LATTE, 1, 300)])
    (row,) = analytics.menu_evidence(*CURRENT, min_pair_orders=1).rows
    assert row.strongest_attachment is None


def test_strongest_attachment_prefers_higher_lift(analytics, make_sale):
    """Toast is frequent; Scone is exclusive. Scone is the stronger signal."""
    for day in (8, 9, 10, 11, 12, 13):
        make_sale(f"2026-08-{day:02d}T10:00", [(*LATTE, 1, 300), (*TOAST, 1, 500)])
    for day in (8, 9):
        make_sale(f"2026-08-{day:02d}T11:00", [(*LATTE, 1, 300), (*SCONE, 1, 200)])
    for day in (10, 11, 12, 13):
        make_sale(f"2026-08-{day:02d}T12:00", [(*TOAST, 1, 500)])

    rows = rows_by_name(analytics.menu_evidence(*CURRENT, min_pair_orders=2))
    attachment = rows["Latte"].strongest_attachment
    assert attachment.product.name == "Scone"
    assert attachment.pair_orders == 2
    assert attachment.lift > 1.0


def test_quantity_and_duplicate_lines_do_not_multiply_attachment(
    analytics, make_sale
):
    for day in (8, 9, 10, 11, 12):
        make_sale(f"2026-08-{day:02d}T10:00",
                  [(*LATTE, 3, 900), (*SCONE, 1, 200), (*SCONE, 1, 200)])
    rows = rows_by_name(analytics.menu_evidence(*CURRENT, min_pair_orders=5))
    assert rows["Latte"].strongest_attachment.pair_orders == 5


def test_refunds_do_not_create_attachment_evidence(analytics, make_sale):
    for day in (8, 9, 10, 11, 12):
        make_sale(f"2026-08-{day:02d}T10:00", [(*LATTE, -1, -300), (*SCONE, -1, -200)],
                  event_type=OrderEventType.REFUND)
    evidence = analytics.menu_evidence(*CURRENT, min_pair_orders=1)
    assert evidence.eligible_order_count == 0
    assert all(r.strongest_attachment is None for r in evidence.rows)


# --- filtering and shape -----------------------------------------------------


def test_non_menu_kinds_are_excluded_by_default(analytics, make_sale):
    make_sale("2026-08-10T10:00",
              [(*LATTE, 1, 300),
               ("Voucher", "", 1, 1000, ProductKind.GIFT_VOUCHER),
               ("Custom Amount", "", 1, 400, ProductKind.CUSTOM_AMOUNT)])
    evidence = analytics.menu_evidence(*CURRENT)
    assert [r.product.name for r in evidence.rows] == ["Latte"]
    assert evidence.total_net_sales_pence == 300


def test_non_menu_kinds_can_be_requested(analytics, make_sale):
    make_sale("2026-08-10T10:00",
              [(*LATTE, 1, 300),
               ("Voucher", "", 1, 1000, ProductKind.GIFT_VOUCHER)])
    evidence = analytics.menu_evidence(
        *CURRENT, kinds=(ProductKind.MENU_ITEM, ProductKind.GIFT_VOUCHER)
    )
    assert {r.product.name for r in evidence.rows} == {"Latte", "Voucher"}


def test_variations_stay_separate(analytics, make_sale):
    make_sale("2026-08-10T10:00",
              [("Latte", "Regular", 1, 300), ("Latte", "Large", 1, 400)])
    evidence = analytics.menu_evidence(*CURRENT)
    assert {(r.product.name, r.product.variation) for r in evidence.rows} == {
        ("Latte", "Regular"), ("Latte", "Large")
    }


def test_shares_computed_before_limit(analytics, make_sale):
    make_sale("2026-08-10T10:00", [(*LATTE, 1, 750), (*TOAST, 1, 250)])
    evidence = analytics.menu_evidence(*CURRENT, limit=1)
    assert len(evidence.rows) == 1
    assert evidence.rows[0].share_of_menu_net_sales_percent == 75.0
    assert evidence.total_net_sales_pence == 1000


def test_empty_window(analytics):
    evidence = analytics.menu_evidence(*CURRENT)
    assert evidence.rows == []
    assert evidence.total_net_sales_pence == 0
    assert evidence.total_net_units == 0
    assert evidence.eligible_order_count == 0


def test_rows_are_ordered_by_net_sales(analytics, make_sale):
    make_sale("2026-08-10T10:00", [(*LATTE, 1, 100), (*TOAST, 1, 900), (*SCONE, 1, 500)])
    names = [r.product.name for r in analytics.menu_evidence(*CURRENT).rows]
    assert names == ["Toast", "Scone", "Latte"]


# --- no N+1 ------------------------------------------------------------------


def test_statement_count_is_independent_of_product_count(analytics, make_sale, database):
    from sqlalchemy import event

    statements: list[str] = []

    @event.listens_for(database, "before_cursor_execute")
    def capture(conn, cursor, statement, params, context, many):
        statements.append(statement)

    try:
        for index in range(3):
            make_sale(f"2026-08-1{index}T10:00", [(f"P{index}", "", 1, 100)])
        statements.clear()
        small = analytics.menu_evidence(*CURRENT)
        small_count = len(statements)

        for index in range(3, 25):
            make_sale("2026-08-10T11:00", [(f"P{index}", "", 1, 100)])
        statements.clear()
        large = analytics.menu_evidence(*CURRENT)
        large_count = len(statements)
    finally:
        event.remove(database, "before_cursor_execute", capture)

    assert len(large.rows) > len(small.rows)
    assert small_count == large_count, "statement count must not grow with products"
    assert large_count <= 6
