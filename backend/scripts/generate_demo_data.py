"""Generate the synthetic Square export set used by the demo and README.

Everything here is invented. No real customer, staff, card, payment or
transaction data from any business appears in the output, and the PII columns
Square includes are written empty on purpose — the importer ignores them, and
this makes that visible.

The three files are derived from one list of orders so they reconcile by
construction rather than by hand-editing:

    items Product Sales      = summary Product Sales + summary Refunds
    orders Net Sales         = summary Net Sales
    items net quantity       = summary Units Sold + summary Items Refunded

Run:  python scripts/generate_demo_data.py
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path

OUT_DIR = Path(__file__).resolve().parents[2] / "demo" / "square-sample"

TRANSACTION_COLUMNS = [
    "Date", "Time", "Time Zone", "Gross Sales", "Discounts", "Service Charges",
    "Net Sales", "Gift Card Sales", "Tax", "Tip", "Partial Refunds",
    "Total Collected", "Source", "Card", "Card Entry Methods", "Cash",
    "Square Gift Card", "Other Tender", "Other Tender Type", "Tender Note",
    "Fees", "Net Total", "Transaction ID", "Payment ID", "Card Brand",
    "PAN Suffix", "Device Name", "Staff Name", "Staff ID", "Details",
    "Description", "Invoice Number", "Event Type", "Location", "Dining Option",
    "Customer ID", "Customer Name", "Customer Reference ID", "Device Nickname",
    "Third Party Fees", "Deposit ID", "Deposit Date", "Deposit Details",
    "Fee Percentage Rate", "Fee Fixed Rate", "Refund Reason", "Discount Name",
    "Transaction Status", "Order Reference ID", "Fulfilment Note",
    "Free Processing Applied", "Channel", "Unattributed Tips", "Table info",
    "International fee",
]

ITEM_COLUMNS = [
    "Date", "Time", "Time Zone", "Category", "Item", "Qty", "Price Point Name",
    "SKU", "Modifiers Applied", "Product Sales", "Discounts", "Net Sales",
    "Tax", "Gross Sales", "Transaction ID", "Payment ID", "Device Name",
    "Notes", "Details", "Event Type", "Location", "Dining Option",
    "Customer ID", "Customer Name", "Customer Reference ID", "Unit", "Count",
    "GTIN", "Itemisation Type", "Commission", "Employee", "Fulfilment Note",
    "Channel", "Token", "Card Brand", "PAN Suffix",
]

SUMMARY_COLUMNS = [
    "Item Name", "Item Variation", "SKU", "Category", "Items Sold",
    "Product Sales", "Items Refunded", "Refunds", "Discounts & Comps",
    "Net Sales", "Tax", "Gross Sales", "Units Sold",
]


def money(amount: Decimal) -> str:
    return f"-£{-amount:.2f}" if amount < 0 else f"£{amount:.2f}"


@dataclass
class Line:
    item: str
    variation: str
    category: str
    qty: int
    product_sales: Decimal
    modifiers: str = ""
    discount: Decimal = Decimal("0.00")
    itemisation: str = "Prepared Food and Beverage"

    @property
    def net(self) -> Decimal:
        return self.product_sales + self.discount


@dataclass
class Txn:
    txn_id: str
    payment_id: str
    date: str
    time: str
    source: str
    dining_option: str
    lines: list[Line] = field(default_factory=list)
    event_type: str = "Payment"
    channel: str = "The Demo Coffee House"
    discount_name: str = ""

    @property
    def product_sales(self) -> Decimal:
        return sum((l.product_sales for l in self.lines), Decimal("0.00"))

    @property
    def discounts(self) -> Decimal:
        return sum((l.discount for l in self.lines), Decimal("0.00"))

    @property
    def net(self) -> Decimal:
        return self.product_sales + self.discounts


# --- the invented month ------------------------------------------------------
# Two coffees, a pastry, a gift voucher and an open-price line, across every
# channel the model supports, plus a discount, a refund and a no-sale row.

FILTER_R = ("Filter Coffee", "Regular", "Hot Drinks")
FILTER_L = ("Filter Coffee", "Large", "Hot Drinks")
CROISSANT = ("Almond Croissant", "", "Bakery")

TRANSACTIONS = [
    Txn("TX-DEMO-0001", "PAY-DEMO-0001", "2026-08-03", "09:15:00", "Register", "Eat in", [
        Line(*FILTER_R, 1, Decimal("2.50"), "Oat Milk"),
        Line(*CROISSANT, 1, Decimal("3.10"), itemisation="Physical Good"),
    ]),
    Txn("TX-DEMO-0002", "PAY-DEMO-0002", "2026-08-03", "12:40:00", "Point of Sale", "Takeaway", [
        Line(*FILTER_L, 2, Decimal("6.40"), "Whole Milk"),
    ]),
    Txn("TX-DEMO-0003", "PAY-DEMO-0003", "2026-08-03", "18:05:00", "Deliveroo", "", [
        Line(*CROISSANT, 2, Decimal("6.20"), itemisation="Physical Good"),
    ], channel="Deliverect"),
    Txn("TX-DEMO-0004", "PAY-DEMO-0004", "2026-08-04", "08:30:00", "Register", "Eat in, Takeaway", [
        Line(*FILTER_R, 1, Decimal("2.50")),
        Line(*CROISSANT, 1, Decimal("3.10"), itemisation="Physical Good"),
    ]),
    Txn("TX-DEMO-0005", "PAY-DEMO-0005", "2026-08-04", "10:00:00", "Square Online", "", [
        Line(*FILTER_L, 1, Decimal("3.20")),
    ]),
    Txn("TX-DEMO-0006", "PAY-DEMO-0006", "2026-08-04", "11:20:00", "Register", "Pick Up", [
        Line("Demo Gift Voucher", "Regular", "Uncategorised", 1, Decimal("10.00"),
             itemisation="Physical Good"),
    ]),
    Txn("TX-DEMO-0007", "PAY-DEMO-0007", "2026-08-04", "14:00:00", "Register", "Eat in", [
        Line("Custom Amount", "", "None", 1, Decimal("4.00"), itemisation=""),
    ]),
    # A staff discount: Square reports Gross Sales ALREADY net of it.
    Txn("TX-DEMO-0008", "PAY-DEMO-0008", "2026-08-05", "09:00:00", "Register", "Eat in", [
        Line(*FILTER_R, 2, Decimal("5.00"), discount=Decimal("-1.00")),
    ], discount_name="Staff Discount"),
    # Sold, then refunded in full a quarter of an hour later.
    Txn("TX-DEMO-0009", "PAY-DEMO-0009", "2026-08-05", "10:30:00", "Register", "Eat in", [
        Line(*FILTER_L, 1, Decimal("3.20")),
    ]),
    Txn("TX-DEMO-0010", "PAY-DEMO-0009", "2026-08-05", "10:45:00", "Register", "", [
        Line(*FILTER_L, -1, Decimal("-3.20")),
    ], event_type="Refund"),
    # A no-sale / voided row: excluded from analytical orders, but counted.
    Txn("TX-DEMO-0011", "PAY-DEMO-0011", "2026-08-05", "16:00:00", "Register", "", []),
]


def transaction_rows() -> list[dict[str, str]]:
    rows = []
    for t in TRANSACTIONS:
        row = {c: "" for c in TRANSACTION_COLUMNS}
        row.update({
            "Date": t.date, "Time": t.time, "Time Zone": "London",
            # Square's "Gross Sales" is already net of discounts.
            "Gross Sales": money(t.net), "Discounts": money(t.discounts),
            "Service Charges": "£0.00", "Net Sales": money(t.net),
            "Gift Card Sales": "£0.00", "Tax": "£0.00", "Tip": "£0.00",
            "Partial Refunds": "£0.00", "Total Collected": money(t.net),
            "Source": t.source, "Transaction ID": t.txn_id,
            "Payment ID": t.payment_id, "Event Type": t.event_type,
            "Location": "The Demo Coffee House", "Dining Option": t.dining_option,
            "Transaction Status": "Complete", "Channel": t.channel,
            "Discount Name": t.discount_name,
            "Refund Reason": "Demo refund" if t.event_type == "Refund" else "",
        })
        rows.append(row)
    return rows


def item_rows() -> list[dict[str, str]]:
    rows = []
    for t in TRANSACTIONS:
        for line in t.lines:
            row = {c: "" for c in ITEM_COLUMNS}
            row.update({
                "Date": t.date, "Time": t.time, "Time Zone": "London",
                "Category": line.category, "Item": line.item,
                "Qty": f"{line.qty}.0", "Price Point Name": line.variation,
                "Modifiers Applied": line.modifiers,
                "Product Sales": money(line.product_sales),
                "Discounts": money(line.discount), "Net Sales": money(line.net),
                "Tax": "£0.00", "Gross Sales": money(line.net),
                "Transaction ID": t.txn_id, "Payment ID": t.payment_id,
                "Event Type": t.event_type, "Location": "The Demo Coffee House",
                "Dining Option": t.dining_option, "Unit": "ea",
                "Count": "1", "Itemisation Type": line.itemisation,
                "Channel": t.channel,
            })
            rows.append(row)
    return rows


def summary_rows() -> list[dict[str, str]]:
    """Aggregate the item lines the way Square's own summary does.

    Positive and negative quantities are reported separately: Units Sold counts
    sales, Items Refunded is a NEGATIVE count, and the two are added to get the
    net. Refunds and Discounts & Comps follow the same sign convention.
    """
    agg: dict[tuple[str, str], dict] = {}
    for t in TRANSACTIONS:
        for line in t.lines:
            key = (line.item, line.variation)
            entry = agg.setdefault(key, {
                "category": line.category, "sold": 0, "refunded": 0,
                "product_sales": Decimal("0.00"), "refunds": Decimal("0.00"),
                "discounts": Decimal("0.00"),
            })
            if line.qty >= 0:
                entry["sold"] += line.qty
                entry["product_sales"] += line.product_sales
            else:
                entry["refunded"] += line.qty
                entry["refunds"] += line.product_sales
            entry["discounts"] += line.discount

    rows = []
    for (item, variation), e in agg.items():
        net = e["product_sales"] + e["refunds"] + e["discounts"]
        row = {c: "" for c in SUMMARY_COLUMNS}
        row.update({
            "Item Name": item,
            "Item Variation": variation or "No description",
            "Category": e["category"] or "Uncategorised",
            "Items Sold": str(e["sold"]),
            "Product Sales": money(e["product_sales"]),
            "Items Refunded": str(e["refunded"]),
            "Refunds": money(e["refunds"]),
            "Discounts & Comps": money(e["discounts"]),
            "Net Sales": money(net), "Tax": "£0.00", "Gross Sales": money(net),
            "Units Sold": str(e["sold"]),
        })
        rows.append(row)
    return rows


def write(path: Path, columns: list[str], rows: list[dict[str, str]]) -> None:
    """Write in Square's real export format: UTF-16 LE with BOM, TAB delimited."""
    lines = ["\t".join(columns)]
    lines += ["\t".join(row.get(c, "") for c in columns) for row in rows]
    path.write_text("\n".join(lines) + "\n", encoding="utf-16")
    print(f"  {path.relative_to(path.parents[2])}  ({len(rows)} rows)")


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    print("Generating synthetic Square exports:")
    write(OUT_DIR / "transactions-demo-2026-08.csv", TRANSACTION_COLUMNS, transaction_rows())
    write(OUT_DIR / "items-demo-2026-08.csv", ITEM_COLUMNS, item_rows())
    write(OUT_DIR / "item-sales-summary-demo-2026-08.csv", SUMMARY_COLUMNS, summary_rows())

    items = item_rows()
    net = sum((t.net for t in TRANSACTIONS), Decimal("0.00"))
    product = sum((l.product_sales for t in TRANSACTIONS for l in t.lines), Decimal("0.00"))
    units = sum(l.qty for t in TRANSACTIONS for l in t.lines)
    print(f"\n  transactions {len(TRANSACTIONS)}  item lines {len(items)}")
    print(f"  net sales {money(net)}   product sales {money(product)}   net units {units}")


if __name__ == "__main__":
    main()
