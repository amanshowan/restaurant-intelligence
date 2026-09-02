"""Product / menu analytics."""

from __future__ import annotations

from datetime import date

import pytest

from app.analytics.service import AnalyticsService, MovementStatus
from app.models.enums import OrderEventType, ProductKind

AUG = (date(2026, 8, 1), date(2026, 8, 31))
LATTE_R = ("Caffe Latte", "Regular")
LATTE_L = ("Caffe Latte", "Large")
TOAST = ("Toast", "")


@pytest.fixture
def analytics(session_factory) -> AnalyticsService:
    return AnalyticsService(session_factory)


def by_key(ranking):
    return {(p.totals.name, p.totals.variation): p for p in ranking.products}


# --- grain -------------------------------------------------------------------


def test_variations_stay_separate(analytics, make_sale):
    make_sale("2026-08-05T10:00", [(*LATTE_R, 1, 365)])
    make_sale("2026-08-05T11:00", [(*LATTE_L, 1, 420)])
    ranking = analytics.products(*AUG)

    keyed = by_key(ranking)
    assert set(keyed) == {LATTE_R, LATTE_L}
    assert keyed[LATTE_R].totals.net_sales_pence == 365
    assert keyed[LATTE_L].totals.net_sales_pence == 420
    assert keyed[LATTE_R].totals.product_id != keyed[LATTE_L].totals.product_id


def test_name_and_variation_are_both_returned(analytics, make_sale):
    make_sale("2026-08-05T10:00", [(*LATTE_L, 1, 420)])
    (product,) = analytics.products(*AUG).products
    assert product.totals.name == "Caffe Latte"
    assert product.totals.variation == "Large"


# --- ranking -----------------------------------------------------------------


def test_ranked_by_net_sales(analytics, make_sale):
    make_sale("2026-08-05T10:00", [(*LATTE_R, 1, 100)])
    make_sale("2026-08-05T11:00", [(*TOAST, 1, 900)])
    make_sale("2026-08-05T12:00", [(*LATTE_L, 1, 500)])
    ranking = analytics.products(*AUG, sort="net_sales")
    assert [p.totals.name for p in ranking.products] == ["Toast", "Caffe Latte", "Caffe Latte"]
    assert [p.totals.net_sales_pence for p in ranking.products] == [900, 500, 100]


def test_ranked_by_units(analytics, make_sale):
    make_sale("2026-08-05T10:00", [(*LATTE_R, 9, 900)])
    make_sale("2026-08-05T11:00", [(*TOAST, 2, 1800)])
    ranking = analytics.products(*AUG, sort="net_units")
    assert [p.totals.name for p in ranking.products] == ["Caffe Latte", "Toast"]
    assert [p.totals.net_units for p in ranking.products] == [9, 2]


def test_ranked_by_discounts(analytics, make_sale):
    make_sale("2026-08-05T10:00", [(*LATTE_R, 1, 1000)], discount=300)
    make_sale("2026-08-05T11:00", [(*TOAST, 1, 1000)], discount=50)
    ranking = analytics.products(*AUG, sort="discounts")
    assert [p.totals.discounts_pence for p in ranking.products] == [300, 50]


def test_limit_applies_after_shares_are_computed(analytics, make_sale):
    make_sale("2026-08-05T10:00", [(*LATTE_R, 1, 750)])
    make_sale("2026-08-05T11:00", [(*TOAST, 1, 250)])
    ranking = analytics.products(*AUG, limit=1)
    assert len(ranking.products) == 1
    # Share is of the whole menu (1000), not of the single row returned.
    assert ranking.products[0].share_of_net_sales_percent == 75.0
    assert ranking.total_net_sales_pence == 1000


# --- discounts (allocated) ---------------------------------------------------


def test_discount_on_one_line_stays_on_that_product(analytics, make_sale):
    """The case apportioning got wrong: a £2.00 discount applied to ONE item of
    a two-item basket belongs entirely to that item, not split 75/25 by value."""
    make_sale(
        "2026-08-05T10:00",
        [(*LATTE_R, 1, 750, ProductKind.MENU_ITEM, 200),
         (*TOAST, 1, 250, ProductKind.MENU_ITEM, 0)],
        discount=200,
    )
    keyed = by_key(analytics.products(*AUG))
    assert keyed[LATTE_R].totals.discounts_pence == 200
    assert keyed[TOAST].totals.discounts_pence == 0
    assert keyed[LATTE_R].totals.net_sales_pence == 550
    assert keyed[TOAST].totals.net_sales_pence == 250


