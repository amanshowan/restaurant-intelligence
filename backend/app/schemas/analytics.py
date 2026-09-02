"""Response schemas for the analytics endpoints."""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

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
