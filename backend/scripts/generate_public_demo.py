"""Generate a full synthetic trading year in Square's export format.

WHAT THIS IS FOR
A public demo needs a dataset that makes every page of the dashboard mean
something — a year of trade with a weekly rhythm, products that rise and fall,
baskets that genuinely go together, and enough history to backtest a forecast.
It must also be completely fictional, because the real dataset this project was
built against belongs to a business.

EVERYTHING HERE IS INVENTED. The Copper Kettle does not exist. No name, price,
volume, product, seasonal pattern or trading figure is copied from any real
business, and the PII columns Square includes are written empty on purpose —
the importer ignores them, and writing them empty makes that visible.

DETERMINISM
One seeded `random.Random`, drawn from in a fixed order. The same seed produces
byte-identical files, so a regenerated demo dataset does not silently become a
different one — which matters when screenshots, documentation and a forecast's
measured error all refer to it.

RECONCILIATION BY CONSTRUCTION
The three files are projections of ONE list of orders, so the importer's three
checks hold arithmetically rather than by hand-tuning:

    sum(order Net Sales)      = sum(summary Net Sales)
    sum(item Product Sales)   = sum(summary Product Sales + Refunds)
    sum(item Qty)             = sum(summary Units Sold + Items Refunded)

Square's sign conventions are followed exactly: discounts and refunds are
NEGATIVE, and "Gross Sales" on a transaction is already net of discount.

Run:  docker compose exec api python scripts/generate_public_demo.py
"""

from __future__ import annotations

import argparse
import random
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

# --- determinism -------------------------------------------------------------

#: The one source of randomness. Fixed so the dataset is reproducible; changing
#: it produces a different but equally valid year.
SEED = 424242

#: A full year ending on the last day of a complete month, so every dashboard's
#: default range and every "last month" question land on real trade.
START_DATE = date(2025, 9, 1)
DAYS = 365

#: Written inside the backend directory, which is the path bind-mounted into
#: the api container — so the same command produces the same files whether it
#: is run on the host or through Compose. `data/` is gitignored at any depth,
#: so a year of generated exports never reaches the repository.
#: Override with `--out <dir>`.
DEFAULT_OUT_DIR = Path(__file__).resolve().parents[1] / "data" / "public-demo"

#: The fictional business. Appears only in Square's Location/Channel columns,
#: which the importer reads for provenance and never for money.
BUSINESS = "The Copper Kettle"

# --- Square's export columns -------------------------------------------------

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
    """Square's money format, with its leading minus outside the symbol."""
    return f"-£{-amount:.2f}" if amount < 0 else f"£{amount:.2f}"


def gbp(value: str) -> Decimal:
    return Decimal(value)


# --- the invented menu -------------------------------------------------------
#
# `slot` decides when an item sells: BREAKFAST items barely move after midday,
# LUNCH items barely move before it, and ALLDAY items sell throughout. That is
# what gives the peak-hours heatmap and the weekday profile something real to
# show.
#
# `trend` is a (start, end) weight multiplier interpolated across the year. It
# is the mechanism behind the product-movers page: without it every product
# would drift only by noise and "declining" would be meaningless.
#
# `available` restricts an item to part of the year, so the catalogue has a
# genuine arrival and a genuine discontinuation rather than 365 identical days.

BREAKFAST, LUNCH, ALLDAY, DRINK = "breakfast", "lunch", "allday", "drink"

MENU_ITEM = "menu_item"
VOUCHER = "voucher"
OPEN_PRICE = "open_price"


@dataclass(frozen=True)
class MenuItem:
    name: str
    variation: str
    category: str
    price: Decimal
    slot: str
    #: Relative popularity before trend and slot weighting.
    weight: float
    #: (start, end) multiplier across the year. (1, 1) is flat.
    trend: tuple[float, float] = (1.0, 1.0)
    #: Inclusive day-index window this item is on the menu for.
    available: tuple[int, int] = (0, DAYS - 1)
    kind: str = MENU_ITEM
    itemisation: str = "Prepared Food and Beverage"

    @property
    def key(self) -> tuple[str, str]:
        return (self.name, self.variation)