def test_several_differently_discounted_lines_keep_their_own_values(
    analytics, make_sale
):
    make_sale(
        "2026-08-05T10:00",
        [(*LATTE_R, 1, 500, ProductKind.MENU_ITEM, 125),
         (*LATTE_L, 1, 600, ProductKind.MENU_ITEM, 60),
         (*TOAST, 1, 400, ProductKind.MENU_ITEM, 0)],
        discount=185,
    )
    keyed = by_key(analytics.products(*AUG))
    assert keyed[LATTE_R].totals.discounts_pence == 125
    assert keyed[LATTE_L].totals.discounts_pence == 60
    assert keyed[TOAST].totals.discounts_pence == 0
    assert sum(k.totals.discounts_pence for k in keyed.values()) == 185


def test_refund_line_discount_keeps_the_refund_sign(analytics, make_sale):
    """A refund of a discounted sale reverses the discount too."""
    make_sale("2026-08-05T10:00",
              [(*LATTE_R, 1, 500, ProductKind.MENU_ITEM, 100)], discount=100)
    make_sale("2026-08-06T10:00",
              [(*LATTE_R, -1, -500, ProductKind.MENU_ITEM, -100)],
              discount=-100, event_type=OrderEventType.REFUND)
    (product,) = analytics.products(*AUG).products
    assert product.totals.gross_sales_pence == 0
    assert product.totals.discounts_pence == 0
    assert product.totals.net_sales_pence == 0
    assert product.totals.payment_order_count == 1


def test_no_apportionment_residual_across_many_discounted_orders(
    analytics, make_sale
):
    """Apportioning rounded per line and drifted by pennies. Reading the source
    value cannot drift, whatever the line values are."""
    for i in range(1, 31):
        make_sale(
            f"2026-08-{i:02d}T10:00",
            [(*LATTE_R, 1, 333, ProductKind.MENU_ITEM, 111),
             (*TOAST, 1, 667, ProductKind.MENU_ITEM, 0)],
            discount=111,
        )
    keyed = by_key(analytics.products(*AUG))
    assert keyed[LATTE_R].totals.discounts_pence == 30 * 111
    assert keyed[TOAST].totals.discounts_pence == 0
    total = sum(k.totals.discounts_pence for k in keyed.values())
    assert total == 30 * 111, "exact, with no rounding residual"


def test_single_line_discount(analytics, make_sale):
    make_sale("2026-08-05T10:00", [(*LATTE_R, 2, 1000)], discount=100)
    (product,) = analytics.products(*AUG).products
    assert product.totals.gross_sales_pence == 1000
    assert product.totals.discounts_pence == 100
    assert product.totals.net_sales_pence == 900


def test_gross_minus_discount_equals_net(analytics, make_sale):
    make_sale("2026-08-05T10:00",
              [(*LATTE_R, 1, 500, ProductKind.MENU_ITEM, 70),
               (*TOAST, 1, 500, ProductKind.MENU_ITEM, 100)],
              discount=170)
    for p in analytics.products(*AUG).products:
        t = p.totals
        assert t.gross_sales_pence - t.discounts_pence == t.net_sales_pence


# --- order counting ----------------------------------------------------------


def test_multiple_quantities_on_one_order_count_as_one_order(analytics, make_sale):
    make_sale("2026-08-05T10:00", [(*LATTE_R, 3, 1095)])
    (product,) = analytics.products(*AUG).products
    assert product.totals.net_units == 3
    assert product.totals.payment_order_count == 1


def test_same_product_on_two_orders_counts_twice(analytics, make_sale):
    make_sale("2026-08-05T10:00", [(*LATTE_R, 1, 365)])
    make_sale("2026-08-06T10:00", [(*LATTE_R, 1, 365)])
    (product,) = analytics.products(*AUG).products
    assert product.totals.payment_order_count == 2


