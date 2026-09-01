"""Decimal-safe money parsing and DST-aware timestamp handling."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from app.adapters.parsing import (
    MoneyParseError,
    NonexistentLocalTime,
    QuantityParseError,
    TimeZoneError,
    parse_local_instant,
    parse_money_to_pence,
    parse_quantity,
    unit_price_pence,
)

UTC = ZoneInfo("UTC")


@pytest.mark.parametrize(
    "raw,pence",
    [
        ("£17.20", 1720),
        ("£0.00", 0),
        ("", 0),
        (None, 0),
        ("-£0.33", -33),      # minus BEFORE the symbol: Square writes fees this way
        ("£-0.33", -33),      # and the other way round
        ("£1,234.56", 123456),
        ("17.20", 1720),      # no symbol
        ("  £5.00  ", 500),
        ("-£50.58", -5058),
    ],
)
def test_money_parses_to_exact_pence(raw, pence):
    assert parse_money_to_pence(raw) == pence


@pytest.mark.parametrize("raw", ["£abc", "17,20", "£1.2.3", "1e5", "£"])
def test_money_rejects_junk(raw):
    with pytest.raises(MoneyParseError):
        parse_money_to_pence(raw)


def test_money_rejects_sub_penny_rather_than_rounding():
    with pytest.raises(MoneyParseError, match="sub-penny"):
        parse_money_to_pence("£0.001")


def test_money_uses_no_float_arithmetic():
    """0.1 + 0.2 != 0.3 in binary floating point; in pence it is exact."""
    total = parse_money_to_pence("£0.10") + parse_money_to_pence("£0.20")
    assert total == 30
    assert total == parse_money_to_pence("£0.30")


def test_repeated_addition_stays_exact():
    """A float accumulator drifts over thousands of rows; integers cannot."""
    assert sum(parse_money_to_pence("£0.07") for _ in range(10_000)) == 70_000


@pytest.mark.parametrize("raw,expected", [("1.0", 1), ("2.0", 2), ("-1.0", -1), ("3", 3)])
def test_quantity_parses_float_strings(raw, expected):
    assert parse_quantity(raw) == expected


@pytest.mark.parametrize("raw", ["", "abc", "1.5"])
def test_quantity_rejects_non_whole_units(raw):
    with pytest.raises(QuantityParseError):
        parse_quantity(raw)


def test_unit_price_is_derived_from_line_total():
    assert unit_price_pence(730, 2) == 365


def test_unit_price_is_positive_for_refunds():
    assert unit_price_pence(-790, -1) == 790


def test_unit_price_rounds_half_up():
    assert unit_price_pence(100, 3) == 33      # 33.33 -> 33
    assert unit_price_pence(101, 2) == 51      # 50.5  -> 51


# --- timestamps --------------------------------------------------------------


def test_bst_wall_time_converts_to_utc():
    """August is BST (UTC+1): 14:30 local is 13:30 UTC, not 14:30."""
    result = parse_local_instant("2026-08-15", "14:30:00", "London")
    assert result.utc == datetime(2026, 8, 15, 13, 30, tzinfo=UTC)
    assert result.local_date.isoformat() == "2026-08-15"
    assert not result.ambiguous


def test_gmt_wall_time_is_unchanged():
    """January is GMT (UTC+0): the same wall time maps to a different offset."""
    result = parse_local_instant("2026-01-15", "14:30:00", "London")
    assert result.utc == datetime(2026, 1, 15, 14, 30, tzinfo=UTC)


def test_midnight_boundary_crosses_the_date_in_utc():
    """00:30 BST on 1 August is 23:30 UTC on 31 JULY — the period-bounds trap."""
    result = parse_local_instant("2026-08-01", "00:30:00", "London")
    assert result.utc == datetime(2026, 7, 31, 23, 30, tzinfo=UTC)
    assert result.local_date.isoformat() == "2026-08-01"


def test_ambiguous_autumn_hour_is_flagged_not_guessed():
    """On the clocks-back Sunday 01:30 happens twice; we take the first."""
    result = parse_local_instant("2026-10-25", "01:30:00", "London")
    assert result.ambiguous is True
    assert result.utc == datetime(2026, 10, 25, 0, 30, tzinfo=UTC)  # fold=0, still BST


def test_nonexistent_spring_hour_is_rejected():
    """On the clocks-forward Sunday 01:30 does not exist at all."""
    with pytest.raises(NonexistentLocalTime):
        parse_local_instant("2026-03-29", "01:30:00", "London")


def test_unknown_zone_is_rejected():
    with pytest.raises(TimeZoneError):
        parse_local_instant("2026-08-15", "14:30:00", "Mars/Olympus")


def test_time_without_seconds_is_accepted():
    assert parse_local_instant("2026-08-15", "14:30", "London").utc == datetime(
        2026, 8, 15, 13, 30, tzinfo=UTC
    )
