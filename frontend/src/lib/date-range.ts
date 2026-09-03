/**
 * Date-range defaults and validation.
 *
 * Ranges are inclusive local calendar dates in ISO `yyyy-mm-dd`, exactly as the
 * API takes them. They are handled as strings rather than `Date` objects
 * throughout: a `Date` is an instant, and coercing a calendar date through one
 * is how a UK trading day silently becomes the previous day for a viewer in a
 * different timezone.
 */

/** The canonical trading timezone. Matches `settings.business_timezone`. */
export const BUSINESS_TIMEZONE = "Europe/London";

/** Mirrors `MAX_RANGE_DAYS` in backend/app/analytics/windows.py. */
export const MAX_RANGE_DAYS = 366;

export interface DateRange {
  /** Inclusive first local calendar day, ISO `yyyy-mm-dd`. */
  startDate: string;
  /** Inclusive last local calendar day, ISO `yyyy-mm-dd`. */
  endDate: string;
}

const ISO_DATE = /^\d{4}-\d{2}-\d{2}$/;

/**
 * Today's date in the business timezone, as ISO `yyyy-mm-dd`.
 *
 * `en-CA` is used purely because its short date format IS ISO 8601, which
 * avoids hand-assembling the string from parts.
 */
export function businessToday(now: Date = new Date()): string {
  return new Intl.DateTimeFormat("en-CA", {
    timeZone: BUSINESS_TIMEZONE,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(now);
}

/** True for a well-formed ISO date that names a real calendar day. */
export function isValidIsoDate(value: string): boolean {
  if (!ISO_DATE.test(value)) return false;
  const parsed = new Date(`${value}T00:00:00Z`);
  if (Number.isNaN(parsed.getTime())) return false;
  // Round-trips only if the day actually exists: "2026-02-30" parses, but
  // comes back as "2026-03-02".
  return parsed.toISOString().slice(0, 10) === value;
}

/** Inclusive day count, or `null` if either endpoint is not a valid date. */
export function rangeLengthDays(range: DateRange): number | null {
  if (!isValidIsoDate(range.startDate) || !isValidIsoDate(range.endDate)) {
    return null;
  }
  const start = Date.parse(`${range.startDate}T00:00:00Z`);
  const end = Date.parse(`${range.endDate}T00:00:00Z`);
  return Math.round((end - start) / 86_400_000) + 1;
}

/**
 * Why the range cannot be sent, or `null` when it can.
 *
 * These are the two rules `build_window` enforces server-side. Checking them
 * here is not a substitute for the server check — it spares the user a round
 * trip that can only fail, and lets the message point at the field.
 */
export function validateDateRange(range: DateRange): string | null {
  if (!isValidIsoDate(range.startDate)) return "Start date is not a valid date.";
  if (!isValidIsoDate(range.endDate)) return "End date is not a valid date.";

  if (range.endDate < range.startDate) {
    // ISO dates are lexicographically ordered, so a string comparison is a
    // date comparison. No parsing, no timezone.
    return "End date must not be before start date.";
  }

  const days = rangeLengthDays(range);
  if (days !== null && days > MAX_RANGE_DAYS) {
    return `Range of ${days} days exceeds the maximum of ${MAX_RANGE_DAYS} days.`;
  }

  return null;
}

/** ISO date `days` after `iso`. Negative values move backwards. */
export function addDays(iso: string, days: number): string {
  const shifted = new Date(Date.parse(`${iso}T00:00:00Z`) + days * 86_400_000);
  return shifted.toISOString().slice(0, 10);
}

/**
 * The default range: the last COMPLETE calendar month in the business timezone.
 *
 * Chosen deliberately, and computed from the clock rather than pinned to any
 * month that happens to hold data:
 *
 *   - The current month is always partial, so it under-reports on the 1st and
 *     invites a false comparison against a full previous month.
 *   - A rolling "last 30 days" straddles two months, which is not how a café
 *     operator reconciles takings or reads a supplier invoice.
 *   - A complete month is the unit the business already thinks in, and it is
 *     the same range every time the page is opened on a given day.
 *
 * LIMITATION: the backend exposes no "what data do you actually hold?"
 * endpoint, so this cannot open on the imported period. A range with no
 * imported data therefore renders as a legitimate zero period, which is
 * indistinguishable in the UI from a month the business was closed. A
 * dataset-aware selector needs a range endpoint first; see README.
 */
export function defaultDateRange(now: Date = new Date()): DateRange {
  const today = businessToday(now);
  const [year, month] = today.split("-").map(Number);

  // Month 1 of year Y rolls back to month 12 of Y-1. Date's UTC constructor
  // normalises month 0 and month -1 for us.
  const firstOfThisMonth = Date.UTC(year, month - 1, 1);
  const lastOfPreviousMonth = new Date(firstOfThisMonth - 86_400_000);
  const firstOfPreviousMonth = new Date(
    Date.UTC(lastOfPreviousMonth.getUTCFullYear(), lastOfPreviousMonth.getUTCMonth(), 1),
  );

  return {
    startDate: firstOfPreviousMonth.toISOString().slice(0, 10),
    endDate: lastOfPreviousMonth.toISOString().slice(0, 10),
  };
}
