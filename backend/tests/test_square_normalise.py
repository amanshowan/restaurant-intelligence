"""Normalisation of Square rows into canonical records."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from app.adapters.base import IssueCode, Severity
from app.adapters.square import EXCLUDED_PII_COLUMNS, SquareAdapter, attach_items
from app.models.enums import Channel, ImportFileRole, OrderEventType, ProductKind
from app.schemas.canonical import CanonicalOrder, CanonicalOrderItem
from tests.conftest import item_row, transaction_row

UTC = ZoneInfo("UTC")
TX = ImportFileRole.TRANSACTIONS
ITEMS = ImportFileRole.ITEMS_DETAIL
SUMMARY = ImportFileRole.ITEMS_SUMMARY


def codes(result):
    return {issue.code for issue in result.issues}


# --- orders ------------------------------------------------------------------


def test_transaction_becomes_a_canonical_order(transactions_file):
    result = SquareAdapter().read(transactions_file([transaction_row()]), TX)
    (order,) = result.orders
    assert order.source == "square"
    assert order.source_order_id == "TX-1"
    assert order.source_payment_id == "PAY-1"
    assert order.occurred_at == datetime(2026, 8, 15, 11, 30, tzinfo=UTC)  # 12:30 BST
    assert order.channel is Channel.IN_STORE
    assert order.event_type is OrderEventType.PAYMENT


def test_gross_is_reconstructed_pre_discount(transactions_file):
    """Square's "Gross Sales" is ALREADY net of discounts and equals Net Sales.

    Mapping it straight through would understate gross and break the model's
    gross - discount = net invariant.
    """
    path = transactions_file([
        transaction_row(**{"Gross Sales": "£3.67", "Discounts": "-£3.68",
                           "Net Sales": "£3.67"})
    ])
    (order,) = SquareAdapter().read(path, TX).orders
    assert order.net_amount == 367
    assert order.discount_amount == 368          # stored positive
    assert order.gross_amount == 735             # the true pre-discount price
    assert order.gross_amount - order.discount_amount == order.net_amount


def test_refund_is_identified_and_keeps_negative_money(transactions_file):
    path = transactions_file([
        transaction_row(**{"Transaction ID": "TX-R", "Payment ID": "PAY-1",
                           "Event Type": "Refund", "Gross Sales": "-£7.90",
                           "Net Sales": "-£7.90"})
    ])
    (order,) = SquareAdapter().read(path, TX).orders
    assert order.event_type is OrderEventType.REFUND
    assert order.net_amount == -790


def test_refund_shares_payment_id_with_its_original(transactions_file):
    path = transactions_file([
        transaction_row(**{"Transaction ID": "TX-P", "Payment ID": "PAY-9"}),
        transaction_row(**{"Transaction ID": "TX-R", "Payment ID": "PAY-9",
                           "Event Type": "Refund", "Net Sales": "-£10.00",
                           "Gross Sales": "-£10.00"}),
    ])
    orders = SquareAdapter().read(path, TX).orders
    assert {o.source_order_id for o in orders} == {"TX-P", "TX-R"}
    assert {o.source_payment_id for o in orders} == {"PAY-9"}


def test_zero_value_transaction_is_excluded_but_counted(transactions_file):
    path = transactions_file([
        transaction_row(**{"Gross Sales": "£0.00", "Net Sales": "£0.00",
                           "Total Collected": "£0.00"})
    ])
    result = SquareAdapter().read(path, TX)
    assert result.orders == []
    assert result.rows_skipped == 1
    assert IssueCode.ZERO_VALUE_TRANSACTION in codes(result)


def test_unresolved_channel_is_skipped_with_a_reason(transactions_file):
    """A PAYMENT whose channel cannot be derived is still skipped. (Refunds
    are exempt — see the refund section below.)"""
    path = transactions_file([
        transaction_row(**{"Source": "Some New Platform", "Dining Option": ""})
    ])
    result = SquareAdapter().read(path, TX)
    assert result.orders == []
    (issue,) = [i for i in result.issues if i.code is IssueCode.UNRESOLVED_CHANNEL]
    assert issue.severity is Severity.SKIP
    assert "Some New Platform" in issue.message
    assert issue.source_order_id == "TX-1"


def test_unknown_event_type_is_skipped(transactions_file):
    path = transactions_file([transaction_row(**{"Event Type": "Chargeback"})])
    result = SquareAdapter().read(path, TX)
    assert result.orders == []
    assert IssueCode.UNKNOWN_EVENT_TYPE in codes(result)


def test_ambiguous_time_is_warned_but_still_imported(transactions_file):
    path = transactions_file([
        transaction_row(**{"Date": "2026-10-25", "Time": "01:30:00"})
    ])
    result = SquareAdapter().read(path, TX)
    assert len(result.orders) == 1                     # not skipped
    assert IssueCode.AMBIGUOUS_LOCAL_TIME in codes(result)
    assert result.rows_skipped == 0                    # WARN, not SKIP


def test_good_and_bad_rows_are_processed_independently(transactions_file):
    path = transactions_file([
        transaction_row(**{"Transaction ID": "TX-OK"}),
        transaction_row(**{"Transaction ID": "TX-BAD", "Source": "Mystery"}),
        transaction_row(**{"Transaction ID": "TX-OK2"}),
    ])
    result = SquareAdapter().read(path, TX)
    assert [o.source_order_id for o in result.orders] == ["TX-OK", "TX-OK2"]
    assert result.rows_read == 3
    assert result.rows_skipped == 1


# --- items -------------------------------------------------------------------


def test_item_becomes_a_canonical_line(items_file):
    result = SquareAdapter().read(items_file([item_row()]), ITEMS)
    (line,) = result.items
    assert line.source_order_id == "TX-1"
    assert line.quantity == 1
    assert line.line_total == 365
    assert line.unit_price == 365
    assert line.modifiers == "Whole Milk"


def test_unit_price_is_derived_from_quantity(items_file):
    path = items_file([item_row(**{"Qty": "2.0", "Product Sales": "£7.30"})])
    (line,) = SquareAdapter().read(path, ITEMS).items
    assert line.line_total == 730
    assert line.unit_price == 365


def test_variation_is_kept_separate_from_the_name(items_file):
    path = items_file([
        item_row(**{"Item": "Caffe Latte", "Price Point Name": "Large",
                    "Transaction ID": "TX-1"}),
        item_row(**{"Item": "Caffe Latte", "Price Point Name": "Regular",
                    "Transaction ID": "TX-2"}),
    ])
    products = {line.product.key for line in SquareAdapter().read(path, ITEMS).items}
    assert products == {("Caffe Latte", "Large"), ("Caffe Latte", "Regular")}
    assert all(p[0] == "Caffe Latte" for p in products)   # name never composed


def test_blank_price_point_becomes_empty_string_not_none(items_file):
    """Matches the NOT NULL DEFAULT '' column, so uniqueness works."""
    path = items_file([item_row(**{"Price Point Name": ""})])
    (line,) = SquareAdapter().read(path, ITEMS).items
    assert line.product.variation == ""


def test_literal_none_category_is_normalised_to_null(items_file):
    """Square writes the STRING "None" for uncategorised items."""
    path = items_file([item_row(**{"Category": "None", "Item": "Custom Amount"})])
    (line,) = SquareAdapter().read(path, ITEMS).items
    assert line.product.category is None


def test_product_kinds_are_classified(items_file):
    path = items_file([
        item_row(**{"Item": "Custom Amount", "Category": "None"}),
        item_row(**{"Item": "TCL - £10.00 Gift Voucher", "Category": "Uncategorised"}),
        item_row(**{"Item": "Caffe Latte"}),
    ])
    kinds = {line.product.name: line.product.kind
             for line in SquareAdapter().read(path, ITEMS).items}
    assert kinds["Custom Amount"] is ProductKind.CUSTOM_AMOUNT
    assert kinds["TCL - £10.00 Gift Voucher"] is ProductKind.GIFT_VOUCHER
    assert kinds["Caffe Latte"] is ProductKind.MENU_ITEM


def test_refund_line_keeps_negative_quantity(items_file):
    path = items_file([item_row(**{"Qty": "-1.0", "Product Sales": "-£3.65"})])
    (line,) = SquareAdapter().read(path, ITEMS).items
    assert line.quantity == -1
    assert line.line_total == -365
    assert line.unit_price == 365       # magnitude


def test_same_item_twice_on_one_order_is_kept_as_two_lines(items_file):
    """380 such groups exist in the real export, differing only by modifiers.
    Deduplicating on (transaction, item, variation) would delete real revenue."""
    path = items_file([
        item_row(**{"Item": "Two Slices of Toast", "Price Point Name": "",
                    "Modifiers Applied": "Scrambled Egg", "Product Sales": "£5.70"}),
        item_row(**{"Item": "Two Slices of Toast", "Price Point Name": "",
                    "Modifiers Applied": "Extra Cheese", "Product Sales": "£4.20"}),
    ])
    lines = SquareAdapter().read(path, ITEMS).items
    assert len(lines) == 2
    assert sum(l.line_total for l in lines) == 990


# --- joining -----------------------------------------------------------------


def test_attach_items_sets_item_count(transactions_file, items_file):
    orders = SquareAdapter().read(transactions_file([transaction_row()]), TX).orders
    items = SquareAdapter().read(
        items_file([item_row(), item_row(**{"Qty": "2.0", "Product Sales": "£7.30"})]),
        ITEMS,
    ).items
    joined, issues = attach_items(orders, items)
    assert joined[0].item_count == 3
    assert issues == []


def test_orphan_items_are_reported(transactions_file, items_file):
    orders = SquareAdapter().read(transactions_file([transaction_row()]), TX).orders
    items = SquareAdapter().read(
        items_file([item_row(**{"Transaction ID": "TX-GHOST"})]), ITEMS
    ).items
    _, issues = attach_items(orders, items)
    assert [i.code for i in issues] == [IssueCode.ORPHAN_ITEM]
    assert issues[0].source_order_id == "TX-GHOST"


# --- summary is reconciliation-only ------------------------------------------


def test_summary_produces_no_sales_records(summary_file):
    path = summary_file([
        {"Item Name": "Caffe Latte", "Item Variation": "Regular",
         "Items Sold": "10", "Product Sales": "£36.50", "Net Sales": "£36.50",
         "Units Sold": "10"}
    ])
    result = SquareAdapter().read(path, SUMMARY)
    assert result.orders == []
    assert result.items == []
    assert len(result.summary_rows) == 1
    assert result.summary_rows[0].item_name == "Caffe Latte"


# --- PII ---------------------------------------------------------------------


def test_pii_never_reaches_canonical_records(transactions_file, items_file):
    """The fixtures deliberately contain customer, card and staff columns."""
    orders = SquareAdapter().read(transactions_file([transaction_row()]), TX).orders
    items = SquareAdapter().read(items_file([item_row()]), ITEMS).items

    serialised = "".join(o.model_dump_json() for o in orders)
    serialised += "".join(i.model_dump_json() for i in items)

    for forbidden in ("A Person", "CUST-9", "Visa", "4242", "A Barista"):
        assert forbidden not in serialised


def test_canonical_models_declare_no_pii_fields():
    for model in (CanonicalOrder, CanonicalOrderItem):
        fields = set(model.model_fields)
        assert not any(
            token in name.lower()
            for name in fields
            for token in ("customer", "card", "staff", "employee", "pan")
        )


def test_excluded_pii_columns_are_not_bound_by_row_schemas():
    from app.schemas.square import SquareItemRow, SquareTransactionRow

    bound = set()
    for model in (SquareTransactionRow, SquareItemRow):
        for field in model.model_fields.values():
            if field.alias:
                bound.add(field.alias)
    assert not (bound & EXCLUDED_PII_COLUMNS)


# --- refunds: inheritance, fallback and exclusion bypass ---------------------


def test_refund_inherits_channel_from_the_payment_it_reverses(transactions_file):
    """A refund row has no usable fulfilment detail of its own — Square writes
    it from the till with a blank dining option."""
    path = transactions_file([
        transaction_row(**{"Transaction ID": "TX-P", "Payment ID": "PAY-7",
                           "Source": "Uber Eats", "Dining Option": ""}),
        transaction_row(**{"Transaction ID": "TX-R", "Payment ID": "PAY-7",
                           "Source": "Register", "Dining Option": "",
                           "Event Type": "Refund", "Net Sales": "-£10.00",
                           "Gross Sales": "-£10.00"}),
    ])
    result = SquareAdapter().read(path, TX)
    by_id = {o.source_order_id: o for o in result.orders}

    assert by_id["TX-P"].channel is Channel.DELIVERY
    assert by_id["TX-R"].channel is Channel.DELIVERY        # inherited
    assert by_id["TX-R"].event_type is OrderEventType.REFUND
    assert IssueCode.REFUND_CHANNEL_INHERITED in codes(result)


def test_refund_inheritance_works_regardless_of_row_order(transactions_file):
    """Payments are normalised in a first pass, so a refund appearing BEFORE
    its payment in the file still inherits correctly."""
    path = transactions_file([
        transaction_row(**{"Transaction ID": "TX-R", "Payment ID": "PAY-7",
                           "Source": "Register", "Dining Option": "",
                           "Event Type": "Refund", "Net Sales": "-£10.00",
                           "Gross Sales": "-£10.00"}),
        transaction_row(**{"Transaction ID": "TX-P", "Payment ID": "PAY-7",
                           "Source": "Deliveroo", "Dining Option": ""}),
    ])
    orders = {o.source_order_id: o for o in SquareAdapter().read(path, TX).orders}
    assert orders["TX-R"].channel is Channel.DELIVERY


def test_refund_outside_the_window_falls_back_to_unknown(transactions_file):
    """Payment absent AND the refund's own row is unresolvable (a till refund
    with no dining option). Preserve the money with an honest 'unknown'."""
    path = transactions_file([
        transaction_row(**{"Transaction ID": "TX-R", "Payment ID": "PAY-ABSENT",
                           "Source": "Register", "Dining Option": "",
                           "Event Type": "Refund", "Net Sales": "-£7.90",
                           "Gross Sales": "-£7.90"}),
    ])
    result = SquareAdapter().read(path, TX)
    (order,) = result.orders
    assert order.channel is Channel.UNKNOWN
    assert order.net_amount == -790
    assert IssueCode.REFUND_CHANNEL_UNKNOWN in codes(result)


def test_out_of_window_deliveroo_refund_derives_delivery(transactions_file):
    """Evidence we DO have should be used before falling back to unknown."""
    path = transactions_file([
        transaction_row(**{"Transaction ID": "TX-R", "Payment ID": "PAY-ABSENT",
                           "Source": "Deliveroo", "Dining Option": "",
                           "Event Type": "Refund", "Net Sales": "-£12.50",
                           "Gross Sales": "-£12.50"}),
    ])
    result = SquareAdapter().read(path, TX)
    (order,) = result.orders
    assert order.channel is Channel.DELIVERY
    assert order.event_type is OrderEventType.REFUND
    assert order.net_amount == -1250
    assert IssueCode.REFUND_CHANNEL_DERIVED in codes(result)
    assert IssueCode.REFUND_CHANNEL_UNKNOWN not in codes(result)


def test_out_of_window_refund_with_pick_up_derives_collection(transactions_file):
    path = transactions_file([
        transaction_row(**{"Transaction ID": "TX-R", "Payment ID": "PAY-ABSENT",
                           "Source": "Register", "Dining Option": "Pick Up",
                           "Event Type": "Refund", "Net Sales": "-£4.00",
                           "Gross Sales": "-£4.00"}),
    ])
    result = SquareAdapter().read(path, TX)
    (order,) = result.orders
    assert order.channel is Channel.COLLECTION
    assert IssueCode.REFUND_CHANNEL_DERIVED in codes(result)


def test_inheritance_beats_the_refunds_own_row(transactions_file):
    """When both are available the payment wins: it is the same commercial
    event, and the refund row's own Source is often just the till."""
    path = transactions_file([
        transaction_row(**{"Transaction ID": "TX-P", "Payment ID": "PAY-7",
                           "Source": "Uber Eats", "Dining Option": ""}),
        transaction_row(**{"Transaction ID": "TX-R", "Payment ID": "PAY-7",
                           "Source": "Register", "Dining Option": "Eat in",
                           "Event Type": "Refund", "Net Sales": "-£10.00",
                           "Gross Sales": "-£10.00"}),
    ])
    result = SquareAdapter().read(path, TX)
    by_id = {o.source_order_id: o for o in result.orders}
    assert by_id["TX-R"].channel is Channel.DELIVERY      # not in_store
    assert IssueCode.REFUND_CHANNEL_INHERITED in codes(result)
    assert IssueCode.REFUND_CHANNEL_DERIVED not in codes(result)


