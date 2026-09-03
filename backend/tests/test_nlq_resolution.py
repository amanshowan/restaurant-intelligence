"""Product resolution: exact, case-insensitive, and never a guess."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.models import Order, Product
from app.nlq.resolution import ProductResolver, normalise


@pytest.fixture
def catalogue(make_sale):
    """A small menu with one genuinely ambiguous item name."""
    make_sale("2026-08-01T09:00", [("Big Breakfast", "", 1, 950)])
    make_sale("2026-08-01T09:30", [("Caffe Latte", "Regular", 1, 365)])
    make_sale("2026-08-01T10:00", [("Caffe Latte", "Large", 1, 415)])


@pytest.fixture
def resolver(session_factory):
    return ProductResolver(session_factory)


def test_normalise_only_changes_what_cannot_change_meaning():
    assert normalise("  Big   Breakfast ") == "big breakfast"
    assert normalise("BIG BREAKFAST") == "big breakfast"
    # Punctuation and plurals are left alone: "Coffee Bean" and "Coffee Beans"
    # may be two products at two prices.
    assert normalise("Coffee Beans") == "coffee beans"


def test_exact_name_resolves(resolver, catalogue, product_id):
    result = resolver.by_name("Big Breakfast")
    assert result.status == "resolved"
    assert result.match.product_id == product_id("Big Breakfast", "")
    assert result.match.name == "Big Breakfast"


@pytest.mark.parametrize(
    "asked", ["big breakfast", "BIG BREAKFAST", "bIg BrEaKfAsT", "  Big  Breakfast  "]
)
def test_case_and_whitespace_are_insensitive(resolver, catalogue, product_id, asked):
    result = resolver.by_name(asked)
    assert result.status == "resolved"
    assert result.match.product_id == product_id("Big Breakfast", "")


def test_a_name_matching_several_variations_is_ambiguous(resolver, catalogue):
    """Not a coin toss. Choosing the bigger seller would be a silent decision
    about what the caller meant."""
    result = resolver.by_name("Caffe Latte")

    assert result.status == "ambiguous"
    assert result.match is None
    assert [c.variation for c in result.candidates] == ["Large", "Regular"]


def test_a_variation_disambiguates(resolver, catalogue, product_id):
    result = resolver.by_name("Caffe Latte", "Large")
    assert result.status == "resolved"
    assert result.match.product_id == product_id("Caffe Latte", "Large")


def test_a_variation_is_matched_case_insensitively(resolver, catalogue, product_id):
    assert resolver.by_name("caffe latte", "large").match.product_id == product_id(
        "Caffe Latte", "Large"
    )


def test_candidates_are_ordered_deterministically(resolver, catalogue):
    first = resolver.by_name("Caffe Latte").candidates
    second = resolver.by_name("Caffe Latte").candidates
    assert [c.product_id for c in first] == [c.product_id for c in second]


def test_a_missing_product_is_not_found(resolver, catalogue):
    result = resolver.by_name("Lobster Thermidor")
    assert result.status == "not_found"
    assert result.match is None
    assert result.candidates == []


def test_a_substring_does_not_match(resolver, catalogue):
    """No fuzzy matching: "Latte" is not "Caffe Latte". A wrong product
    produces a confident, fluent, wrong answer."""
    assert resolver.by_name("Latte").status == "not_found"
    assert resolver.by_name("Breakfast").status == "not_found"


def test_wildcards_are_literal_characters_not_patterns(resolver, catalogue):
    """A LIKE-style match would let '%' select the whole catalogue."""
    for pattern in ("%", "Big%", "_ig Breakfast", "Caffe%"):
        assert resolver.by_name(pattern).status == "not_found"


def test_an_empty_or_whitespace_name_is_not_found(resolver, catalogue):
    assert resolver.by_name("   ").status == "not_found"


def test_resolution_by_id_is_canonical(resolver, catalogue, product_id):
    expected = product_id("Caffe Latte", "Large")
    result = resolver.by_id(expected)
    assert result.status == "resolved"
    assert result.match.product_id == expected


def test_an_unknown_id_is_not_found(resolver, catalogue):
    assert resolver.by_id(999_999).status == "not_found"


# --- adversarial -------------------------------------------------------------


INJECTION_NAMES = [
    "'; DROP TABLE orders; --",
    "Big Breakfast'; DELETE FROM order_items WHERE '1'='1",
    "' OR 1=1 --",
    'Big Breakfast" UNION SELECT * FROM products --',
    "\\'; TRUNCATE products; --",
]


@pytest.mark.parametrize("name", INJECTION_NAMES)
def test_injection_shaped_names_are_harmless_values(
    resolver, catalogue, session_factory, name
):
    """The name is compared as a bound parameter. The worst outcome is that the
    café does not sell a product by that name."""
    result = resolver.by_name(name)
    assert result.status == "not_found"

    # The tables the payloads name are still there, with their rows.
    with session_factory() as s:
        assert len(s.scalars(select(Product)).all()) == 3
        assert len(s.scalars(select(Order)).all()) == 3


def test_a_name_containing_a_null_byte_does_not_resolve(resolver, catalogue):
    assert resolver.by_name("Big Breakfast\x00").status == "not_found"
