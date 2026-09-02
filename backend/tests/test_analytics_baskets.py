"""Basket, co-purchase and attachment analytics."""

from __future__ import annotations

from datetime import date

import pytest

from app.analytics.service import AnalyticsService
from app.models.enums import OrderEventType, ProductKind

AUG = (date(2026, 8, 1), date(2026, 8, 31))
A, B, C = ("Latte", "Regular"), ("Toast", ""), ("Muffin", "")


@pytest.fixture
def analytics(session_factory) -> AnalyticsService:
    return AnalyticsService(session_factory)


def pair_map(analysis):
    return {
        frozenset(
            [(p.counts.a.name, p.counts.a.variation),
             (p.counts.b.name, p.counts.b.variation)]
        ): p
        for p in analysis.pairs
    }


# --- pair construction -------------------------------------------------------


def test_a_pair_appears_exactly_once(analytics, make_sale):
    make_sale("2026-08-05T10:00", [(*A, 1, 300), (*B, 1, 500)])
    analysis = analytics.product_pairs(*AUG)
    assert len(analysis.pairs) == 1
    assert analysis.qualifying_pair_count == 1


def test_no_self_pairs(analytics, make_sale):
    make_sale("2026-08-05T10:00", [(*A, 3, 900)])
    analysis = analytics.product_pairs(*AUG)
    assert analysis.pairs == []
    for p in analysis.pairs:
        assert p.counts.a.product_id != p.counts.b.product_id


def test_three_products_produce_three_unordered_pairs(analytics, make_sale):
    make_sale("2026-08-05T10:00", [(*A, 1, 300), (*B, 1, 500), (*C, 1, 200)])
    analysis = analytics.product_pairs(*AUG)
    assert len(analysis.pairs) == 3
    assert set(pair_map(analysis)) == {
        frozenset([A, B]), frozenset([A, C]), frozenset([B, C])
    }
    assert all(p.counts.pair_orders == 1 for p in analysis.pairs)


def test_quantity_does_not_multiply_co_occurrence(analytics, make_sale):
    """Three lattes and two toasts on one order is still one co-occurrence."""
    make_sale("2026-08-05T10:00", [(*A, 3, 900), (*B, 2, 1000)])
    (pair,) = analytics.product_pairs(*AUG).pairs
    assert pair.counts.pair_orders == 1
    assert pair.counts.a_orders == 1
    assert pair.counts.b_orders == 1


def test_duplicate_lines_of_one_product_do_not_multiply_pairs(analytics, make_sale):
    """Two lines of the same product differing only by modifiers."""
    make_sale("2026-08-05T10:00", [(*B, 1, 570), (*B, 1, 420), (*A, 1, 300)])
    (pair,) = analytics.product_pairs(*AUG).pairs
    assert pair.counts.pair_orders == 1
    assert pair.counts.b_orders == 1


def test_variations_remain_separate(analytics, make_sale):
    make_sale("2026-08-05T10:00",
              [("Latte", "Regular", 1, 300), ("Latte", "Large", 1, 400)])
    analysis = analytics.product_pairs(*AUG)
    assert len(analysis.pairs) == 1
    (pair,) = analysis.pairs
    assert {pair.counts.a.variation, pair.counts.b.variation} == {"Regular", "Large"}
    assert analysis.distinct_product_count == 2


# --- eligibility -------------------------------------------------------------


def test_refunds_do_not_create_or_cancel_relationships(analytics, make_sale):
    make_sale("2026-08-05T10:00", [(*A, 1, 300), (*B, 1, 500)])
    make_sale("2026-08-06T10:00", [(*A, -1, -300), (*B, -1, -500)],
              event_type=OrderEventType.REFUND)
    analysis = analytics.product_pairs(*AUG)
    (pair,) = analysis.pairs
    assert pair.counts.pair_orders == 1          # not 2, not 0
    assert analysis.eligible_order_count == 1


