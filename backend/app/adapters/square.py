"""Square export adapter.

Reads Square's Transactions, Items Detail and Items Summary exports and maps
them onto canonical records (ARCHITECTURE.md §2). Knows nothing about the
database.

Format note: Square names these files `.csv`, but they are UTF-16 LE with a
BOM and TAB delimited. Reading one with CSV defaults yields a single garbage
column rather than an error, so the format is asserted rather than assumed.
"""

from __future__ import annotations

import csv
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from app.adapters.base import (
    IssueCode,
    ParseResult,
    RowIssue,
    Severity,
    SourceAdapter,
    SourceFormatError,
    SourceSchemaError,
)
from app.adapters.parsing import (
    MoneyParseError,
    NonexistentLocalTime,
    QuantityParseError,
    TimeZoneError,
    parse_local_instant,
    parse_money_to_pence,
    parse_quantity,
    unit_price_pence,
)
from app.models.enums import Channel, ImportFileRole, OrderEventType, ProductKind
from app.schemas.canonical import CanonicalOrder, CanonicalOrderItem, CanonicalProduct
from app.schemas.square import SquareItemRow, SquareSummaryRow, SquareTransactionRow

#: UTF-16 byte-order marks. Square writes little-endian; big-endian is accepted
#: because the marker is unambiguous and rejecting it would be gratuitous.
_BOM_UTF16_LE = b"\xff\xfe"
_BOM_UTF16_BE = b"\xfe\xff"
_BOM_UTF8 = b"\xef\xbb\xbf"

DELIMITER = "\t"

REQUIRED_COLUMNS: dict[ImportFileRole, frozenset[str]] = {
    ImportFileRole.TRANSACTIONS: frozenset(
        {
            "Date", "Time", "Time Zone", "Gross Sales", "Discounts", "Net Sales",
            "Transaction ID", "Event Type",
            # "Source" is required for two reasons. It is needed for channel
            # derivation, AND it is the discriminator between this export and
            # Items Detail: the Items export carries every other column in this
            # set, so without it an Items file read as Transactions would parse
            # "successfully" and emit one bogus order per line item.
            "Source",
        }
    ),
    ImportFileRole.ITEMS_DETAIL: frozenset(
        {"Date", "Time", "Time Zone", "Item", "Qty", "Product Sales", "Transaction ID"}
    ),
    ImportFileRole.ITEMS_SUMMARY: frozenset(
        {"Item Name", "Items Sold", "Product Sales", "Net Sales"}
    ),
}

#: Columns deliberately never bound by the row schemas. Listed here so the
#: exclusion is explicit and testable rather than an accident of omission.
EXCLUDED_PII_COLUMNS = frozenset(
    {
        "Customer ID", "Customer Name", "Customer Reference ID",
        "Card", "Card Brand", "PAN Suffix", "Card Entry Methods",
        "Staff Name", "Staff ID", "Employee", "Details", "Device Name",
        "Device Nickname", "Tender Note",
    }
)

# --- channel derivation ------------------------------------------------------

_DELIVERY_SOURCES = frozenset({"uber eats", "just eat", "deliveroo"})
#: Square's own online ordering. The export carries no fulfilment detail for
#: these, so they map to their own channel rather than being guessed into
#: collection or delivery.
_ONLINE_SOURCES = frozenset({"square online"})
_COUNTER_SOURCES = frozenset({"point of sale", "register"})
_PICKUP_SUFFIX = " pickup"

#: Dining options, as a normalised set, mapped to a canonical channel. A
#: combined "Eat in, Takeaway" order is genuinely mixed rather than either.
#: Square writes a comma-separated list when one order spans more than one
#: fulfilment mode, so the key is the SET of options, not the raw string.
#:
#: A combination that spans two different single-option channels is MIXED:
#: "eat in" and "takeaway" are both IN_STORE while "pick up" is COLLECTION, so
#: any pairing that crosses that boundary describes an order fulfilled two ways
#: and belongs in neither. Folding it into either one would put revenue in a
#: channel the source does not support.
_DINING_OPTION_CHANNELS: dict[frozenset[str], Channel] = {
    frozenset({"eat in"}): Channel.IN_STORE,
    frozenset({"takeaway"}): Channel.IN_STORE,
    frozenset({"eat in", "takeaway"}): Channel.MIXED,
    frozenset({"pick up"}): Channel.COLLECTION,
    # Both found in the real 12-month export set: 22 orders carry
    # "Eat In, Pick Up" and 3 carry "Pick Up, Takeaway". Each spans the
    # in-store/collection boundary, so each is MIXED by the rule above.
    frozenset({"eat in", "pick up"}): Channel.MIXED,
    frozenset({"pick up", "takeaway"}): Channel.MIXED,
}

