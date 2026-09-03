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
