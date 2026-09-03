"""The request contract: the only thing a language model is allowed to produce.

Every model here is `extra="forbid"` and frozen. A request carrying a field the
schema does not name — `sql`, `table`, `where`, or a typo — is rejected, not
quietly ignored, because silently dropping an unexpected key is how an
injection attempt becomes an unnoticed one.

Validation happens BEFORE any database work. Date ranges are checked by the
same `build_window` the HTTP API uses, so "no more than a year" means exactly
what it already meant; horizons are bounded by the forecast service's own
`MAX_HORIZON_DAYS`; every free-choice field is an enum or an integer with
explicit bounds. Product names are the one genuinely free-text field, and they
are values only: they reach the database as bound parameters through
SQLAlchemy and are never composed into SQL.
"""

from __future__ import annotations

from datetime import date
from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.analytics.windows import InvalidDateRange, build_window
from app.models.enums import ProductKind
from app.nlq.operations import (
    MAX_ATTACHMENT_ROWS,
    MAX_BUSIEST_HOURS,
    MAX_HORIZON_DAYS,
    MAX_MENU_EVIDENCE_ROWS,
    MAX_MIN_PAIR_ORDERS,
    MAX_PAIR_ROWS,
    MAX_PRODUCT_ROWS,
    Operation,
)
from app.schemas.forecast import ForecastTarget

#: Shared configuration. `extra="forbid"` is the load-bearing half.
STRICT = ConfigDict(extra="forbid", frozen=True)

_DATE_HELP = (
    "Inclusive local calendar date (Europe/London). The final day is included "
    "in full."
)
_KIND_HELP = (
    "Product kinds to include. Defaults to menu_item only: gift vouchers are a "
    "liability at issuance rather than menu revenue, and open-price lines have "
    "no menu identity."
)


class ProductSelector(BaseModel):
    """How a request names one product variation.

    Exactly one of `product_id` or `name` must be given. `product_id` is the
    canonical internal identifier and is what every operation ultimately runs
    on; `name` exists because a question says "Big Breakfast", not "142", and
    is resolved to an id by `app.nlq.resolution` before any analytics query
    runs.
    """

    model_config = STRICT

    product_id: int | None = Field(
        default=None,
        ge=1,
        description="Canonical product-variation identifier. Preferred when known.",
    )
    name: str | None = Field(
        default=None,
        min_length=1,
        max_length=255,
        description=(
            "Catalogue item name, matched case-insensitively after trimming "
            "and collapsing whitespace. Never a pattern: no wildcards, no "
            "fuzzy matching."
        ),
    )
    variation: str | None = Field(
        default=None,
        max_length=100,
        description=(
            'Price point, e.g. "Large". Omit to match across variations — which '
            "is ambiguous, and reported as such, when the item has more than one."
        ),
    )

    @field_validator("name", "variation")
    @classmethod
    def _no_control_characters(cls, value: str | None) -> str | None:
        """A catalogue name is printable text.

        NUL in particular is not merely unusual: PostgreSQL text cannot store
        it, so a name containing one can match nothing and would instead reach
        the driver as a DataError. Rejecting the whole C0 range keeps the rule
        simple and costs nothing real.
        """
        if value is not None and any(character < " " for character in value):
            raise ValueError("product names must not contain control characters")
        return value

    @model_validator(mode="after")
    def _exactly_one_identifier(self) -> "ProductSelector":
        if (self.product_id is None) == (self.name is None):
            raise ValueError(
                "supply exactly one of product_id or name to identify a product"
            )
        if self.product_id is not None and self.variation is not None:
            raise ValueError(
                "variation applies only when identifying a product by name; "
                "product_id already names one variation"
            )
        return self


class _DatedRequest(BaseModel):
    """Base for every operation that reads history.

    The range is validated here, in the schema, so an impossible request never
    reaches a session. `build_window` is the same function the HTTP endpoints
    call, so the maximum span and the reversed-range rule cannot drift apart.
    """

    model_config = STRICT

    start_date: date = Field(description=_DATE_HELP)
    end_date: date = Field(description=_DATE_HELP)

    @model_validator(mode="after")
    def _range_is_queryable(self):
        try:
            build_window(self.start_date, self.end_date)
        except InvalidDateRange as exc:
            raise ValueError(str(exc)) from exc
        return self


class _KindedRequest(_DatedRequest):
    kinds: tuple[ProductKind, ...] | None = Field(
        default=None, max_length=len(ProductKind), description=_KIND_HELP
    )


# --- period operations -------------------------------------------------------


class OverviewRequest(_DatedRequest):
    """Headline KPIs, optionally against the comparable previous period."""

    operation: Literal[Operation.OVERVIEW]
    compare_to_previous_period: bool = Field(
        default=False,
        description=(
            "Also measure the equal-length period immediately before this one "
            "and report the difference. 31 requested days compare against the "
            "31 days ending the day before the range opened — the same "
            "comparison product movers already uses. There is no other "
            "comparison mechanism: arbitrary period arithmetic is deliberately "
            "not expressible."
        ),
    )