MENU: list[MenuItem] = [
    # --- hot drinks ---------------------------------------------------------
    MenuItem("Copper House Blend", "Regular", "Hot Drinks", gbp("2.95"), DRINK, 100),
    MenuItem("Copper House Blend", "Large", "Hot Drinks", gbp("3.45"), DRINK, 62),
    MenuItem("Silken Milk Coffee", "", "Hot Drinks", gbp("3.30"), DRINK, 58),
    MenuItem("Morning Cortado", "", "Hot Drinks", gbp("3.10"), DRINK, 40),
    MenuItem("Spiced Masala Chai", "Regular", "Hot Drinks", gbp("3.40"), DRINK, 34,
             trend=(0.7, 1.5)),
    MenuItem("Spiced Masala Chai", "Large", "Hot Drinks", gbp("3.90"), DRINK, 20,
             trend=(0.7, 1.5)),
    MenuItem("Double Espresso", "", "Hot Drinks", gbp("2.40"), DRINK, 26),
    MenuItem("Rooibos Amber Tea", "", "Hot Drinks", gbp("2.60"), DRINK, 30),
    MenuItem("Hedgerow Herbal Infusion", "", "Hot Drinks", gbp("2.70"), DRINK, 18),

    # --- cold drinks --------------------------------------------------------
    # Arrives in month four: a genuine new product for the movers page.
    MenuItem("Cloudberry Lemonade", "", "Cold Drinks", gbp("3.20"), DRINK, 44,
             trend=(1.0, 1.8), available=(92, DAYS - 1)),
    MenuItem("Pressed Apple & Elderflower", "", "Cold Drinks", gbp("2.90"), DRINK, 26),
    MenuItem("Iced Maple Latte", "", "Cold Drinks", gbp("3.80"), DRINK, 30,
             trend=(0.5, 2.2)),
    # Free. Exercises the importer's zero-value-order-with-real-items path.
    MenuItem("Still Spring Water", "", "Cold Drinks", gbp("0.00"), DRINK, 22),

    # --- breakfast ----------------------------------------------------------
    MenuItem("Skillet Breakfast", "Regular", "Breakfast", gbp("9.75"), BREAKFAST, 78),
    MenuItem("Skillet Breakfast", "Large", "Breakfast", gbp("12.50"), BREAKFAST, 34),
    MenuItem("Smashed Avocado Stack", "", "Breakfast", gbp("8.40"), BREAKFAST, 52,
             trend=(0.9, 1.35)),
    MenuItem("Buttermilk Pancake Tower", "", "Breakfast", gbp("7.90"), BREAKFAST, 46,
             trend=(1.5, 0.55)),
    MenuItem("Porridge with Poached Pear", "", "Breakfast", gbp("5.60"), BREAKFAST, 28),
    # Taken off the menu two-thirds of the way through the year.
    MenuItem("Wild Mushroom Toast", "", "Breakfast", gbp("7.20"), BREAKFAST, 30,
             available=(0, 242)),

    # --- lunch --------------------------------------------------------------
    MenuItem("Harvest Grain Bowl", "", "Lunch", gbp("9.20"), LUNCH, 60,
             trend=(0.75, 1.6)),
    MenuItem("Chargrilled Halloumi Wrap", "", "Lunch", gbp("8.60"), LUNCH, 50),
    MenuItem("Slow-Roast Beef Sandwich", "", "Lunch", gbp("8.95"), LUNCH, 48),
    MenuItem("Daily Soup Pot", "", "Lunch", gbp("5.90"), LUNCH, 42,
             trend=(1.4, 0.7)),
    MenuItem("Roast Beetroot & Orange Salad", "", "Lunch", gbp("8.10"), LUNCH, 30),
    MenuItem("Rarebit Toastie", "", "Lunch", gbp("7.40"), LUNCH, 44,
             trend=(1.6, 0.45)),

    # --- sides --------------------------------------------------------------
    MenuItem("Rosemary Skinny Fries", "", "Sides", gbp("3.90"), ALLDAY, 40),
    MenuItem("House Slaw", "", "Sides", gbp("2.40"), ALLDAY, 16),
    MenuItem("Sourdough Slice", "", "Sides", gbp("1.80"), ALLDAY, 20),

    # --- bakery -------------------------------------------------------------
    MenuItem("Pistachio Morning Bun", "", "Bakery", gbp("3.60"), ALLDAY, 54,
             trend=(0.85, 1.4), itemisation="Physical Good"),
    MenuItem("Salted Caramel Brownie", "", "Bakery", gbp("3.20"), ALLDAY, 46,
             itemisation="Physical Good"),
    MenuItem("Lemon Polenta Slice", "", "Bakery", gbp("3.40"), ALLDAY, 28,
             itemisation="Physical Good"),
    MenuItem("Cinnamon Knot", "", "Bakery", gbp("2.90"), ALLDAY, 32,
             trend=(1.3, 0.75), itemisation="Physical Good"),

    # --- not menu revenue ---------------------------------------------------
    #
    # These two names are NOT free choices. The importer classifies
    # ProductKind by name — "gift voucher"/"gift card" markers and the exact
    # string "Custom Amount" (app/adapters/square.py) — so a demo dataset that
    # renamed them would silently produce a catalogue with no voucher and no
    # open-price line, and the kind-filtering behaviour would go untested.
    # They are Square's platform vocabulary, not any business's product names.
    #
    # A liability at issuance, excluded from menu analytics by ProductKind.
    MenuItem("Copper Kettle Gift Voucher", "Regular", "Uncategorised",
             gbp("20.00"), ALLDAY, 4, kind=VOUCHER, itemisation="Physical Good"),
    # Square's open-price line: real revenue, no catalogue identity.
    MenuItem("Custom Amount", "", "None", gbp("4.50"), ALLDAY, 5,
             kind=OPEN_PRICE, itemisation=""),
]