def test_product_appearing_twice_on_one_order_counts_one_order(analytics, make_sale):
    """Two lines of the same product differing only by modifiers."""
    make_sale("2026-08-05T10:00", [(*TOAST, 1, 570), (*TOAST, 1, 420)])
    (product,) = analytics.products(*AUG).products
    assert product.totals.payment_order_count == 1
    assert product.totals.net_units == 2
    assert product.totals.gross_sales_pence == 990


# --- refunds -----------------------------------------------------------------


def test_refund_reduces_product_revenue_and_units(analytics, make_sale):
    make_sale("2026-08-05T10:00", [(*LATTE_R, 2, 730)])
    make_sale("2026-08-06T10:00", [(*LATTE_R, -1, -365)],
              event_type=OrderEventType.REFUND)
    (product,) = analytics.products(*AUG).products
    assert product.totals.net_sales_pence == 365
    assert product.totals.net_units == 1


def test_refund_event_does_not_increase_payment_order_count(analytics, make_sale):
    make_sale("2026-08-05T10:00", [(*LATTE_R, 1, 365)])
    make_sale("2026-08-06T10:00", [(*LATTE_R, -1, -365)],
              event_type=OrderEventType.REFUND)
    (product,) = analytics.products(*AUG).products
    assert product.totals.payment_order_count == 1
    assert product.totals.net_sales_pence == 0
    assert product.totals.net_units == 0


def test_refund_only_product_has_no_selling_price(analytics, make_sale):
    make_sale("2026-08-05T10:00", [(*LATTE_R, -1, -365)],
              event_type=OrderEventType.REFUND)
    (product,) = analytics.products(*AUG).products
    assert product.totals.net_units == -1
    assert product.totals.average_selling_price_pence is None
    assert product.totals.payment_order_count == 0


def test_average_selling_price(analytics, make_sale):
    make_sale("2026-08-05T10:00", [(*LATTE_R, 4, 1460)])
    (product,) = analytics.products(*AUG).products
    assert product.totals.average_selling_price_pence == 365


# --- shares ------------------------------------------------------------------


def test_shares_of_net_sales_and_units(analytics, make_sale):
    make_sale("2026-08-05T10:00", [(*LATTE_R, 3, 750)])
    make_sale("2026-08-05T11:00", [(*TOAST, 1, 250)])
    keyed = by_key(analytics.products(*AUG))
    assert keyed[LATTE_R].share_of_net_sales_percent == 75.0
    assert keyed[TOAST].share_of_net_sales_percent == 25.0
    assert keyed[LATTE_R].share_of_units_percent == 75.0


def test_shares_are_null_when_totals_are_not_positive(analytics, make_sale):
    make_sale("2026-08-05T10:00", [(*LATTE_R, -1, -365)],
              event_type=OrderEventType.REFUND)
    (product,) = analytics.products(*AUG).products
    assert product.share_of_net_sales_percent is None
    assert product.share_of_units_percent is None


def test_empty_period(analytics):
    ranking = analytics.products(*AUG)
    assert ranking.products == []
    assert ranking.total_net_sales_pence == 0
    assert ranking.total_net_units == 0


# --- kind filtering ----------------------------------------------------------


def test_gift_vouchers_are_excluded_by_default(analytics, make_sale):
    make_sale("2026-08-05T10:00", [(*LATTE_R, 1, 365)])
    make_sale("2026-08-05T11:00",
              [("Gift Voucher", "Regular", 1, 1000, ProductKind.GIFT_VOUCHER)])
    ranking = analytics.products(*AUG)
    assert [p.totals.name for p in ranking.products] == ["Caffe Latte"]
    assert ranking.total_net_sales_pence == 365      # voucher excluded from base


def test_custom_amount_is_excluded_by_default(analytics, make_sale):
    make_sale("2026-08-05T10:00", [(*LATTE_R, 1, 365)])
    make_sale("2026-08-05T11:00",
              [("Custom Amount", "", 1, 400, ProductKind.CUSTOM_AMOUNT)])
    assert [p.totals.name for p in analytics.products(*AUG).products] == ["Caffe Latte"]


