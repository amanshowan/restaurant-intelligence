"""The closed set of operations an LLM is permitted to request, and their caps.

Every member maps to functionality that already exists in M3-M6. Nothing here
introduces a new metric definition: adding one would create a second, divergent
implementation of revenue, refunds or basket semantics, which is exactly the
failure this layer exists to prevent.

There is no `custom`, `raw`, `other` or `sql` member. A generic fallback would
reopen the hole the enum closes, because the only way to make it useful would
be to accept free text and interpret it.
"""

from __future__ import annotations

from enum import Enum

from app.analytics.windows import MAX_RANGE_DAYS
from app.forecasting.service import MAX_HORIZON_DAYS

__all__ = [
    "MAX_ATTACHMENT_ROWS",
    "MAX_BUSIEST_HOURS",
    "MAX_CANDIDATE_PRODUCTS",
    "MAX_HORIZON_DAYS",
    "MAX_MENU_EVIDENCE_ROWS",
    "MAX_MIN_PAIR_ORDERS",
    "MAX_PAIR_ROWS",
    "MAX_PRODUCT_ROWS",
    "MAX_RANGE_DAYS",
    "MAX_SERIES_BUCKETS",
    "Operation",
]


class Operation(str, Enum):
    """What the caller is asking for. One member, one specific request schema.

    Names follow the analytics vocabulary already used by the HTTP API and the
    dashboard, so the same word means the same thing in a route, a chart and a
    request from the model.
    """

    #: Headline KPIs for a period, optionally against the comparable previous one.
    OVERVIEW = "overview"
    #: Net sales and volume bucketed by trading day or Monday-start week.
    REVENUE_OVER_TIME = "revenue_over_time"
    #: Totals per weekday, summed across every occurrence in the period.
    DAY_OF_WEEK = "day_of_week"
    #: The busiest local weekday/hour cells.
    PEAK_HOURS = "peak_hours"
    #: Revenue and volume split by how the order reached the business.
    CHANNEL_MIX = "channel_mix"
    #: Ranked product variations with their share of the menu.
    PRODUCT_PERFORMANCE = "product_performance"
    #: Products gaining or losing against the comparable previous period.
    PRODUCT_MOVERS = "product_movers"
    #: One product variation's time series.
    PRODUCT_TREND = "product_trend"
    #: What else is in the basket with one anchor product.
    PRODUCT_ATTACHMENTS = "product_attachments"
    #: Unordered co-purchase pairs across the menu.
    BASKET_PAIRS = "basket_pairs"
    #: Performance, movement and strongest attachment per product, in one view.
    MENU_EVIDENCE = "menu_evidence"
    #: Short-horizon daily prediction. NOT a measured fact.
    FORECAST = "forecast"


# --- result-size caps --------------------------------------------------------
#
# The HTTP API allows `limit` up to 1000 because a dashboard can page and scroll.
# A language model cannot: thousands of rows dilute the evidence, cost tokens and
# make an answer less accurate, not more. These caps are therefore deliberately
# TIGHTER than the equivalent public endpoints, and every bundle reports the cap
# it applied alongside how many rows qualified, so truncation is always visible
# rather than silent.

#: Ranked product rows (product_performance, product_movers).
MAX_PRODUCT_ROWS = 50
#: Co-purchase pairs.
MAX_PAIR_ROWS = 50
#: Attached products for one anchor.
MAX_ATTACHMENT_ROWS = 25
#: Menu evidence rows.
MAX_MENU_EVIDENCE_ROWS = 50
#: Weekday/hour cells. The full grid is 168 cells; almost all of them are
#: closed hours, so only the busiest are returned.
MAX_BUSIEST_HOURS = 24
#: Highest `min_pair_orders` accepted. Above this every pair is filtered out
#: and the answer is an empty set for an uninteresting reason.
MAX_MIN_PAIR_ORDERS = 1000
#: Candidate products returned when a name is ambiguous.
MAX_CANDIDATE_PRODUCTS = 25

#: Date-series operations return one bucket per day in the requested range, so
#: their size is bounded by the range itself rather than by a row limit.
MAX_SERIES_BUCKETS = MAX_RANGE_DAYS