class RevenueOverTimeRequest(_DatedRequest):
    operation: Literal[Operation.REVENUE_OVER_TIME]
    granularity: Literal["day", "week"] = Field(
        default="day", description="Bucket size. Weekly buckets start on Monday."
    )


class DayOfWeekRequest(_DatedRequest):
    operation: Literal[Operation.DAY_OF_WEEK]


class PeakHoursRequest(_DatedRequest):
    operation: Literal[Operation.PEAK_HOURS]
    limit: int = Field(
        default=10,
        ge=1,
        le=MAX_BUSIEST_HOURS,
        description=(
            "How many of the busiest weekday/hour cells to return. The full "
            "grid is 168 cells, most of them closed hours."
        ),
    )


class ChannelMixRequest(_DatedRequest):
    operation: Literal[Operation.CHANNEL_MIX]


# --- product operations ------------------------------------------------------


class ProductPerformanceRequest(_KindedRequest):
    operation: Literal[Operation.PRODUCT_PERFORMANCE]
    sort: Literal["net_sales", "gross_sales", "net_units", "discounts"] = Field(
        default="net_sales", description="Ranking measure, highest first."
    )
    limit: int = Field(default=10, ge=1, le=MAX_PRODUCT_ROWS)


class ProductMoversRequest(_KindedRequest):
    operation: Literal[Operation.PRODUCT_MOVERS]
    limit: int = Field(
        default=10,
        ge=1,
        le=MAX_PRODUCT_ROWS,
        description="Largest absolute change in net sales first.",
    )


class ProductTrendRequest(_DatedRequest):
    operation: Literal[Operation.PRODUCT_TREND]
    product: ProductSelector
    granularity: Literal["day", "week"] = "day"


class ProductAttachmentsRequest(_KindedRequest):
    operation: Literal[Operation.PRODUCT_ATTACHMENTS]
    product: ProductSelector
    min_pair_orders: int = Field(
        default=5,
        ge=1,
        le=MAX_MIN_PAIR_ORDERS,
        description=(
            "Exclude attachments seen fewer times than this. Lift is unstable "
            "on tiny samples, so the default is higher than the HTTP endpoint's."
        ),
    )
    limit: int = Field(default=10, ge=1, le=MAX_ATTACHMENT_ROWS)


class BasketPairsRequest(_KindedRequest):
    operation: Literal[Operation.BASKET_PAIRS]
    min_pair_orders: int = Field(default=5, ge=1, le=MAX_MIN_PAIR_ORDERS)
    sort: Literal["pair_orders", "lift", "support"] = "pair_orders"
    limit: int = Field(default=10, ge=1, le=MAX_PAIR_ROWS)


class MenuEvidenceRequest(_KindedRequest):
    operation: Literal[Operation.MENU_EVIDENCE]
    min_pair_orders: int = Field(default=5, ge=1, le=MAX_MIN_PAIR_ORDERS)
    limit: int = Field(default=10, ge=1, le=MAX_MENU_EVIDENCE_ROWS)


# --- forecast ----------------------------------------------------------------


class ForecastRequest(BaseModel):
    """A prediction request. Deliberately carries no date range.

    The forecast always starts from the last day of real imported data, which
    the service determines. Letting a caller nominate an origin would let it
    ask for a forecast of a period that has already happened and receive it
    labelled as a prediction.
    """

    model_config = STRICT

    operation: Literal[Operation.FORECAST]
    target: ForecastTarget = Field(
        default="net_sales", description="Which measure to predict."
    )
    horizon_days: int = Field(
        default=14,
        ge=1,
        le=MAX_HORIZON_DAYS,
        description=(
            f"Days ahead to predict, 1 to {MAX_HORIZON_DAYS}. Beyond a "
            "fortnight nothing in the backtest supports the forecast."
        ),
    )


#: The complete whitelist, discriminated on `operation`. Pydantic selects the
#: member schema from the tag, so an unknown operation fails against the union
#: itself rather than being matched loosely against whichever member happens to
#: accept the remaining fields.
#:
#: `operation` is REQUIRED on every member, with no default. An earlier draft
#: defaulted each model to its own tag, which read harmlessly but meant an empty
#: body `{}` satisfied the one request whose every field was optional and came
#: back as a fourteen-day forecast. A whitelist that picks an operation for a
#: caller who named none is not a whitelist.
AnalyticsRequest = Annotated[
    Union[
        OverviewRequest,
        RevenueOverTimeRequest,
        DayOfWeekRequest,
        PeakHoursRequest,
        ChannelMixRequest,
        ProductPerformanceRequest,
        ProductMoversRequest,
        ProductTrendRequest,
        ProductAttachmentsRequest,
        BasketPairsRequest,
        MenuEvidenceRequest,
        ForecastRequest,
    ],
    Field(discriminator="operation"),
]
