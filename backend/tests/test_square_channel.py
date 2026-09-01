"""Canonical channel derivation from Square's Source + Dining Option."""

from __future__ import annotations

import pytest

from app.adapters.square import derive_channel
from app.models.enums import Channel


@pytest.mark.parametrize(
    "source,dining_option,expected",
    [
        # Counter sales. Takeaway at the counter is still an in-store sale:
        # no platform commission was paid.
        ("Register", "Eat in", Channel.IN_STORE),
        ("Point of Sale", "Eat in", Channel.IN_STORE),
        ("Register", "Takeaway", Channel.IN_STORE),
        # Ordered ahead and collected.
        ("Register", "Pick Up", Channel.COLLECTION),
        # Delivery platforms.
        ("Uber Eats", "", Channel.DELIVERY),
        ("Just Eat", "", Channel.DELIVERY),
        ("Deliveroo", "", Channel.DELIVERY),
        # Platform pickup variants are collection, not delivery.
        ("Deliveroo Pickup", "", Channel.COLLECTION),
        ("Just Eat Pickup", "", Channel.COLLECTION),
        ("Uber Eats Pickup", "", Channel.COLLECTION),
        # An order containing both is genuinely mixed.
        ("Register", "Eat in, Takeaway", Channel.MIXED),
        ("Register", "Takeaway, Eat in", Channel.MIXED),
        ("Point of Sale", "Eat in, Takeaway", Channel.MIXED),
    ],
)
def test_agreed_mapping(source, dining_option, expected):
    assert derive_channel(source, dining_option).channel is expected


def test_derivation_is_case_and_whitespace_insensitive():
    assert derive_channel("  register ", " EAT IN ").channel is Channel.IN_STORE


@pytest.mark.parametrize(
    "source,dining_option",
    [
        ("Register", ""),            # counter sale with no dining option
        ("Some New Platform", ""),   # a source we have never seen
        ("Register", "Delivery"),    # a dining option we have never seen
    ],
)
def test_unmapped_combinations_are_explicit_outcomes_not_guesses(source, dining_option):
    derivation = derive_channel(source, dining_option)
    assert derivation.channel is None
    assert derivation.reason  # always explains itself


def test_squares_own_channel_column_is_not_our_channel():
    """Square's `Channel` holds the POS/integration name ("Deliverect"), which
    must never be mistaken for how the order reached the business."""
    assert derive_channel("Deliverect", "").channel is None


def test_square_online_maps_to_the_online_channel():
    """Not collection, not delivery: the export carries no fulfilment evidence,
    and guessing would put revenue in the wrong channel-mix bucket."""
    assert derive_channel("Square Online", "").channel is Channel.ONLINE


def test_square_online_still_honours_an_explicit_dining_option():
    """A dining option IS evidence, and takes priority over the fallback."""
    assert derive_channel("Square Online", "Pick Up").channel is Channel.COLLECTION
    assert derive_channel("Square Online", "Eat in").channel is Channel.IN_STORE
