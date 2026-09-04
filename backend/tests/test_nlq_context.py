"""Date and catalogue context: deterministic, bounded, and free of order data."""

from __future__ import annotations

from datetime import date

import pytest

from app.forecasting.service import ForecastService
from app.nlq.context import CatalogueContext, ContextBuilder, DateContext
from app.nlq.operations import MAX_CATALOGUE_PRODUCTS
from app.nlq.resolution import ProductResolver


@pytest.fixture
def builder(session_factory):
    def _build(today: date = date(2026, 9, 4), **kwargs):
        return ContextBuilder(
            ProductResolver(session_factory),
            ForecastService(session_factory),
            today=today,
            **kwargs,
        )

    return _build


@pytest.fixture
def trading(make_sale):
    make_sale("2025-09-01T09:00", [("The Big Breakfast", "Regular", 1, 950)])
    make_sale("2026-08-31T09:00", [("Caffe Latte", "Regular", 1, 365),
                                   ("Caffe Latte", "Large", 1, 415)])


# --- dates -------------------------------------------------------------------


def test_the_observed_range_comes_from_the_data(builder, trading):
    context = builder().dates()
    assert context.earliest_observed_date == date(2025, 9, 1)
    assert context.latest_observed_date == date(2026, 8, 31)


def test_today_is_injected_not_read_from_the_clock(builder, trading):
    """Every relative-date assertion in this suite depends on this."""
    assert builder(today=date(2026, 3, 15)).dates().today == date(2026, 3, 15)


def test_the_timezone_is_the_business_one(builder, trading):
    assert builder().dates().timezone == "Europe/London"


def test_a_data_lag_is_stated_explicitly(builder, trading):
    """A question about "the last two weeks" answered against today, on data
    that stops earlier, returns zero buckets that look like a closed shop."""
    rendered = builder(today=date(2026, 9, 4)).dates().render()

    assert "latest_observed_date: 2026-08-31" in rendered
    assert "today: 2026-09-04" in rendered
    assert "ends 4 day(s) before today" in rendered
    assert "Never request dates after latest_observed_date" in rendered


def test_no_lag_note_when_the_data_is_current(builder, trading):
    rendered = builder(today=date(2026, 8, 31)).dates().render()
    assert "before today" not in rendered


def test_an_empty_database_is_reported_as_unanswerable(builder):
    context = builder().dates()
    assert context.has_data is False
    assert "no orders have been imported" in context.render()


def test_the_date_context_carries_no_figures(builder, trading):
    """Dates and a timezone. No revenue, no counts."""
    rendered = builder().dates().render()
    assert "950" not in rendered and "365" not in rendered


# --- catalogue ---------------------------------------------------------------


def test_the_catalogue_lists_canonical_names_and_variations(builder, trading):
    rendered = builder().catalogue().render()
    assert "The Big Breakfast | Regular" in rendered
    assert "Caffe Latte | Large" in rendered
    assert "Caffe Latte | Regular" in rendered


def test_a_product_without_a_variation_is_listed_by_name_alone(builder, make_sale):
    make_sale("2026-08-01T09:00", [("Poached Egg", "", 1, 300)])
    assert "Poached Egg\n" in builder().catalogue().render() + "\n"


def test_the_catalogue_is_ordered_deterministically(builder, make_sale):
    for name in ("Zucchini Fries", "Almond Croissant", "Mocha"):
        make_sale("2026-08-01T09:00", [(name, "", 1, 300)])

    first = builder().catalogue().render()
    assert first == builder().catalogue().render()
    assert first.index("Almond Croissant") < first.index("Mocha") < first.index(
        "Zucchini Fries"
    )


def test_the_catalogue_is_bounded_and_reports_truncation(builder, make_sale):
    for index in range(6):
        make_sale("2026-08-01T09:00", [(f"Item {index:02d}", "", 1, 100)])

    catalogue = builder(catalogue_limit=3).catalogue()

    assert len(catalogue.products) == 3
    assert catalogue.total_products == 6
    assert catalogue.truncated is True
    rendered = catalogue.render()
    assert "3 of 6 product variations" in rendered
    assert "may still exist" in rendered


def test_an_untruncated_catalogue_says_so(builder, trading):
    catalogue = builder().catalogue()
    assert catalogue.truncated is False
    assert "All 3 product variations" in catalogue.render()


def test_the_default_cap_is_the_declared_one(builder, trading):
    assert builder().catalogue().limit == MAX_CATALOGUE_PRODUCTS


def test_an_empty_catalogue_renders_safely(builder):
    assert "empty" in builder().catalogue().render()


def test_the_catalogue_carries_no_order_or_customer_data(
    builder, session_factory, trading
):
    """Names and price points only. Nothing about who bought what, or for how
    much.

    Asserted STRUCTURALLY — every product line is exactly a catalogue name, or
    a name and its variation — rather than by scanning for figures. The real
    café menu contains items called "TCL - £10.00 Gift Voucher", so a scan for
    currency or digits would flag a legitimate product name as leaked
    financial data. What matters is that no line carries anything the
    catalogue itself does not hold.
    """
    from sqlalchemy import select

    from app.models import Product

    with session_factory() as s:
        allowed = {
            f"{p.name} | {p.variation}" if p.variation else p.name
            for p in s.scalars(select(Product)).all()
        }

    lines = builder().catalogue().render().splitlines()
    product_lines = [line for line in lines[1:] if line.strip()]

    assert product_lines
    assert set(product_lines) <= allowed


def test_a_product_name_containing_a_price_is_not_mistaken_for_leaked_data(
    builder, make_sale
):
    """The real menu has gift vouchers named after their face value. The name
    is the product's identity and must reach the planner intact — otherwise it
    cannot select it, and Commit 24's exact matching would report it unknown.
    """
    make_sale("2026-08-01T09:00", [("TCL - £10.00 Gift Voucher", "Regular", 1, 1000)])
    assert "TCL - £10.00 Gift Voucher | Regular" in builder().catalogue().render()


def test_the_catalogue_does_not_weaken_exact_resolution(session_factory, trading):
    """The catalogue is a lookup table given BEFORE planning, not a fuzzy
    fallback applied after a name fails to match."""
    resolver = ProductResolver(session_factory)
    assert "The Big Breakfast" in {p.name for p in resolver.catalogue()}
    assert resolver.by_name("Big Breakfast").status == "not_found"