def test_refund_only_period_has_no_pairs(analytics, make_sale):
    make_sale("2026-08-05T10:00", [(*A, -1, -300), (*B, -1, -500)],
              event_type=OrderEventType.REFUND)
    analysis = analytics.product_pairs(*AUG)
    assert analysis.pairs == []
    assert analysis.eligible_order_count == 0


def test_gift_vouchers_are_excluded_by_default(analytics, make_sale):
    make_sale("2026-08-05T10:00",
              [(*A, 1, 300),
               ("Gift Voucher", "", 1, 1000, ProductKind.GIFT_VOUCHER)])
    assert analytics.product_pairs(*AUG).pairs == []


def test_custom_amounts_are_excluded_by_default(analytics, make_sale):
    make_sale("2026-08-05T10:00",
              [(*A, 1, 300),
               ("Custom Amount", "", 1, 400, ProductKind.CUSTOM_AMOUNT)])
    assert analytics.product_pairs(*AUG).pairs == []


def test_non_menu_kinds_can_be_included_explicitly(analytics, make_sale):
    make_sale("2026-08-05T10:00",
              [(*A, 1, 300),
               ("Gift Voucher", "", 1, 1000, ProductKind.GIFT_VOUCHER)])
    analysis = analytics.product_pairs(
        *AUG, kinds=(ProductKind.MENU_ITEM, ProductKind.GIFT_VOUCHER)
    )
    assert len(analysis.pairs) == 1


def test_eligible_count_excludes_orders_with_no_included_products(
    analytics, make_sale
):
    make_sale("2026-08-05T10:00", [(*A, 1, 300), (*B, 1, 500)])
    make_sale("2026-08-06T10:00",
              [("Gift Voucher", "", 1, 1000, ProductKind.GIFT_VOUCHER)])
    assert analytics.product_pairs(*AUG).eligible_order_count == 1


# --- metrics -----------------------------------------------------------------


def test_support_confidence_and_lift(analytics, make_sale):
    """Four orders: A+B twice, A alone once, B alone once.

      eligible = 4, A = 3, B = 3, both = 2
      support     = 2/4  = 50%
      conf A->B   = 2/3  = 66.6667%
      conf B->A   = 2/3  = 66.6667%
      lift        = (2*4)/(3*3) = 0.8889
    """
    make_sale("2026-08-01T10:00", [(*A, 1, 300), (*B, 1, 500)])
    make_sale("2026-08-02T10:00", [(*A, 1, 300), (*B, 1, 500)])
    make_sale("2026-08-03T10:00", [(*A, 1, 300), (*C, 1, 200)])
    make_sale("2026-08-04T10:00", [(*B, 1, 500), (*C, 1, 200)])

    analysis = analytics.product_pairs(*AUG)
    assert analysis.eligible_order_count == 4
    pair = pair_map(analysis)[frozenset([A, B])]
    assert pair.counts.pair_orders == 2
    assert pair.counts.a_orders == 3
    assert pair.counts.b_orders == 3
    assert pair.metrics.support_percent == 50.0
    assert pair.metrics.confidence_a_to_b_percent == pytest.approx(66.6667)
    assert pair.metrics.confidence_b_to_a_percent == pytest.approx(66.6667)
    assert pair.metrics.lift == pytest.approx(0.8889)


def test_asymmetric_confidence(analytics, make_sale):
    """B always comes with A; A often comes without B.

      A = 3, B = 1, both = 1
      conf A->B = 1/3 = 33.3333%   conf B->A = 1/1 = 100%
    """
    make_sale("2026-08-01T10:00", [(*A, 1, 300), (*B, 1, 500)])
    make_sale("2026-08-02T10:00", [(*A, 1, 300), (*C, 1, 200)])
    make_sale("2026-08-03T10:00", [(*A, 1, 300), (*C, 1, 200)])

    pair = pair_map(analytics.product_pairs(*AUG))[frozenset([A, B])]
    assert pair.metrics.confidence_a_to_b_percent == pytest.approx(33.3333)
    assert pair.metrics.confidence_b_to_a_percent == 100.0


