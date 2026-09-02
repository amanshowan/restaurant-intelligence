"""Response schemas for the analytics endpoints."""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import Channel

PENCE = "Integer minor units (pence). Never a float."


class OverviewResponse(BaseModel):
    """Headline figures for one inclusive local date range."""

    model_config = ConfigDict(frozen=True)

    start_date: date = Field(description="Inclusive first local calendar day.")
    end_date: date = Field(description="Inclusive last local calendar day.")

    net_sales_pence: int = Field(
        description=f"{PENCE} Includes refunds as negative amounts."
    )
    gross_sales_pence: int = Field(description=f"{PENCE} Before discounts.")
    discounts_pence: int = Field(description=f"{PENCE} Positive.")

    payment_order_count: int = Field(
        description="Orders with event_type=payment. Refunds are excluded so "
        "they cannot inflate volume."
    )
    refund_event_count: int = Field(description="Orders with event_type=refund.")

    net_units: int = Field(
        description="Units sold minus units refunded."
    )
    average_order_value_pence: int = Field(
        description=f"{PENCE} Net sales divided by paid orders; 0 when there "
        "are none."
    )


class RevenueBucketResponse(BaseModel):
    """One point in a revenue time series."""

    model_config = ConfigDict(frozen=True)

    period_start: date = Field(
        description="Local calendar date the bucket starts on. For weekly "
        "granularity this is the Monday of the week."
    )
    net_sales_pence: int
    gross_sales_pence: int
    discounts_pence: int
    payment_order_count: int
    net_units: int


class RevenueResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    start_date: date
    end_date: date
    granularity: Literal["day", "week"]
    buckets: list[RevenueBucketResponse] = Field(
        description="Chronological. Periods with no trade appear as explicit "
        "zero buckets rather than being omitted."
    )


# --- breakdowns --------------------------------------------------------------

WeekdayName = Literal[
    "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"
]

_LOCAL_HOUR = (
    "Hour of the local trading day (Europe/London), 0-23. Not UTC: an hour "
    "extracted from UTC would shift the whole profile for seven months a year."
)


class WeekdayTotalsResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    iso_weekday: int = Field(ge=1, le=7, description="1 = Monday … 7 = Sunday.")
    weekday: WeekdayName
    net_sales_pence: int = Field(description=f"{PENCE} Includes refunds.")
    payment_order_count: int
    net_units: int
    average_order_value_pence: int = Field(
        description=f"{PENCE} 0 when the weekday has no paid orders."
    )


class DayOfWeekResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    start_date: date
    end_date: date
    weekdays: list[WeekdayTotalsResponse] = Field(
        description="Always seven entries, Monday to Sunday, in fixed order. "
        "Weekdays with no trade appear as explicit zero rows."
    )


class PeakHourCell(BaseModel):
    model_config = ConfigDict(frozen=True)

    iso_weekday: int = Field(ge=1, le=7)
    weekday: WeekdayName
    hour: int = Field(ge=0, le=23, description=_LOCAL_HOUR)
    payment_order_count: int
    net_sales_pence: int
    net_units: int


class PeakHoursResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    start_date: date
    end_date: date
    cells: list[PeakHourCell] = Field(
        description="Always 168 cells (7 weekdays x 24 hours), ordered Monday "
        "00:00 to Sunday 23:00, zero-filled so a heatmap has a stable shape."
    )
    peak_payment_order_count: int = Field(
        description="Highest payment-order count in any single cell — enough "
        "on its own to scale a heatmap's colour ramp."
    )
    busiest: list[PeakHourCell] = Field(
        description="Busiest cells by payment-order volume, most first."
    )


class ChannelMixEntry(BaseModel):
    model_config = ConfigDict(frozen=True)

    channel: Channel
    net_sales_pence: int
    payment_order_count: int
    net_units: int
    average_order_value_pence: int
    share_of_payment_orders_percent: float | None = Field(
        default=None,
        description="Percentage of paid orders in the period; null when there "
        "are none. Rounded to 2dp, so entries may not sum to exactly 100.",
    )
    share_of_net_sales_percent: float | None = Field(
        default=None,
        description="Percentage of net sales; null when total net sales is "
        "not positive, where a share would be undefined or misleading.",
    )


class ChannelMixResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    start_date: date
    end_date: date
    channels: list[ChannelMixEntry] = Field(
        description="Every canonical channel present in the period, highest "
        "net sales first. Channels are never merged."
    )
