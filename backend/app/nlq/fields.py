"""What every evidence field is, and what it is counted in.

One table, consulted by every operation, so "share_of_net_sales_percent" is
described identically whether it came from the product ranking or the menu
evidence view. Keeping it central is also what makes the provenance claim
checkable: there is one place to read to see that no derived quantity is
labelled measured.

`provenance_for` raises on a field it does not know. That is deliberate — an
unmapped field is a code change that forgot to say what its number is, and
failing loudly in the test suite is better than shipping evidence whose
provenance quietly reads as empty.
"""

from __future__ import annotations

from typing import Any

from app.nlq.evidence import EvidenceKind
from app.nlq.operations import (
    MAX_ATTACHMENT_ROWS,
    MAX_BUSIEST_HOURS,
    MAX_HORIZON_DAYS,
    MAX_MENU_EVIDENCE_ROWS,
    MAX_PAIR_ROWS,
    MAX_PRODUCT_ROWS,
    MAX_SERIES_BUCKETS,
    Operation,
)

MEASURED = EvidenceKind.MEASURED
DERIVED = EvidenceKind.DERIVED
FORECAST = EvidenceKind.FORECAST


#: Identifiers and dimension labels. Recorded in the source data, so measured:
#: a channel or a weekday is a fact about an order, not a calculation over it.
_IDENTITY: dict[str, EvidenceKind] = {
    "product_id": MEASURED,
    "product_name": MEASURED,
    "product_variation": MEASURED,
    "kind": MEASURED,
    "product_a_id": MEASURED,
    "product_a_name": MEASURED,
    "product_a_variation": MEASURED,
    "product_b_id": MEASURED,
    "product_b_name": MEASURED,
    "product_b_variation": MEASURED,
    "attachment_product_id": MEASURED,
    "attachment_product_name": MEASURED,
    "attachment_product_variation": MEASURED,
    "channel": MEASURED,
    "iso_weekday": MEASURED,
    "weekday": MEASURED,
    "hour": MEASURED,
    "period_start": MEASURED,
}

#: Aggregations of orders that happened.
_MEASURES: dict[str, EvidenceKind] = {
    "net_sales_pence": MEASURED,
    "gross_sales_pence": MEASURED,
    "discounts_pence": MEASURED,
    "payment_order_count": MEASURED,
    "refund_event_count": MEASURED,
    "net_units": MEASURED,
    "current_net_sales_pence": MEASURED,
    "previous_net_sales_pence": MEASURED,
    "current_net_units": MEASURED,
    "previous_net_units": MEASURED,
    "previous_payment_order_count": MEASURED,
    "pair_orders": MEASURED,
    "product_orders": MEASURED,
    "product_a_orders": MEASURED,
    "product_b_orders": MEASURED,
    "anchor_order_count": MEASURED,
    "eligible_order_count": MEASURED,
    "distinct_product_count": MEASURED,
    "qualifying_pair_count": MEASURED,
    "peak_payment_order_count": MEASURED,
    "trading_hour_cell_count": MEASURED,
    "total_net_sales_pence": MEASURED,
    "total_net_units": MEASURED,
    "attachment_pair_orders": MEASURED,
}

#: Arithmetic over measured quantities. True given the inputs, but not itself a
#: record of anything — including the status fields, which describe which
#: arithmetic case applied.
_DERIVED: dict[str, EvidenceKind] = {
    "average_order_value_pence": DERIVED,
    "average_selling_price_pence": DERIVED,
    "previous_average_order_value_pence": DERIVED,
    "share_of_net_sales_percent": DERIVED,
    "share_of_units_percent": DERIVED,
    "share_of_payment_orders_percent": DERIVED,
    "share_of_menu_net_sales_percent": DERIVED,
    "share_of_menu_units_percent": DERIVED,
    "discount_rate_percent": DERIVED,
    "net_sales_change_pence": DERIVED,
    "net_units_change": DERIVED,
    "payment_order_count_change": DERIVED,
    "net_sales_percent_change": DERIVED,
    "movement_status": DERIVED,
    "comparison_status": DERIVED,
    "revenue_direction": DERIVED,
    "support_percent": DERIVED,
    "confidence_a_to_b_percent": DERIVED,
    "confidence_b_to_a_percent": DERIVED,
    "lift": DERIVED,
    "attachment_rate_percent": DERIVED,
    "reverse_attachment_rate_percent": DERIVED,
    "attachment_lift": DERIVED,
}

