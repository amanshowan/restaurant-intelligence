/**
 * Shaping API responses for the chart components.
 *
 * Everything here is a PRESENTATION transform — reordering, binning for a
 * colour ramp, projecting a flat list onto a grid. No metric is recomputed:
 * net sales, order counts, averages and shares all arrive from the API already
 * calculated, and a second implementation on this side would be a second thing
 * to get wrong and to keep in step.
 *
 * Kept as plain functions, separate from the components, so the parts that can
 * be wrong about DATA are tested without rendering anything.
 */

import type {
  ChannelMixEntry,
  Channel,
  DayOfWeekResponse,
  Granularity,
  PeakHourCell,
  PeakHoursResponse,
  RevenueResponse,
  WeekdayTotals,
} from "./api";
import { formatShortDate } from "./format";

// --- revenue -----------------------------------------------------------------

export interface RevenuePoint {
  /** ISO date the bucket starts on — the Monday, for weekly granularity. */
  periodStart: string;
  /** Axis tick label. */
  label: string;
  netSalesPence: number;
  paymentOrderCount: number;
  netUnits: number;
  grossSalesPence: number;
  discountsPence: number;
}

/**
 * The revenue response as chart points, in the order the API returned them.
 *
 * Zero buckets are KEPT. The API zero-fills deliberately so that a day with no
 * trade is visible as a zero rather than absent; dropping them here would join
 * the line across a closed day and invent trade that did not happen.
 */
export function revenuePoints(response: RevenueResponse): RevenuePoint[] {
  return response.buckets.map((bucket) => ({
    periodStart: bucket.period_start,
    label: formatShortDate(bucket.period_start),
    netSalesPence: bucket.net_sales_pence,
    paymentOrderCount: bucket.payment_order_count,
    netUnits: bucket.net_units,
    grossSalesPence: bucket.gross_sales_pence,
    discountsPence: bucket.discounts_pence,
  }));
}

/**
 * How many axis ticks to skip so labels do not collide.
 *
 * 31 daily buckets cannot each carry a legible label at dashboard width, and
 * Recharts' own collision avoidance drops them unpredictably as the container
 * resizes. Choosing the interval from the point count keeps it deterministic.
 */
export function tickInterval(pointCount: number, maxTicks = 8): number {
  if (pointCount <= maxTicks) return 0;
  return Math.ceil(pointCount / maxTicks) - 1;
}

/** Totals across a revenue series, for reconciling the chart against Overview. */
export function revenueTotals(points: RevenuePoint[]) {
  return points.reduce(
    (totals, point) => ({
      netSalesPence: totals.netSalesPence + point.netSalesPence,
      paymentOrderCount: totals.paymentOrderCount + point.paymentOrderCount,
      netUnits: totals.netUnits + point.netUnits,
    }),
    { netSalesPence: 0, paymentOrderCount: 0, netUnits: 0 },
  );
}

/** Human wording for the bucket size, used in subtitles and tooltips. */
export const GRANULARITY_LABEL: Record<Granularity, string> = {
  day: "Daily",
  week: "Weekly",
};

// --- day of week -------------------------------------------------------------

/**
 * The seven weekday rows, Monday first.
 *
 * The API already guarantees seven entries in Monday-to-Sunday order, so this
 * sorts defensively rather than correctively — it exists so the fixed order is
 * a property of the view that a test can assert, not an assumption about a
 * response that happens to arrive sorted.
 */
export function orderedWeekdays(response: DayOfWeekResponse): WeekdayTotals[] {
  return [...response.weekdays].sort((a, b) => a.iso_weekday - b.iso_weekday);
}

/** The highest net sales across the week; 0 when nothing traded. */
export function peakWeekdayNetSales(weekdays: WeekdayTotals[]): number {
  return weekdays.reduce((peak, day) => Math.max(peak, day.net_sales_pence), 0);
}

// --- peak hours --------------------------------------------------------------

export const HOURS_IN_DAY = 24;

export interface HeatmapRow {
  isoWeekday: number;
  weekday: string;
  /** Exactly 24 cells, hour 0 to 23. */
  cells: PeakHourCell[];
}

const WEEKDAY_NAMES = [
  "Monday", "Tuesday", "Wednesday", "Thursday",
  "Friday", "Saturday", "Sunday",
] as const;

function emptyCell(isoWeekday: number, hour: number): PeakHourCell {
  return {
    iso_weekday: isoWeekday,
    weekday: WEEKDAY_NAMES[isoWeekday - 1],
    hour,
    payment_order_count: 0,
    net_sales_pence: 0,
    net_units: 0,
  };
}

/**
 * The flat 168-cell list projected onto a 7 x 24 grid.
 *
 * Built by indexing rather than by trusting the response's order, so a cell
 * lands in the row and column its OWN `iso_weekday` and `hour` name. Reading
 * the list positionally would silently transpose the whole grid if the
 * ordering ever changed — a bug that still renders a plausible-looking heatmap.
 *
 * Missing cells are filled with explicit zeros. The API always sends all 168,
 * so this is belt and braces; an incomplete grid would break the layout rather
 * than shift the data.
 *
 * No timezone work happens here. Hours arrive as local Europe/London trading
 * hours and are placed exactly as given.
 */
export function heatmapRows(response: PeakHoursResponse): HeatmapRow[] {
  const index = new Map<string, PeakHourCell>();
  for (const cell of response.cells) {
    index.set(`${cell.iso_weekday}:${cell.hour}`, cell);
  }

  return WEEKDAY_NAMES.map((weekday, position) => {
    const isoWeekday = position + 1;
    return {
      isoWeekday,
      weekday,
      cells: Array.from({ length: HOURS_IN_DAY }, (_, hour) =>
        index.get(`${isoWeekday}:${hour}`) ?? emptyCell(isoWeekday, hour),
      ),
    };
  });
}

/** How many filled steps the heatmap ramp has, excluding the zero class. */
export const HEATMAP_BINS = 4;

/**
 * Which colour step a cell takes: 0 for "no trade", then 1..HEATMAP_BINS.
 *
 * Zero is its own class rather than the bottom of the ramp. A quiet hour and a
 * closed hour are different facts, and the palette's lightest step is chosen to
 * be clearly visible against the surface — so it must not also have to mean
 * "nothing happened".
 *
 * Binned rather than continuous because past roughly seven colour classes
 * adjacent shades stop being distinguishable, and a legend stops being
 * readable.
 */
export function intensityBin(count: number, peak: number): number {
  if (count <= 0 || peak <= 0) return 0;
  const bin = Math.ceil((count / peak) * HEATMAP_BINS);
  // Guards a count above `peak`, which would otherwise index past the ramp.
  return Math.min(Math.max(bin, 1), HEATMAP_BINS);
}

// --- channels ----------------------------------------------------------------

/**
 * Display names for the canonical channels.
 *
 * `mixed`, `online` and `unknown` are deliberately spelled out rather than
 * folded into a neighbour: each records a different fact about the order's
 * origin, and the backend keeps them distinct for that reason.
 */
export const CHANNEL_LABELS: Record<Channel, string> = {
  in_store: "In-store",
  collection: "Collection",
  delivery: "Delivery",
  mixed: "Mixed",
  online: "Online",
  unknown: "Unknown",
};

export function channelLabel(channel: Channel): string {
  return CHANNEL_LABELS[channel] ?? channel;
}

/** The largest net sales in the mix, for scaling the bars; 0 when empty. */
export function peakChannelNetSales(channels: ChannelMixEntry[]): number {
  return channels.reduce(
    (peak, channel) => Math.max(peak, channel.net_sales_pence),
    0,
  );
}