BY_KEY = {item.key: item for item in MENU}


# --- basket structure --------------------------------------------------------
#
# Co-purchase has to be BUILT IN or it does not exist. Random baskets produce
# lift near 1.0 everywhere, which makes the basket page technically correct and
# completely uninteresting. These pairs are the ones the attachment and lift
# analytics are meant to surface, at strengths chosen to be visible without
# being absurd.

ATTACHMENTS: dict[tuple[str, str], list[tuple[tuple[str, str], float]]] = {
    ("Skillet Breakfast", "Regular"): [
        (("Copper House Blend", "Regular"), 0.62),
        (("Pressed Apple & Elderflower", ""), 0.18),
    ],
    ("Skillet Breakfast", "Large"): [
        (("Copper House Blend", "Large"), 0.58),
        (("Sourdough Slice", ""), 0.24),
    ],
    ("Pistachio Morning Bun", ""): [
        (("Morning Cortado", ""), 0.55),
    ],
    ("Salted Caramel Brownie", ""): [
        (("Spiced Masala Chai", "Regular"), 0.48),
    ],
    ("Harvest Grain Bowl", ""): [
        (("Cloudberry Lemonade", ""), 0.45),
    ],
    ("Slow-Roast Beef Sandwich", ""): [
        (("Rosemary Skinny Fries", ""), 0.66),
        (("House Slaw", ""), 0.22),
    ],
    ("Chargrilled Halloumi Wrap", ""): [
        (("Rosemary Skinny Fries", ""), 0.40),
    ],
    ("Daily Soup Pot", ""): [
        (("Sourdough Slice", ""), 0.70),
    ],
    ("Buttermilk Pancake Tower", ""): [
        (("Silken Milk Coffee", ""), 0.35),
    ],
}


