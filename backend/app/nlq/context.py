"""What the planner is told about the world before it plans.

Two kinds of context, both deterministic, both derived from the database
rather than from the model's assumptions.

DATES
"Last month", "the last two weeks" and "recently" are meaningless without an
anchor, and a model asked to guess one will guess from its training cut-off.
Three dates are supplied instead:

    today                    the current local business date
    latest_observed_date     the last day the database holds an order for
    earliest_observed_date   the first

The distinction between the first two is load-bearing. `today` is what "this
month" means to a person. `latest_observed_date` is what the data can actually
support, and it is usually earlier — imports run monthly. A question about
"the last two weeks" answered against `today` on a database that stops three
weeks ago returns three weeks of zero buckets and a confident story about a
collapse in trade. The planner is told both, and told which to use.

`today` is injected rather than read from the clock inside the planner, so
every test that mentions a relative date is deterministic.

CATALOGUE
Commit 24's resolver refuses to guess: "Big Breakfast" does not match "The Big
Breakfast". That refusal is correct and stays. The catalogue context is what
makes it workable rather than obstructive — the planner is shown the real
names, so it can select one instead of inventing one. It is a lookup table
given BEFORE the question is planned, not a fuzzy fallback applied after a
name fails to match.

Names and price points only. No orders, no customers, no financial figures.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime

from app.config import BUSINESS_TZ, settings
from app.forecasting.service import ForecastService
from app.nlq.operations import MAX_CATALOGUE_PRODUCTS
from app.nlq.resolution import ProductMatch, ProductResolver


def business_today() -> date:
    """The current calendar date in the trading timezone, not UTC.

    At 00:30 London time in summer, the UTC date is still yesterday. A
    question about "today" answered against a UTC date would silently be a
    question about the previous trading day.
    """
    return datetime.now(BUSINESS_TZ).date()


@dataclass(frozen=True)
class DateContext:
    """The anchors every relative date in a question resolves against."""

    timezone: str
    today: date
    earliest_observed_date: date | None
    latest_observed_date: date | None

    @property
    def has_data(self) -> bool:
        return self.latest_observed_date is not None

    def render(self) -> str:
        """The prompt fragment. Plain, explicit, no prose to misread."""
        lines = [
            f"business_timezone: {self.timezone}",
            f"today: {self.today.isoformat()}",
        ]
        if self.has_data:
            lines += [
                f"earliest_observed_date: {self.earliest_observed_date.isoformat()}",
                f"latest_observed_date: {self.latest_observed_date.isoformat()}",
            ]
            if self.latest_observed_date < self.today:
                behind = (self.today - self.latest_observed_date).days
                lines.append(
                    f"NOTE: imported data ends {behind} day(s) before today. "
                    f"Never request dates after latest_observed_date — those "
                    f"days return zero buckets that look like closures, not "
                    f"missing imports."
                )
        else:
            lines.append(
                "NOTE: no orders have been imported. No operation can return "
                "evidence; the question is unanswerable."
            )
        return "\n".join(lines)


@dataclass(frozen=True)
class CatalogueContext:
    """The canonical product names a plan may refer to."""

    products: list[ProductMatch] = field(default_factory=list)
    total_products: int = 0
    limit: int = MAX_CATALOGUE_PRODUCTS

    @property
    def truncated(self) -> bool:
        return self.total_products > len(self.products)

    def render(self) -> str:
        """One product per line, `name | variation`, ordered deterministically.

        A flat list rather than JSON: it is the most compact form the model
        can match a spoken name against, and it keeps the prompt prefix stable
        across requests so it caches.
        """
        if not self.products:
            return "The product catalogue is empty."

        lines = [
            f"{p.name} | {p.variation}" if p.variation else p.name
            for p in self.products
        ]
        header = (
            f"{len(self.products)} of {self.total_products} product variations"
            if self.truncated
            else f"All {self.total_products} product variations"
        )
        body = "\n".join(lines)
        if self.truncated:
            body += (
                f"\n\nNOTE: the catalogue is longer than this list. A product "
                f"that is not shown may still exist; a name not on this list "
                f"will be reported as unknown rather than guessed at."
            )
        return f"{header}:\n{body}"


class ContextBuilder:
    """Assembles both contexts from the existing services.

    Two bounded queries per question — the observed range and the catalogue —
    neither of which reads an order line or a customer.
    """

    def __init__(
        self,
        resolver: ProductResolver,
        forecasts: ForecastService,
        *,
        today: date | None = None,
        catalogue_limit: int = MAX_CATALOGUE_PRODUCTS,
    ) -> None:
        self._resolver = resolver
        self._forecasts = forecasts
        # Injected in tests; None means "read the clock at question time".
        self._today = today
        self._catalogue_limit = catalogue_limit

    def dates(self) -> DateContext:
        earliest, latest = self._forecasts.observed_range()
        return DateContext(
            timezone=settings.business_timezone,
            today=self._today or business_today(),
            earliest_observed_date=earliest,
            latest_observed_date=latest,
        )

    def catalogue(self) -> CatalogueContext:
        return CatalogueContext(
            products=self._resolver.catalogue(self._catalogue_limit),
            total_products=self._resolver.count(),
            limit=self._catalogue_limit,
        )