def test_non_menu_kinds_can_be_requested_explicitly(analytics, make_sale):
    make_sale("2026-08-05T10:00", [(*LATTE_R, 1, 365)])
    make_sale("2026-08-05T11:00",
              [("Gift Voucher", "Regular", 1, 1000, ProductKind.GIFT_VOUCHER)])
    ranking = analytics.products(
        *AUG, kinds=(ProductKind.MENU_ITEM, ProductKind.GIFT_VOUCHER)
    )
    assert {p.totals.name for p in ranking.products} == {"Caffe Latte", "Gift Voucher"}
    assert ranking.total_net_sales_pence == 1365


def test_only_non_menu_kinds_can_be_requested(analytics, make_sale):
    make_sale("2026-08-05T10:00", [(*LATTE_R, 1, 365)])
    make_sale("2026-08-05T11:00",
              [("Gift Voucher", "Regular", 1, 1000, ProductKind.GIFT_VOUCHER)])
    ranking = analytics.products(*AUG, kinds=(ProductKind.GIFT_VOUCHER,))
    assert [p.totals.name for p in ranking.products] == ["Gift Voucher"]


# --- trend -------------------------------------------------------------------


def test_trend_is_zero_filled_daily(analytics, make_sale, product_id):
    make_sale("2026-08-01T10:00", [(*LATTE_R, 1, 100)])
    make_sale("2026-08-04T10:00", [(*LATTE_R, 2, 400)])
    trend = analytics.product_trend(
        product_id(*LATTE_R), date(2026, 8, 1), date(2026, 8, 5), "day"
    )
    assert [b.period_start for b in trend.buckets] == [
        date(2026, 8, d) for d in range(1, 6)
    ]
    assert [b.net_sales_pence for b in trend.buckets] == [100, 0, 0, 400, 0]
    assert trend.product.net_sales_pence == 500
    assert trend.product.net_units == 3


def test_trend_weekly_is_monday_based(analytics, make_sale, product_id):
    make_sale("2026-08-05T10:00", [(*LATTE_R, 1, 100)])     # Wednesday
    trend = analytics.product_trend(
        product_id(*LATTE_R), date(2026, 8, 5), date(2026, 8, 7), "week"
    )
    assert [b.period_start for b in trend.buckets] == [date(2026, 8, 3)]


def test_trend_excludes_other_products(analytics, make_sale, product_id):
    make_sale("2026-08-01T10:00", [(*LATTE_R, 1, 100), (*TOAST, 1, 900)])
    trend = analytics.product_trend(
        product_id(*LATTE_R), date(2026, 8, 1), date(2026, 8, 1), "day"
    )
    assert trend.buckets[0].net_sales_pence == 100


def test_trend_for_unknown_product_is_none(analytics):
    assert analytics.product_trend(999999, *AUG, "day") is None


# --- timezone inheritance ----------------------------------------------------


def test_bst_boundary_is_inherited(analytics, make_sale, product_id):
    """00:30 BST on 1 Aug is 23:30 UTC on 31 Jul; it belongs to August."""
    make_sale("2026-08-01T00:30", [(*LATTE_R, 1, 500)])
    make_sale("2026-07-31T23:30", [(*LATTE_R, 1, 999)])
    ranking = analytics.products(*AUG)
    assert ranking.products[0].totals.net_sales_pence == 500

    trend = analytics.product_trend(product_id(*LATTE_R), *AUG, "day")
    active = [b for b in trend.buckets if b.net_sales_pence]
    assert [b.period_start for b in active] == [date(2026, 8, 1)]


def test_gmt_boundary_is_inherited(analytics, make_sale):
    make_sale("2026-01-01T00:30", [(*LATTE_R, 1, 500)])
    make_sale("2025-12-31T23:30", [(*LATTE_R, 1, 999)])
    ranking = analytics.products(date(2026, 1, 1), date(2026, 1, 31))
    assert ranking.products[0].totals.net_sales_pence == 500


# --- movers ------------------------------------------------------------------


def test_previous_window_is_equal_length_and_immediately_prior(analytics):
    movers = analytics.product_movers(date(2026, 8, 15), date(2026, 8, 31))
    assert movers.window.days == 17
    assert movers.previous_window.days == 17
    assert movers.previous_window.end_date == date(2026, 8, 14)
    assert movers.previous_window.start_date == date(2026, 7, 29)