def test_unresolvable_refund_with_unknown_source_falls_back(transactions_file):
    path = transactions_file([
        transaction_row(**{"Transaction ID": "TX-R", "Payment ID": "",
                           "Source": "Some New Platform", "Dining Option": "",
                           "Event Type": "Refund", "Net Sales": "-£1.00",
                           "Gross Sales": "-£1.00"}),
    ])
    result = SquareAdapter().read(path, TX)
    (order,) = result.orders
    assert order.channel is Channel.UNKNOWN
    assert result.rows_skipped == 0      # preserved, never dropped


def test_refund_bypasses_the_zero_value_exclusion(transactions_file):
    """Square reports one real August refund with Net Sales £0.00 and
    Total Collected -£50.58. A value test on net sales alone would discard it."""
    path = transactions_file([
        transaction_row(**{"Transaction ID": "TX-R", "Payment ID": "PAY-X",
                           "Event Type": "Refund", "Source": "Register",
                           "Dining Option": "", "Gross Sales": "£0.00",
                           "Net Sales": "£0.00", "Total Collected": "-£50.58"}),
    ])
    result = SquareAdapter().read(path, TX)
    assert len(result.orders) == 1
    assert result.orders[0].event_type is OrderEventType.REFUND
    assert IssueCode.ZERO_VALUE_TRANSACTION not in codes(result)