# --- trading rhythm ----------------------------------------------------------

#: Monday-to-Sunday multipliers. A café is busiest at the weekend, and Monday
#: is the quietest day of the week.
WEEKDAY_FACTOR = [0.82, 0.88, 0.94, 1.00, 1.18, 1.46, 1.38]

#: Month-of-year multipliers, January first. A summer lift, a December peak,
#: and a slow start to the year.
MONTH_FACTOR = {
    1: 0.82, 2: 0.86, 3: 0.94, 4: 1.00, 5: 1.06, 6: 1.12,
    7: 1.18, 8: 1.16, 9: 1.02, 10: 0.96, 11: 0.94, 12: 1.08,
}

#: Opening hours and the shape of the day. Weight per hour, 7am to 5pm: a
#: breakfast peak, a deeper lunch peak, and a quiet middle afternoon.
WEEKDAY_HOURS = {
    7: 0.30, 8: 0.95, 9: 1.05, 10: 0.80, 11: 0.70, 12: 1.35,
    13: 1.30, 14: 0.75, 15: 0.55, 16: 0.35,
}
WEEKEND_HOURS = {
    8: 0.45, 9: 1.00, 10: 1.35, 11: 1.40, 12: 1.30,
    13: 1.15, 14: 0.85, 15: 0.60, 16: 0.35,
}

#: Average paid orders on a neutral day, before every factor above.
BASE_ORDERS_PER_DAY = 62

#: Closed days. A real business shuts sometimes, and a dashboard that has never
#: seen a zero day hides how it renders one.
CLOSURES = {date(2025, 12, 25), date(2025, 12, 26), date(2026, 1, 1)}


# --- channels ----------------------------------------------------------------
#
# Each entry is (Source, Dining Option, weight). Every combination here is one
# the existing adapter already maps — see app/adapters/square.py. Nothing new
# is introduced, because the generator must not require importer changes.

CHANNEL_MIX = [
    ("Register", "Eat in", 40),
    ("Register", "Takeaway", 22),
    ("Point of Sale", "Eat in", 8),
    ("Register", "Eat in, Takeaway", 3),      # -> mixed
    ("Register", "Pick Up", 4),               # -> collection
    ("Square Online", "", 3),                 # -> online
    ("Deliveroo", "", 9),                     # -> delivery
    ("Uber Eats", "", 5),                     # -> delivery
    ("Just Eat", "", 3),                      # -> delivery
]

#: Delivery baskets skew larger; the platform name also goes in Square's own
#: Channel column, which records the integration, not the channel.
DELIVERY_SOURCES = {"Deliveroo", "Uber Eats", "Just Eat"}

DISCOUNT_NAMES = ["Staff Discount", "Loyalty Reward", "Regulars Card"]
REFUND_REASONS = ["Order cancelled", "Item unavailable", "Made incorrectly"]


@dataclass
class Line:
    item: MenuItem
    qty: int
    product_sales: Decimal
    discount: Decimal = Decimal("0.00")

    @property
    def net(self) -> Decimal:
        return self.product_sales + self.discount


@dataclass
class Txn:
    txn_id: str
    payment_id: str
    day: date
    time: str
    source: str
    dining_option: str
    lines: list[Line] = field(default_factory=list)
    event_type: str = "Payment"
    channel: str = BUSINESS
    discount_name: str = ""
    refund_reason: str = ""

    @property
    def product_sales(self) -> Decimal:
        return sum((line.product_sales for line in self.lines), Decimal("0.00"))

    @property
    def discounts(self) -> Decimal:
        return sum((line.discount for line in self.lines), Decimal("0.00"))

    @property
    def net(self) -> Decimal:
        return self.product_sales + self.discounts


# --- generation --------------------------------------------------------------