def test_lift_above_one_for_products_that_travel_together(analytics, make_sale):
    make_sale("2026-08-01T10:00", [(*A, 1, 300), (*B, 1, 500)])
    make_sale("2026-08-02T10:00", [(*A, 1, 300), (*B, 1, 500)])
    make_sale("2026-08-03T10:00", [(*C, 1, 200)])
    make_sale("2026-08-04T10:00", [(*C, 1, 200)])
    pair = pair_map(analytics.product_pairs(*AUG))[frozenset([A, B])]
    # eligible 4, A 2, B 2, both 2 -> (2*4)/(2*2) = 2.0
    assert pair.metrics.lift == 2.0


def test_metrics_are_none_on_an_empty_period(analytics):
    analysis = analytics.product_pairs(*AUG)
    assert analysis.pairs == []
    assert analysis.eligible_order_count == 0
    assert analysis.distinct_product_count == 0
    assert analysis.qualifying_pair_count == 0


# --- filtering and ordering --------------------------------------------------


def test_minimum_pair_order_threshold(analytics, make_sale):
    make_sale("2026-08-01T10:00", [(*A, 1, 300), (*B, 1, 500)])
    make_sale("2026-08-02T10:00", [(*A, 1, 300), (*B, 1, 500)])
    make_sale("2026-08-03T10:00", [(*A, 1, 300), (*C, 1, 200)])

    assert len(analytics.product_pairs(*AUG, min_pair_orders=1).pairs) == 2
    strict = analytics.product_pairs(*AUG, min_pair_orders=2)
    assert len(strict.pairs) == 1
    assert strict.qualifying_pair_count == 1
    assert set(pair_map(strict)) == {frozenset([A, B])}


def test_sorting_by_pair_orders_then_lift(analytics, make_sale):
    make_sale("2026-08-01T10:00", [(*A, 1, 300), (*B, 1, 500)])
    make_sale("2026-08-02T10:00", [(*A, 1, 300), (*B, 1, 500)])
    make_sale("2026-08-03T10:00", [(*C, 1, 200), ("Rare", "", 1, 100)])

    by_count = analytics.product_pairs(*AUG, sort="pair_orders")
    assert by_count.pairs[0].counts.pair_orders == 2
    by_lift = analytics.product_pairs(*AUG, sort="lift")
    # The one-off pair is perfectly correlated, so it out-lifts the frequent one.
    assert by_lift.pairs[0].metrics.lift >= by_count.pairs[0].metrics.lift


def test_sorting_is_stable_across_calls(analytics, make_sale):
    for day in range(1, 6):
        make_sale(f"2026-08-0{day}T10:00",
                  [(*A, 1, 300), (*B, 1, 500), (*C, 1, 200)])
    first = analytics.product_pairs(*AUG)
    second = analytics.product_pairs(*AUG)
    order = lambda a: [(p.counts.a.name, p.counts.b.name) for p in a.pairs]
    assert order(first) == order(second)


def test_limit_applies_after_the_qualifying_count(analytics, make_sale):
    make_sale("2026-08-01T10:00", [(*A, 1, 300), (*B, 1, 500), (*C, 1, 200)])
    analysis = analytics.product_pairs(*AUG, limit=1)
    assert len(analysis.pairs) == 1
    assert analysis.qualifying_pair_count == 3


# --- timezone ----------------------------------------------------------------


def test_bst_boundary(analytics, make_sale):
    """00:30 BST on 1 Aug is 23:30 UTC on 31 Jul; the basket belongs to August."""
    make_sale("2026-08-01T00:30", [(*A, 1, 300), (*B, 1, 500)])
    make_sale("2026-07-31T23:30", [(*A, 1, 300), (*C, 1, 200)])
    analysis = analytics.product_pairs(*AUG)
    assert set(pair_map(analysis)) == {frozenset([A, B])}