#: Heuristic. Square has no field marking a product as a gift voucher, so it is
#: matched on name. Documented as a heuristic precisely because it is one: a
#: renamed voucher product would silently become menu revenue.
GIFT_VOUCHER_MARKERS = ("gift voucher", "gift card")
CUSTOM_AMOUNT_NAMES = frozenset({"custom amount"})

#: Square writes the literal string "None" for uncategorised items — not blank.
_NULL_CATEGORY_TEXT = frozenset({"", "none", "uncategorised", "uncategorized"})


@dataclass(frozen=True)
class _PreparedTransaction:
    """A transaction row that passed structural validation, awaiting a channel."""

    row_number: int
    row: SquareTransactionRow
    event: OrderEventType
    occurred_at: datetime
    net: int
    discount: int


@dataclass(frozen=True)
class ChannelDerivation:
    channel: Channel | None
    reason: str


def derive_channel(source: str, dining_option: str) -> ChannelDerivation:
    """Map Square's Source + Dining Option onto a canonical channel.

    Square's own `Channel` column is NOT this field — it holds the point-of-sale
    or integration name ("Deliverect"), not how the order reached the business.

    Returns `channel=None` for combinations the mapping does not cover. That is
    an explicit outcome the caller reports; the adapter never guesses.
    """
    src = (source or "").strip().lower()

    if src.endswith(_PICKUP_SUFFIX):
        return ChannelDerivation(Channel.COLLECTION, f"pickup source {source!r}")
    if src in _DELIVERY_SOURCES:
        return ChannelDerivation(Channel.DELIVERY, f"delivery platform {source!r}")

    options = frozenset(
        part.strip().lower() for part in (dining_option or "").split(",") if part.strip()
    )

    if src in _ONLINE_SOURCES:
        # A dining option, where present, is real evidence and takes priority.
        # Only genuinely ambiguous fulfilment falls back to ONLINE.
        channel = _DINING_OPTION_CHANNELS.get(options)
        if channel is not None:
            return ChannelDerivation(channel, f"online source with dining option {options}")
        return ChannelDerivation(
            Channel.ONLINE, f"online source {source!r} with no fulfilment detail"
        )

    if src in _COUNTER_SOURCES:
        channel = _DINING_OPTION_CHANNELS.get(options)
        if channel is not None:
            return ChannelDerivation(channel, f"counter source, dining option {options}")
        if not options:
            return ChannelDerivation(
                None, f"counter source {source!r} with no dining option"
            )
        return ChannelDerivation(
            None, f"counter source {source!r} with unmapped dining option {sorted(options)}"
        )

    return ChannelDerivation(None, f"unmapped source {source!r}")


def classify_product_kind(name: str, category: str | None) -> ProductKind:
    lowered = (name or "").strip().lower()
    if lowered in CUSTOM_AMOUNT_NAMES:
        return ProductKind.CUSTOM_AMOUNT
    if any(marker in lowered for marker in GIFT_VOUCHER_MARKERS):
        return ProductKind.GIFT_VOUCHER
    return ProductKind.MENU_ITEM


def normalise_category(raw: str | None) -> str | None:
    text = (raw or "").strip()
    return None if text.lower() in _NULL_CATEGORY_TEXT else text


def _event_type(raw: str) -> OrderEventType | None:
    match (raw or "").strip().lower():
        case "payment":
            return OrderEventType.PAYMENT
        case "refund":
            return OrderEventType.REFUND
        case _:
            return None


# --- reading -----------------------------------------------------------------


def detect_encoding(path: Path) -> str:
    """Assert the file really is UTF-16, and say so clearly when it is not."""
    with path.open("rb") as handle:
        prefix = handle.read(4)

    if prefix.startswith(_BOM_UTF16_LE):
        return "utf-16"
    if prefix.startswith(_BOM_UTF16_BE):
        return "utf-16"
    if prefix.startswith(_BOM_UTF8):
        raise SourceFormatError(
            f"{path.name}: expected a UTF-16 Square export but found a UTF-8 BOM. "
            "Square exports are UTF-16 despite the .csv extension; this file has "
            "probably been re-saved by a spreadsheet application."
        )
    raise SourceFormatError(
        f"{path.name}: expected a UTF-16 byte-order mark, found {prefix[:2]!r}. "
        "Square exports are UTF-16 LE, tab-delimited, despite the .csv extension."
    )