#: Model output for days that have not happened. `date` belongs here because it
#: is a future calendar day the model was asked about, not a day anything was
#: recorded on.
_FORECAST: dict[str, EvidenceKind] = {
    "date": FORECAST,
    "predicted_value": FORECAST,
}

PROVENANCE: dict[str, EvidenceKind] = {
    **_IDENTITY,
    **_MEASURES,
    **_DERIVED,
    **_FORECAST,
}

#: What a field counts, so a consumer never infers pence from a name. Fields
#: absent here are labels or identifiers and carry no unit.
UNITS: dict[str, str] = {
    **{name: "pence" for name in PROVENANCE if name.endswith("_pence")},
    "payment_order_count": "orders",
    "previous_payment_order_count": "orders",
    "payment_order_count_change": "orders",
    "refund_event_count": "refund events",
    "net_units": "units",
    "current_net_units": "units",
    "previous_net_units": "units",
    "net_units_change": "units",
    "total_net_units": "units",
    "pair_orders": "orders",
    "product_orders": "orders",
    "product_a_orders": "orders",
    "product_b_orders": "orders",
    "anchor_order_count": "orders",
    "eligible_order_count": "orders",
    "attachment_pair_orders": "orders",
    "peak_payment_order_count": "orders",
    "distinct_product_count": "products",
    "qualifying_pair_count": "pairs",
    "trading_hour_cell_count": "weekday/hour cells",
    "iso_weekday": "ISO weekday, 1 = Monday",
    "hour": "hour of the local trading day, 0-23",
    "period_start": "local calendar date",
    **{name: "percent" for name in PROVENANCE if name.endswith("_percent")},
    "lift": "ratio, 1.0 = independence",
    "attachment_lift": "ratio, 1.0 = independence",
}

#: The hard ceiling on rows for each operation, regardless of what was asked.
MAX_ROWS: dict[Operation, int] = {
    Operation.OVERVIEW: 0,  # totals only, no rows
    Operation.REVENUE_OVER_TIME: MAX_SERIES_BUCKETS,
    Operation.DAY_OF_WEEK: 7,
    Operation.PEAK_HOURS: MAX_BUSIEST_HOURS,
    Operation.CHANNEL_MIX: 6,  # bounded by the Channel enum
    Operation.PRODUCT_PERFORMANCE: MAX_PRODUCT_ROWS,
    Operation.PRODUCT_MOVERS: MAX_PRODUCT_ROWS,
    Operation.PRODUCT_TREND: MAX_SERIES_BUCKETS,
    Operation.PRODUCT_ATTACHMENTS: MAX_ATTACHMENT_ROWS,
    Operation.BASKET_PAIRS: MAX_PAIR_ROWS,
    Operation.MENU_EVIDENCE: MAX_MENU_EVIDENCE_ROWS,
    Operation.FORECAST: MAX_HORIZON_DAYS,
}


class UnmappedEvidenceField(KeyError):
    """An evidence field with no declared provenance. A programming error."""


def _keys(rows: list[dict[str, Any]], totals: dict[str, Any]) -> list[str]:
    """Every field name emitted, in first-seen order, without duplicates."""
    seen: dict[str, None] = {}
    for row in rows:
        for key in row:
            seen.setdefault(key, None)
    for key in totals:
        seen.setdefault(key, None)
    return list(seen)


def provenance_for(
    rows: list[dict[str, Any]], totals: dict[str, Any]
) -> dict[str, EvidenceKind]:
    result: dict[str, EvidenceKind] = {}
    for key in _keys(rows, totals):
        if key not in PROVENANCE:
            raise UnmappedEvidenceField(
                f"evidence field {key!r} has no declared provenance; add it to "
                f"app/nlq/fields.py"
            )
        result[key] = PROVENANCE[key]
    return result


def units_for(
    rows: list[dict[str, Any]], totals: dict[str, Any]
) -> dict[str, str]:
    return {key: UNITS[key] for key in _keys(rows, totals) if key in UNITS}


def has_undefined(rows: list[dict[str, Any]], totals: dict[str, Any]) -> bool:
    """True when any emitted value is null — an undefined quantity, not zero."""
    if any(value is None for value in totals.values()):
        return True
    return any(value is None for row in rows for value in row.values())