def weighted_choice(rng: random.Random, options: list[tuple[object, float]]):
    total = sum(weight for _, weight in options)
    cut = rng.random() * total
    running = 0.0
    for value, weight in options:
        running += weight
        if cut <= running:
            return value
    return options[-1][0]


def available_menu(day_index: int, slot: str | None = None) -> list[MenuItem]:
    items = [
        item for item in MENU
        if item.available[0] <= day_index <= item.available[1]
    ]
    if slot is not None:
        items = [item for item in items if item.slot == slot]
    return items


def trend_weight(item: MenuItem, day_index: int) -> float:
    """The item's weight on this day, after its own trend across the year."""
    progress = day_index / max(DAYS - 1, 1)
    start, end = item.trend
    return item.weight * (start + (end - start) * progress)


def pick_anchor(rng: random.Random, day_index: int, hour: int) -> MenuItem:
    """The first item in a basket, chosen for the time of day."""
    if hour <= 10:
        slots = [(BREAKFAST, 6.0), (DRINK, 3.5), (ALLDAY, 1.6)]
    elif hour <= 14:
        slots = [(LUNCH, 6.0), (DRINK, 2.0), (ALLDAY, 1.8), (BREAKFAST, 1.0)]
    else:
        slots = [(DRINK, 4.5), (ALLDAY, 3.0), (LUNCH, 1.2)]

    slot = weighted_choice(rng, slots)
    candidates = [c for c in available_menu(day_index, slot) if c.kind == MENU_ITEM]
    if not candidates:
        candidates = [c for c in available_menu(day_index) if c.kind == MENU_ITEM]
    return weighted_choice(
        rng, [(item, trend_weight(item, day_index)) for item in candidates]
    )


def build_basket(
    rng: random.Random, day_index: int, hour: int, delivery: bool
) -> list[MenuItem]:
    """One order's items, with the encoded attachments applied."""
    anchor = pick_anchor(rng, day_index, hour)
    chosen = [anchor]

    for partner_key, probability in ATTACHMENTS.get(anchor.key, []):
        partner = BY_KEY[partner_key]
        if not (partner.available[0] <= day_index <= partner.available[1]):
            continue
        if rng.random() < probability:
            chosen.append(partner)

    # A filler item, more likely on a delivery order (larger baskets).
    if rng.random() < (0.34 if delivery else 0.22):
        pool = [
            item for item in available_menu(day_index)
            if item.kind == MENU_ITEM and item not in chosen
        ]
        chosen.append(
            weighted_choice(
                rng, [(item, trend_weight(item, day_index)) for item in pool]
            )
        )

    # Rare non-menu lines, so gift vouchers and open-price rows exist without
    # distorting the menu.
    if rng.random() < 0.004:
        chosen.append(BY_KEY[("Copper Kettle Gift Voucher", "Regular")])
    if rng.random() < 0.005:
        chosen.append(BY_KEY[("Custom Amount", "")])

    return chosen


def orders_for_day(rng: random.Random, day: date) -> int:
    if day in CLOSURES:
        return 0
    factor = WEEKDAY_FACTOR[day.weekday()] * MONTH_FACTOR[day.month]
    noise = rng.gauss(1.0, 0.12)
    return max(0, int(round(BASE_ORDERS_PER_DAY * factor * max(noise, 0.45))))