def test_gmt_boundary(analytics, make_sale):
    make_sale("2026-01-01T00:30", [(*A, 1, 300), (*B, 1, 500)])
    make_sale("2025-12-31T23:30", [(*A, 1, 300), (*C, 1, 200)])
    analysis = analytics.product_pairs(date(2026, 1, 1), date(2026, 1, 31))
    assert set(pair_map(analysis)) == {frozenset([A, B])}


# --- attachments -------------------------------------------------------------


def test_attachments_for_an_anchor(analytics, make_sale, product_id):
    make_sale("2026-08-01T10:00", [(*A, 1, 300), (*B, 1, 500)])
    make_sale("2026-08-02T10:00", [(*A, 1, 300), (*B, 1, 500)])
    make_sale("2026-08-03T10:00", [(*A, 1, 300), (*C, 1, 200)])
    make_sale("2026-08-04T10:00", [(*B, 1, 500)])

    analysis = analytics.product_attachments(product_id(*A), *AUG)
    assert analysis.anchor.name == "Latte"
    assert analysis.anchor_order_count == 3
    assert analysis.eligible_order_count == 4

    attached = {a.product.name: a for a in analysis.attachments}
    assert attached["Toast"].pair_orders == 2
    assert attached["Toast"].product_orders == 3
    assert attached["Toast"].attachment_rate_percent == pytest.approx(66.6667)
    assert attached["Toast"].reverse_attachment_rate_percent == pytest.approx(66.6667)
    assert attached["Muffin"].pair_orders == 1
    assert attached["Muffin"].attachment_rate_percent == pytest.approx(33.3333)
    assert attached["Muffin"].reverse_attachment_rate_percent == 100.0


def test_attachments_never_include_the_anchor_itself(analytics, make_sale, product_id):
    make_sale("2026-08-01T10:00", [(*A, 3, 900), (*B, 1, 500)])
    analysis = analytics.product_attachments(product_id(*A), *AUG)
    assert [a.product.name for a in analysis.attachments] == ["Toast"]


def test_anchor_with_no_attachments(analytics, make_sale, product_id):
    make_sale("2026-08-01T10:00", [(*A, 1, 300)])
    analysis = analytics.product_attachments(product_id(*A), *AUG)
    assert analysis.anchor_order_count == 1
    assert analysis.attachments == []


def test_anchor_never_sold_in_the_window(analytics, make_sale, product_id):
    make_sale("2026-01-05T10:00", [(*A, 1, 300)])
    analysis = analytics.product_attachments(product_id(*A), *AUG)
    assert analysis.anchor_order_count == 0
    assert analysis.attachments == []


def test_unknown_anchor_returns_none(analytics):
    assert analytics.product_attachments(999999, *AUG) is None


def test_attachment_minimum_threshold(analytics, make_sale, product_id):
    make_sale("2026-08-01T10:00", [(*A, 1, 300), (*B, 1, 500)])
    make_sale("2026-08-02T10:00", [(*A, 1, 300), (*B, 1, 500)])
    make_sale("2026-08-03T10:00", [(*A, 1, 300), (*C, 1, 200)])
    analysis = analytics.product_attachments(
        product_id(*A), *AUG, min_pair_orders=2
    )
    assert [a.product.name for a in analysis.attachments] == ["Toast"]


def test_attachments_exclude_refunds(analytics, make_sale, product_id):
    make_sale("2026-08-01T10:00", [(*A, 1, 300), (*B, 1, 500)])
    make_sale("2026-08-02T10:00", [(*A, -1, -300), (*C, -1, -200)],
              event_type=OrderEventType.REFUND)
    analysis = analytics.product_attachments(product_id(*A), *AUG)
    assert [a.product.name for a in analysis.attachments] == ["Toast"]
    assert analysis.anchor_order_count == 1
