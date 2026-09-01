"""Decimal-safe and timezone-safe primitives for parsing Square exports.

Deliberately free of float arithmetic: every monetary value goes through
Decimal and lands as an integer number of pence (ARCHITECTURE.md §4).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, time
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo

UTC = ZoneInfo("UTC")

#: Square writes a zone NAME, not a UTC offset. Mapping it to a real IANA zone
#: is what makes DST handling possible at all.
ZONE_ALIASES: dict[str, str] = {
    "London": "Europe/London",
    "Europe/London": "Europe/London",
}

# Accepts "£17.20", "-£0.33", "£-0.33", "£1,234.56", "17.20", "".
# The minus may appear before OR after the currency symbol; Square writes
# "-£0.33" for fees, which trips naive symbol-stripping.
_MONEY_RE = re.compile(
    r"^(?P<lead>-)?\s*£?\s*(?P<num>-?\d{1,3}(?:,\d{3})*(?:\.\d+)?|-?\d+(?:\.\d+)?)$"
)


class MoneyParseError(ValueError):
    """A monetary cell could not be read as an exact pence amount."""


class QuantityParseError(ValueError):
    """A quantity cell could not be read as a whole number of units."""


class TimeZoneError(ValueError):
    """The export named a time zone the adapter does not recognise."""


class NonexistentLocalTime(ValueError):
    """The local time does not exist (clocks jumped forward over it)."""


def parse_money_to_pence(raw: str | None) -> int:
    """Return an exact integer number of pence.

    Empty cells are 0. Sub-penny precision is an error rather than something
    to round away silently — if Square ever emits it we want to know.
    """
    text = (raw or "").strip()
    if not text:
        return 0

    match = _MONEY_RE.match(text)
    if match is None:
        raise MoneyParseError(f"cannot parse {raw!r} as a monetary amount")

    try:
        amount = Decimal(match.group("num").replace(",", ""))
    except InvalidOperation as exc:  # pragma: no cover - regex already guards
        raise MoneyParseError(f"cannot parse {raw!r} as a monetary amount") from exc

    if match.group("lead"):
        amount = -amount

    pence = amount * 100
    if pence != pence.to_integral_value():
        raise MoneyParseError(f"{raw!r} has sub-penny precision")
    return int(pence)


def parse_quantity(raw: str | None) -> int:
    """Square writes quantities as floats-in-strings ("1.0", "-1.0")."""
    text = (raw or "").strip()
    if not text:
        raise QuantityParseError("quantity is empty")
    try:
        value = Decimal(text)
    except InvalidOperation as exc:
        raise QuantityParseError(f"cannot parse {raw!r} as a quantity") from exc
    if value != value.to_integral_value():
        raise QuantityParseError(f"{raw!r} is not a whole number of units")
    return int(value)


def unit_price_pence(line_total_pence: int, quantity: int) -> int:
    """Derive a unit price; Square exports line totals, not unit prices.

    Uses magnitudes so a refund (negative total, negative quantity) still
    yields a positive unit price. The line total remains authoritative for
    money — this is a derived convenience.
    """
    if quantity == 0:
        raise QuantityParseError("cannot derive a unit price from zero quantity")
    total, qty = abs(line_total_pence), abs(quantity)
    # Integer arithmetic with explicit half-up rounding; no float division.
    return (total + qty // 2) // qty


@dataclass(frozen=True)
class ParsedInstant:
    """A local wall time resolved to a UTC instant, with DST caveats."""

    utc: datetime
    local_date: date
    #: True when the wall time occurred twice (clocks went back). fold=0 is
    #: used, i.e. the FIRST (still-BST) occurrence.
    ambiguous: bool = False


def parse_local_instant(
    date_text: str, time_text: str, zone_text: str
) -> ParsedInstant:
    """Interpret Square's Date + Time + Time Zone as a UTC instant.

    Square exports wall-clock time plus a zone NAME. Treating those columns as
    UTC shifts every British Summer Time record by an hour — which produces a
    plausible-looking but wrong peak-hour analysis rather than a crash.
    """
    zone_name = ZONE_ALIASES.get(zone_text.strip())
    if zone_name is None:
        raise TimeZoneError(f"unrecognised time zone {zone_text!r}")
    tz = ZoneInfo(zone_name)

    naive = _parse_naive(date_text, time_text)
    local = naive.replace(tzinfo=tz)

    # A nonexistent time (the spring-forward gap) round-trips to a different
    # wall time. Real data should never contain one; if it does, that is a
    # fault to report, not to paper over.
    if local.astimezone(UTC).astimezone(tz).replace(tzinfo=None) != naive:
        raise NonexistentLocalTime(
            f"{naive.isoformat()} does not exist in {zone_name} (DST gap)"
        )

    ambiguous = local.replace(fold=0).utcoffset() != local.replace(fold=1).utcoffset()

    return ParsedInstant(
        utc=local.astimezone(UTC), local_date=naive.date(), ambiguous=ambiguous
    )


def _parse_naive(date_text: str, time_text: str) -> datetime:
    d = (date_text or "").strip()
    t = (time_text or "").strip()
    if not d:
        raise ValueError("date is empty")
    try:
        day = date.fromisoformat(d)
    except ValueError as exc:
        raise ValueError(f"cannot parse date {date_text!r}") from exc

    for fmt in ("%H:%M:%S", "%H:%M"):
        try:
            clock = datetime.strptime(t, fmt).time()
            break
        except ValueError:
            continue
    else:
        if t:
            raise ValueError(f"cannot parse time {time_text!r}")
        clock = time(0, 0)

    return datetime.combine(day, clock)
