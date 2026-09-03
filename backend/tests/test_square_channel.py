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
        # Combinations that span the in-store/collection boundary. Both occur
        # in the real 12-month export set and belong to neither single channel.
        ("Point of Sale", "Eat In, Pick Up", Channel.MIXED),
        ("Register", "Pick Up, Eat in", Channel.MIXED),
        ("Point of Sale", "Pick Up, Takeaway", Channel.MIXED),
        ("Register", "Takeaway, Pick Up", Channel.MIXED),
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


@pytest.mark.parametrize(
    "dining_option,expected",
    [
        ("Eat In", Channel.IN_STORE),
        ("Takeaway", Channel.IN_STORE),
        ("Pick Up", Channel.COLLECTION),
        ("Eat In, Takeaway", Channel.MIXED),
        ("Eat In, Pick Up", Channel.MIXED),
        ("Pick Up, Takeaway", Channel.MIXED),
    ],
)
def test_every_dining_option_seen_in_the_real_year_resolves(dining_option, expected):
    """The complete set of Dining Option values in the 12-month export set.

    A scan of all twelve monthly Transactions exports found exactly these six.
    Two of them — "Eat In, Pick Up" and "Pick Up, Takeaway" — were unmapped and
    silently cost 81 units and £522.29 across the year before this was fixed,
    surfacing only as a reconciliation mismatch. If Square adds a seventh, this
    list is the place it should be recorded.
    """
    assert derive_channel("Point of Sale", dining_option).channel is expected


def test_single_option_channels_are_unchanged_by_the_mixed_additions():
    """The additions must not have altered what a lone option means."""
    assert derive_channel("Register", "Eat in").channel is Channel.IN_STORE
    assert derive_channel("Register", "Takeaway").channel is Channel.IN_STORE
    assert derive_channel("Register", "Pick Up").channel is Channel.COLLECTION
