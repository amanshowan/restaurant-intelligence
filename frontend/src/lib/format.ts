/**
 * Presentation formatting.
 *
 * The backend's discipline is that money is an integer number of pence and
 * never a float (ARCHITECTURE.md §5a). That discipline is worth keeping on this
 * side of the wire too, so the money formatter below does its arithmetic in
 * integers and only ever hands a whole number to `Intl`.
 */

/** Groups the major units — "47194" -> "47,194". No currency symbol: the
 *  symbol and the minor units are assembled by hand so no float is involved. */
const MAJOR_UNITS = new Intl.NumberFormat("en-GB", {
  useGrouping: true,
  maximumFractionDigits: 0,
});

const WHOLE_NUMBERS = new Intl.NumberFormat("en-GB", {
  useGrouping: true,
  maximumFractionDigits: 0,
});

/** Rendered wherever a value is genuinely undefined rather than zero. */
export const NOT_APPLICABLE = "—";

/**
 * Integer pence -> a GBP string, e.g. `4719408` -> `"£47,194.08"`.
 *
 * Negative amounts (a period whose refunds outweigh its sales) format as
 * `"-£12.34"`, with the sign outside the symbol.
 *
 * Deliberately NOT `Intl.NumberFormat(..., { style: "currency" })` over
 * `pence / 100`: that reintroduces the binary fraction the backend went to some
 * trouble to avoid. Splitting into major and minor units keeps every operation
 * on integers, and `Intl` only ever sees a whole number.
 */
export function formatMoneyPence(pence: number): string {
  if (!Number.isFinite(pence)) return NOT_APPLICABLE;

  // Defensive: the API contract is integer pence, but a malformed payload
  // should degrade to a sane string rather than render "£47,194.080000001".
  const value = Math.round(pence);

  const negative = value < 0;
  const absolute = Math.abs(value);
  const major = Math.trunc(absolute / 100);
  const minor = absolute % 100;

  return `${negative ? "-" : ""}£${MAJOR_UNITS.format(major)}.${String(minor).padStart(2, "0")}`;
}

/** Counts — orders, units. `2715` -> `"2,715"`. */
export function formatCount(value: number): string {
  if (!Number.isFinite(value)) return NOT_APPLICABLE;
  return WHOLE_NUMBERS.format(Math.round(value));
}

/**
 * A percentage that the API may legitimately return as `null`.
 *
 * Several backend fields — `share_of_net_sales_percent`, `lift`,
 * `attachment_rate_percent` — are `float | null`, where null means the
 * denominator was zero and the ratio is UNDEFINED, not zero. Rendering those as
 * "0%" would state something the data does not support, so null becomes an
 * em dash. This helper exists so no call site has to remember that.
 */
export function formatPercent(
  value: number | null | undefined,
  fractionDigits = 1,
): string {
  if (value === null || value === undefined || !Number.isFinite(value)) {
    return NOT_APPLICABLE;
  }
  return `${value.toFixed(fractionDigits)}%`;
}

const RANGE_LABEL = new Intl.DateTimeFormat("en-GB", {
  day: "numeric",
  month: "short",
  year: "numeric",
  timeZone: "UTC",
});

/**
 * An ISO `yyyy-mm-dd` date as a readable label, e.g. `"1 Aug 2026"`.
 *
 * Parsed as UTC and formatted as UTC. An ISO date string is a calendar date
 * with no instant attached; letting it fall through the viewer's local zone
 * would render 2026-08-01 as "31 Jul 2026" for anyone west of Greenwich.
 */
export function formatIsoDate(iso: string): string {
  const parsed = new Date(`${iso}T00:00:00Z`);
  if (Number.isNaN(parsed.getTime())) return iso;
  return RANGE_LABEL.format(parsed);
}

/** `"1 Aug 2026 – 31 Aug 2026"`, or a single date when the range is one day. */
export function formatDateRangeLabel(startIso: string, endIso: string): string {
  if (startIso === endIso) return formatIsoDate(startIso);
  return `${formatIsoDate(startIso)} – ${formatIsoDate(endIso)}`;
}

const SHORT_DATE = new Intl.DateTimeFormat("en-GB", {
  day: "numeric",
  month: "short",
  timeZone: "UTC",
});

const LONG_DATE = new Intl.DateTimeFormat("en-GB", {
  weekday: "short",
  day: "numeric",
  month: "short",
  year: "numeric",
  timeZone: "UTC",
});

/** `"2026-08-01"` -> `"1 Aug"`. For axis ticks, where the year is in the header. */
export function formatShortDate(iso: string): string {
  const parsed = new Date(`${iso}T00:00:00Z`);
  if (Number.isNaN(parsed.getTime())) return iso;
  return SHORT_DATE.format(parsed);
}

/** `"2026-08-01"` -> `"Sat 1 Aug 2026"`. For tooltips, where context is wanted. */
export function formatLongDate(iso: string): string {
  const parsed = new Date(`${iso}T00:00:00Z`);
  if (Number.isNaN(parsed.getTime())) return iso;
  return LONG_DATE.format(parsed);
}

/** `9` -> `"09:00"`. Local trading hour, already Europe/London from the API. */
export function formatHour(hour: number): string {
  return `${String(hour).padStart(2, "0")}:00`;
}

/**
 * A money value for a chart AXIS TICK, abbreviated to stay legible.
 *
 * Below £1,000 the exact pounds are shown. Above it, thousands carry ONE
 * decimal place up to £10k: rounding to whole thousands renders £1,650 and
 * £2,100 as the same "£2k", which puts two different ticks on one axis under
 * an identical label and makes the scale unreadable.
 *
 * Tick labels only. Every figure a reader acts on is rendered in full by
 * `formatMoneyPence`.
 */
export function formatAxisMoney(pence: number): string {
  const pounds = pence / 100;
  const magnitude = Math.abs(pounds);
  // Sign outside the symbol, matching formatMoneyPence: "-£1.7k", not "£-1.7k".
  const sign = pounds < 0 ? "-" : "";

  if (magnitude >= 1000) {
    const thousands = magnitude / 1000;
    const text =
      magnitude < 10_000
        ? thousands.toFixed(1).replace(/\.0$/, "")
        : String(Math.round(thousands));
    return `${sign}£${text}k`;
  }

  return `${sign}£${Math.round(magnitude)}`;
}