def test_growth_percentage(analytics, make_sale):
    make_sale("2026-08-01T10:00", [(*LATTE_R, 1, 1000)])    # previous period
    make_sale("2026-08-09T10:00", [(*LATTE_R, 1, 1500)])    # current period
    movers = analytics.product_movers(date(2026, 8, 8), date(2026, 8, 14))

    (m,) = movers.movements
    assert m.previous_net_sales_pence == 1000
    assert m.current_net_sales_pence == 1500
    assert m.net_sales_change_pence == 500
    assert m.net_sales_percent_change == 50.0
    assert m.status is MovementStatus.COMPARABLE


def test_decline_percentage(analytics, make_sale):
    make_sale("2026-08-01T10:00", [(*LATTE_R, 4, 1000)])
    make_sale("2026-08-09T10:00", [(*LATTE_R, 1, 250)])
    (m,) = analytics.product_movers(date(2026, 8, 8), date(2026, 8, 14)).movements
    assert m.net_sales_percent_change == -75.0
    assert m.net_units_change == -3


def test_new_product_has_no_percentage(analytics, make_sale):
    """No previous sales is not infinite growth."""
    make_sale("2026-08-09T10:00", [(*LATTE_R, 1, 500)])
    (m,) = analytics.product_movers(date(2026, 8, 8), date(2026, 8, 14)).movements
    assert m.previous_net_sales_pence == 0
    assert m.net_sales_percent_change is None
    assert m.status is MovementStatus.NEW_IN_PERIOD
    assert m.net_sales_change_pence == 500


def test_disappeared_product_is_a_well_defined_minus_100_percent(
    analytics, make_sale
):
    """Falling to zero FROM a positive base is comparable, not undefined."""
    make_sale("2026-08-01T10:00", [(*LATTE_R, 1, 500)])
    (m,) = analytics.product_movers(date(2026, 8, 8), date(2026, 8, 14)).movements
    assert m.current_net_sales_pence == 0
    assert m.previous_net_sales_pence == 500
    assert m.net_sales_change_pence == -500
    assert m.net_sales_percent_change == -100.0
    assert m.status is MovementStatus.COMPARABLE


def test_money_fields_are_integers_not_decimals(analytics, make_sale):
    """PostgreSQL SUM() over bigint returns NUMERIC; money must stay int."""
    make_sale("2026-08-05T10:00", [(*LATTE_R, 1, 750), (*TOAST, 1, 250)],
              discount=200)
    for p in analytics.products(*AUG).products:
        for field in ("gross_sales_pence", "discounts_pence", "net_sales_pence",
                      "net_units", "payment_order_count"):
            assert type(getattr(p.totals, field)) is int, field


def test_negative_previous_period_is_not_comparable(analytics, make_sale):
    make_sale("2026-08-01T10:00", [(*LATTE_R, -1, -500)],
              event_type=OrderEventType.REFUND)
    make_sale("2026-08-09T10:00", [(*LATTE_R, 1, 500)])
    (m,) = analytics.product_movers(date(2026, 8, 8), date(2026, 8, 14)).movements
    assert m.previous_net_sales_pence == -500
    assert m.net_sales_percent_change is None
    assert m.status is MovementStatus.NOT_COMPARABLE


def test_movers_sorted_by_absolute_change(analytics, make_sale):
    make_sale("2026-08-01T10:00", [(*LATTE_R, 1, 1000), (*TOAST, 1, 100)])
    make_sale("2026-08-09T10:00", [(*LATTE_R, 1, 100), (*TOAST, 1, 300)])
    movements = analytics.product_movers(
        date(2026, 8, 8), date(2026, 8, 14)
    ).movements
    assert [m.name for m in movements] == ["Caffe Latte", "Toast"]
    assert movements[0].net_sales_change_pence == -900
    assert movements[1].net_sales_change_pence == 200


def test_movers_respects_kind_filter(analytics, make_sale):
    make_sale("2026-08-09T10:00",
              [("Gift Voucher", "Regular", 1, 1000, ProductKind.GIFT_VOUCHER)])
    assert analytics.product_movers(date(2026, 8, 8), date(2026, 8, 14)).movements == []