def generate() -> list[Txn]:
    rng = random.Random(SEED)
    transactions: list[Txn] = []
    counter = 0

    for day_index in range(DAYS):
        day = START_DATE + timedelta(days=day_index)
        hours = WEEKEND_HOURS if day.weekday() >= 5 else WEEKDAY_HOURS

        for _ in range(orders_for_day(rng, day)):
            counter += 1
            hour = weighted_choice(rng, list(hours.items()))
            minute, second = rng.randrange(60), rng.randrange(60)

            source, dining_option = weighted_choice(
                rng, [((s, d), w) for s, d, w in CHANNEL_MIX]
            )
            delivery = source in DELIVERY_SOURCES

            lines: list[Line] = []
            for item in build_basket(rng, day_index, hour, delivery):
                qty = 2 if (item.slot == DRINK and rng.random() < 0.12) else 1
                lines.append(Line(item, qty, item.price * qty))

            txn = Txn(
                txn_id=f"CK-{counter:07d}",
                payment_id=f"PAY-{counter:07d}",
                day=day,
                time=f"{hour:02d}:{minute:02d}:{second:02d}",
                source=source,
                dining_option=dining_option,
                lines=lines,
                channel="Deliverect" if delivery else BUSINESS,
            )

            # A discount, applied to the largest line the way a till does.
            if rng.random() < 0.035 and txn.product_sales > 0:
                target = max(txn.lines, key=lambda line: line.product_sales)
                rate = weighted_choice(
                    rng,
                    [(Decimal("0.10"), 5), (Decimal("0.20"), 3), (Decimal("0.50"), 1)],
                )
                target.discount = -(target.product_sales * rate).quantize(Decimal("0.01"))
                txn.discount_name = rng.choice(DISCOUNT_NAMES)

            transactions.append(txn)

            # A rare full refund, minutes later, against the same payment.
            if rng.random() < 0.0009 and txn.net > 0:
                counter += 1
                transactions.append(
                    Txn(
                        txn_id=f"CK-{counter:07d}",
                        payment_id=txn.payment_id,
                        day=day,
                        time=f"{hour:02d}:{min(minute + 12, 59):02d}:{second:02d}",
                        source=txn.source,
                        dining_option="",
                        lines=[
                            Line(line.item, -line.qty, -line.product_sales,
                                 -line.discount)
                            for line in txn.lines
                        ],
                        event_type="Refund",
                        channel=txn.channel,
                        refund_reason=rng.choice(REFUND_REASONS),
                    )
                )

    return transactions


# --- writing -----------------------------------------------------------------


def transaction_row(txn: Txn) -> dict[str, str]:
    row = {column: "" for column in TRANSACTION_COLUMNS}
    row.update({
        "Date": txn.day.isoformat(), "Time": txn.time, "Time Zone": "London",
        # Square's "Gross Sales" on a transaction is ALREADY net of discount.
        "Gross Sales": money(txn.net), "Discounts": money(txn.discounts),
        "Service Charges": "£0.00", "Net Sales": money(txn.net),
        "Gift Card Sales": "£0.00", "Tax": "£0.00", "Tip": "£0.00",
        "Partial Refunds": "£0.00", "Total Collected": money(txn.net),
        "Source": txn.source, "Transaction ID": txn.txn_id,
        "Payment ID": txn.payment_id, "Event Type": txn.event_type,
        "Location": BUSINESS, "Dining Option": txn.dining_option,
        "Transaction Status": "Complete", "Channel": txn.channel,
        "Discount Name": txn.discount_name, "Refund Reason": txn.refund_reason,
    })
    return row


def item_rows_for(txn: Txn) -> list[dict[str, str]]:
    rows = []
    for line in txn.lines:
        row = {column: "" for column in ITEM_COLUMNS}
        row.update({
            "Date": txn.day.isoformat(), "Time": txn.time, "Time Zone": "London",
            "Category": line.item.category, "Item": line.item.name,
            "Qty": f"{line.qty}.0", "Price Point Name": line.item.variation,
            "Product Sales": money(line.product_sales),
            "Discounts": money(line.discount), "Net Sales": money(line.net),
            "Tax": "£0.00", "Gross Sales": money(line.net),
            "Transaction ID": txn.txn_id, "Payment ID": txn.payment_id,
            "Event Type": txn.event_type, "Location": BUSINESS,
            "Dining Option": txn.dining_option, "Unit": "ea", "Count": "1",
            "Itemisation Type": line.item.itemisation, "Channel": txn.channel,
        })
        rows.append(row)
    return rows