def test_refund_bypasses_the_unresolved_channel_exclusion(transactions_file):
    """A Register refund with a blank dining option would be unresolvable as a
    payment; as a refund it is preserved, not skipped."""
    path = transactions_file([
        transaction_row(**{"Transaction ID": "TX-R", "Payment ID": "PAY-Y",
                           "Event Type": "Refund", "Source": "Register",
                           "Dining Option": "", "Net Sales": "-£7.90",
                           "Gross Sales": "-£7.90"}),
    ])
    result = SquareAdapter().read(path, TX)
    assert len(result.orders) == 1
    assert IssueCode.UNRESOLVED_CHANNEL not in codes(result)
    assert result.rows_skipped == 0


def test_zero_value_payments_are_still_excluded(transactions_file):
    """The refund bypass must not weaken the rule for genuine no-sale rows."""
    path = transactions_file([
        transaction_row(**{"Transaction ID": "TX-Z", "Event Type": "Payment",
                           "Gross Sales": "£0.00", "Net Sales": "£0.00"}),
    ])
    result = SquareAdapter().read(path, TX)
    assert result.orders == []
    assert IssueCode.ZERO_VALUE_TRANSACTION in codes(result)


def test_square_online_payment_normalises_to_online(transactions_file):
    path = transactions_file([
        transaction_row(**{"Source": "Square Online", "Dining Option": ""})
    ])
    (order,) = SquareAdapter().read(path, TX).orders
    assert order.channel is Channel.ONLINE


def test_refund_item_count_is_negative(transactions_file, items_file):
    """Signed item_count, so summing across orders yields NET units."""
    orders = SquareAdapter().read(transactions_file([
        transaction_row(**{"Transaction ID": "TX-P", "Payment ID": "PAY-1"}),
        transaction_row(**{"Transaction ID": "TX-R", "Payment ID": "PAY-1",
                           "Event Type": "Refund", "Net Sales": "-£3.65",
                           "Gross Sales": "-£3.65", "Dining Option": ""}),
    ]), TX).orders
    items = SquareAdapter().read(items_file([
        item_row(**{"Transaction ID": "TX-P", "Qty": "1.0"}),
        item_row(**{"Transaction ID": "TX-R", "Qty": "-1.0",
                    "Product Sales": "-£3.65"}),
    ]), ITEMS).items
    joined, _ = attach_items(orders, items)
    counts = {o.source_order_id: o.item_count for o in joined}
    assert counts == {"TX-P": 1, "TX-R": -1}
    assert sum(counts.values()) == 0        # net units after a full refund