def read_rows(path: Path, role: ImportFileRole) -> tuple[list[dict[str, str]], list[str]]:
    """Read a Square export into dict rows, asserting format and schema."""
    encoding = detect_encoding(path)

    with path.open(encoding=encoding, newline="") as handle:
        sample = handle.readline()
        if DELIMITER not in sample:
            raise SourceFormatError(
                f"{path.name}: header contains no TAB character. Square exports are "
                f"tab-delimited; found a header of {len(sample.split(','))} "
                "comma-separated fields instead."
            )
        handle.seek(0)
        reader = csv.DictReader(handle, delimiter=DELIMITER)
        fieldnames = list(reader.fieldnames or [])
        missing = REQUIRED_COLUMNS[role] - set(fieldnames)
        if missing:
            raise SourceSchemaError(
                f"{path.name}: not a Square {role.value} export — missing required "
                f"column(s): {', '.join(sorted(missing))}"
            )
        rows = list(reader)

    return rows, fieldnames


class SquareAdapter(SourceAdapter):
    """Maps Square's exports onto canonical records."""

    source_name = "square"

    def read(self, path: Path, role: ImportFileRole) -> ParseResult:
        rows, _ = read_rows(path, role)
        result = ParseResult(role=role, path=path, rows_read=len(rows))

        match role:
            case ImportFileRole.TRANSACTIONS:
                self._read_transactions(rows, result)
            case ImportFileRole.ITEMS_DETAIL:
                self._read_items(rows, result)
            case ImportFileRole.ITEMS_SUMMARY:
                self._read_summary(rows, result)

        return result

    # -- transactions ---------------------------------------------------------

    def _read_transactions(self, rows: list[dict[str, str]], result: ParseResult) -> None:
        """Normalise transactions in two passes.

        Payments are normalised first so that a `(source, payment_id) -> channel`
        lookup exists by the time refunds are processed. A refund row carries no
        usable fulfilment detail of its own — Square writes it from the till with
        a blank dining option — so its channel is inherited from the payment it
        reverses.

        Refunds also bypass the zero-value and unresolved-channel exclusions
        entirely. A refund is a real financial event whichever way its columns
        read: Square reports one of the August refunds with `Net Sales £0.00`
        and `Total Collected -£50.58`, so a value test on net sales alone would
        silently discard it.
        """
        prepared = self._prepare_transactions(rows, result)

        channel_by_payment: dict[tuple[str, str], Channel] = {}
        for item in (p for p in prepared if p.event is OrderEventType.PAYMENT):
            self._normalise_payment(item, result, channel_by_payment)

        for item in (p for p in prepared if p.event is OrderEventType.REFUND):
            self._normalise_refund(item, result, channel_by_payment)

    def _prepare_transactions(
        self, rows: list[dict[str, str]], result: ParseResult
    ) -> list[_PreparedTransaction]:
        """Validate every row's identity, event, timestamp and money.

        Failures here are structural and apply equally to payments and refunds.
        """
        prepared: list[_PreparedTransaction] = []

        for number, raw in enumerate(rows, start=2):  # row 1 is the header
            row = SquareTransactionRow.model_validate(raw)

            if not row.transaction_id.strip():
                result.issues.append(
                    RowIssue(number, IssueCode.MISSING_TRANSACTION_ID, Severity.SKIP,
                             "transaction has no Transaction ID", "Transaction ID")
                )
                continue

            event = _event_type(row.event_type)
            if event is None:
                result.issues.append(
                    RowIssue(number, IssueCode.UNKNOWN_EVENT_TYPE, Severity.SKIP,
                             f"unrecognised Event Type {row.event_type!r}",
                             "Event Type", row.transaction_id)
                )
                continue

            try:
                instant = parse_local_instant(row.date, row.time, row.time_zone)
            except TimeZoneError as exc:
                result.issues.append(
                    RowIssue(number, IssueCode.UNKNOWN_TIME_ZONE, Severity.SKIP,
                             str(exc), "Time Zone", row.transaction_id)
                )
                continue
            except NonexistentLocalTime as exc:
                result.issues.append(
                    RowIssue(number, IssueCode.NONEXISTENT_LOCAL_TIME, Severity.SKIP,
                             str(exc), "Time", row.transaction_id)
                )
                continue

            if instant.ambiguous:
                result.issues.append(
                    RowIssue(number, IssueCode.AMBIGUOUS_LOCAL_TIME, Severity.WARN,
                             "local time occurs twice (clocks went back); "
                             "resolved to the first, still-BST occurrence",
                             "Time", row.transaction_id)
                )

            try:
                net = parse_money_to_pence(row.net_sales)
                # Negated, not abs(): same reasoning as the line-level discount
                # above. abs() would report a positive discount on a refund
                # that reverses a discounted sale, breaking
                # gross = net + discount for that row. Identical for every
                # payment, so no existing figure changes.
                discount = -parse_money_to_pence(row.discounts)
            except MoneyParseError as exc:
                result.issues.append(
                    RowIssue(number, IssueCode.UNPARSABLE_MONEY, Severity.SKIP,
                             str(exc), "Net Sales/Discounts", row.transaction_id)
                )
                continue

            prepared.append(
                _PreparedTransaction(
                    row_number=number, row=row, event=event,
                    occurred_at=instant.utc, net=net, discount=discount,
                )
            )

        return prepared

    def _build_order(
        self, item: _PreparedTransaction, channel: Channel
    ) -> CanonicalOrder:
        # Square's "Gross Sales" is already NET of discounts and equals its
        # "Net Sales". Our canonical gross is the pre-discount figure, so that
        # gross - discount = net holds as the model expects.
        return CanonicalOrder(
            source=self.source_name,
            source_order_id=item.row.transaction_id.strip(),
            source_payment_id=item.row.payment_id.strip() or None,
            occurred_at=item.occurred_at,
            channel=channel,
            event_type=item.event,
            gross_amount=item.net + item.discount,
            discount_amount=item.discount,
            net_amount=item.net,
        )

    def _normalise_payment(
        self,
        item: _PreparedTransaction,
        result: ParseResult,
        channel_by_payment: dict[tuple[str, str], Channel],
    ) -> None:
        row = item.row

        if item.net == 0 and item.discount == 0:
            result.issues.append(
                RowIssue(item.row_number, IssueCode.ZERO_VALUE_TRANSACTION, Severity.SKIP,
                         "zero-value payment excluded from analytical orders",
                         None, row.transaction_id)
            )
            return

        derivation = derive_channel(row.source, row.dining_option)
        if derivation.channel is None:
            result.issues.append(
                RowIssue(item.row_number, IssueCode.UNRESOLVED_CHANNEL, Severity.SKIP,
                         f"cannot derive channel: {derivation.reason}",
                         "Source/Dining Option", row.transaction_id)
            )
            return

        order = self._build_order(item, derivation.channel)
        result.orders.append(order)

        if order.source_payment_id:
            channel_by_payment[(order.source, order.source_payment_id)] = order.channel

    def _normalise_refund(
        self,
        item: _PreparedTransaction,
        result: ParseResult,
        channel_by_payment: dict[tuple[str, str], Channel],
    ) -> None:
        """Refunds are never excluded — only their channel can be uncertain.

        Resolution is tried in descending order of evidence:

          1. Inherit from the payment being reversed, when that payment is in
             this extraction. Strongest evidence: it is the same commercial
             event, and the payment row carries the real fulfilment detail.
          2. Derive from the refund's OWN Source + Dining Option, using the
             ordinary mapping. Weaker, because a refund is often rung through
             the till rather than the original channel — but a refund whose
             Source really is "Deliveroo" is delivery, and calling that
             "unknown" would discard evidence we actually have.
          3. Only then, `unknown`. Still preserved, never dropped.
        """
        row = item.row
        payment_id = row.payment_id.strip() or None

        inherited = (
            channel_by_payment.get((self.source_name, payment_id))
            if payment_id
            else None
        )
        if inherited is not None:
            result.issues.append(
                RowIssue(item.row_number, IssueCode.REFUND_CHANNEL_INHERITED, Severity.WARN,
                         f"channel {inherited.value!r} inherited from payment "
                         f"{payment_id}", "Payment ID", row.transaction_id)
            )
            result.orders.append(self._build_order(item, inherited))
            return

        derivation = derive_channel(row.source, row.dining_option)
        if derivation.channel is not None:
            result.issues.append(
                RowIssue(item.row_number, IssueCode.REFUND_CHANNEL_DERIVED, Severity.WARN,
                         f"original payment not in this extraction; channel "
                         f"{derivation.channel.value!r} derived from the refund's "
                         f"own row ({derivation.reason})",
                         "Source/Dining Option", row.transaction_id)
            )
            result.orders.append(self._build_order(item, derivation.channel))
            return

        result.issues.append(
            RowIssue(item.row_number, IssueCode.REFUND_CHANNEL_UNKNOWN, Severity.WARN,
                     "original payment is not in this extraction window and the "
                     f"refund's own row is unresolvable ({derivation.reason}); "
                     "preserved with channel 'unknown' rather than dropped",
                     "Payment ID", row.transaction_id)
        )
        result.orders.append(self._build_order(item, Channel.UNKNOWN))

    # -- items ----------------------------------------------------------------

    def _read_items(self, rows: list[dict[str, str]], result: ParseResult) -> None:
        for number, raw in enumerate(rows, start=2):
            row = SquareItemRow.model_validate(raw)

            if not row.transaction_id.strip():
                result.issues.append(
                    RowIssue(number, IssueCode.MISSING_TRANSACTION_ID, Severity.SKIP,
                             "item row has no Transaction ID", "Transaction ID")
                )
                continue

            try:
                quantity = parse_quantity(row.qty)
            except QuantityParseError as exc:
                result.issues.append(
                    RowIssue(number, IssueCode.UNPARSABLE_QUANTITY, Severity.SKIP,
                             str(exc), "Qty", row.transaction_id)
                )
                continue

            try:
                line_total = parse_money_to_pence(row.product_sales)
                # Square writes discounts NEGATIVE, the same convention as its
                # Refunds and Items Refunded columns. Negating (rather than
                # taking the magnitude) keeps the sign aligned with line_total:
                # a payment line yields a positive discount, a refund line a
                # negative one, so line_total - discount_amount is the net
                # contribution in both directions.
                line_discount = -parse_money_to_pence(row.discounts)
            except MoneyParseError as exc:
                result.issues.append(
                    RowIssue(number, IssueCode.UNPARSABLE_MONEY, Severity.SKIP,
                             str(exc), "Product Sales/Discounts",
                             row.transaction_id)
                )
                continue

            if quantity == 0:
                result.issues.append(
                    RowIssue(number, IssueCode.UNPARSABLE_QUANTITY, Severity.SKIP,
                             "item row has zero quantity", "Qty", row.transaction_id)
                )
                continue

            name = row.item.strip()
            category = normalise_category(row.category)
            product = CanonicalProduct(
                name=name,
                variation=row.price_point_name.strip(),
                category=category,
                kind=classify_product_kind(name, category),
            )

            result.items.append(
                CanonicalOrderItem(
                    source_order_id=row.transaction_id.strip(),
                    product=product,
                    quantity=quantity,
                    unit_price=unit_price_pence(line_total, quantity),
                    line_total=line_total,
                    discount_amount=line_discount,
                    modifiers=row.modifiers_applied.strip() or None,
                )
            )

    # -- summary --------------------------------------------------------------

    def _read_summary(self, rows: list[dict[str, str]], result: ParseResult) -> None:
        """Reconciliation only. Produces no canonical sales records, ever."""
        for raw in rows:
            result.summary_rows.append(SquareSummaryRow.model_validate(raw))


def attach_items(
    orders: list[CanonicalOrder], items: list[CanonicalOrderItem]
) -> tuple[list[CanonicalOrder], list[RowIssue]]:
    """Join items to their orders and set item_count.

    Item rows whose transaction was skipped (or is absent) are reported as
    orphans rather than dropped quietly.
    """
    by_order: dict[str, list[CanonicalOrderItem]] = defaultdict(list)
    for item in items:
        by_order[item.source_order_id].append(item)

    known = {order.source_order_id for order in orders}
    issues = [
        RowIssue(0, IssueCode.ORPHAN_ITEM, Severity.WARN,
                 f"{len(group)} item row(s) reference a transaction that produced "
                 "no analytical order", None, order_id)
        for order_id, group in by_order.items()
        if order_id not in known
    ]

    joined = [
        order.model_copy(
            update={
                # Signed, matching the signed money: a refund order carries a
                # negative item_count, so summing across orders yields NET
                # units rather than double-counting a refunded unit as sold.
                "item_count": sum(
                    i.quantity for i in by_order.get(order.source_order_id, [])
                )
            }
        )
        for order in orders
    ]
    return joined, issues