def summary_rows_for(transactions: list[Txn]) -> list[dict[str, str]]:
    """Aggregate the item lines the way Square's own summary does.

    Positive and negative quantities are reported separately: Units Sold counts
    sales, Items Refunded is a NEGATIVE count, and the two ADD to the net.
    Refunds and Discounts & Comps follow the same sign convention.
    """
    agg: dict[tuple[str, str], dict] = {}
    for txn in transactions:
        for line in txn.lines:
            entry = agg.setdefault(line.item.key, {
                "category": line.item.category, "sold": 0, "refunded": 0,
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
    for (name, variation), entry in sorted(agg.items()):
        net = entry["product_sales"] + entry["refunds"] + entry["discounts"]
        row = {column: "" for column in SUMMARY_COLUMNS}
        row.update({
            "Item Name": name,
            "Item Variation": variation or "No description",
            "Category": entry["category"] or "Uncategorised",
            "Items Sold": str(entry["sold"]),
            "Product Sales": money(entry["product_sales"]),
            "Items Refunded": str(entry["refunded"]),
            "Refunds": money(entry["refunds"]),
            "Discounts & Comps": money(entry["discounts"]),
            "Net Sales": money(net), "Tax": "£0.00", "Gross Sales": money(net),
            "Units Sold": str(entry["sold"]),
        })
        rows.append(row)
    return rows


def write(path: Path, columns: list[str], rows: list[dict[str, str]]) -> int:
    """Write in Square's real export format: UTF-16 with BOM, TAB delimited."""
    lines = ["\t".join(columns)]
    lines += ["\t".join(row.get(column, "") for column in columns) for row in rows]
    path.write_text("\n".join(lines) + "\n", encoding="utf-16")
    return len(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--out", type=Path, default=DEFAULT_OUT_DIR,
        help=f"output directory (default: {DEFAULT_OUT_DIR})",
    )
    out_dir = parser.parse_args().out

    transactions = generate()
    out_dir.mkdir(parents=True, exist_ok=True)

    # Monthly batches, matching the production import workflow: one logical
    # import per calendar month, each reconciling on its own.
    months: dict[str, list[Txn]] = {}
    for txn in transactions:
        months.setdefault(txn.day.strftime("%Y-%m"), []).append(txn)

    print(f"The Copper Kettle — synthetic trading year (seed {SEED})")
    print(f"{START_DATE} to {START_DATE + timedelta(days=DAYS - 1)}\n")

    total_net = Decimal("0.00")
    total_items = 0
    for month, batch in sorted(months.items()):
        write(out_dir / f"transactions-{month}.csv", TRANSACTION_COLUMNS,
              [transaction_row(t) for t in batch])
        item_rows = [row for t in batch for row in item_rows_for(t)]
        write(out_dir / f"items-{month}.csv", ITEM_COLUMNS, item_rows)
        write(out_dir / f"item-sales-summary-{month}.csv", SUMMARY_COLUMNS,
              summary_rows_for(batch))

        net = sum((t.net for t in batch), Decimal("0.00"))
        payments = sum(1 for t in batch if t.event_type == "Payment")
        total_net += net
        total_items += len(item_rows)
        print(f"  {month}  {payments:>5} payments  {len(item_rows):>6} lines  "
              f"{money(net):>12}")

    payments = sum(1 for t in transactions if t.event_type == "Payment")
    refunds = sum(1 for t in transactions if t.event_type == "Refund")
    units = sum(line.qty for t in transactions for line in t.lines)
    print(f"\n  {len(months)} monthly batches in {out_dir}")
    print(f"  {payments:,} payments · {refunds} refunds · {total_items:,} item "
          f"lines · {units:,} net units")
    print(f"  annual net sales {money(total_net)}")


if __name__ == "__main__":
    main()
