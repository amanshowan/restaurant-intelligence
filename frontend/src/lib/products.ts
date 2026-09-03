/**
 * Presentation logic for the Products page.
 *
 * Sorting and filtering only. Every measure — net sales, units, shares,
 * discount rate, movement, attachment strength — arrives from
 * `/analytics/menu/evidence` already computed, and recomputing any of it here
 * would be a second implementation to keep in step with the database.
 *
 * The grain is the product VARIATION: "Regular" and "Large" are different
 * products, and the two are never merged.
 */

import type {
  MenuEvidenceResponse,
  MenuEvidenceRow,
  MovementStatus,
  ProductTrendResponse,
  RevenueDirection,
} from "./api";
import { formatShortDate } from "./format";

/** Stable identity for a row, and for the selected-product state. */
export function productKey(row: { product: { product_id: number } }): number {
  return row.product.product_id;
}

/** `"Caffe Latte"` + `"Regular"` -> `"Caffe Latte · Regular"`; name alone when
 *  the item has no price point. Used where one string is needed, such as a
 *  chart tooltip; the table keeps the two in separate columns. */
export function productLabel(name: string, variation: string): string {
  return variation ? `${name} · ${variation}` : name;
}

// --- movement ----------------------------------------------------------------

/**
 * Wording for each movement status.
 *
 * Mechanical descriptions of the arithmetic. Deliberately no "star", "winner",
 * "opportunity" or "poor performer": this system holds no cost, margin or
 * elasticity data, so it cannot support a judgement about any product.
 */
export const MOVEMENT_STATUS_LABELS: Record<MovementStatus, string> = {
  comparable: "Comparable",
  new_in_period: "New in period",
  not_comparable: "Not comparable",
};

export const MOVEMENT_STATUS_EXPLANATIONS: Record<MovementStatus, string> = {
  comparable:
    "The previous period's net sales was positive, so a percentage change is meaningful.",
  new_in_period:
    "Nothing in the previous period, something in this one. Growth from zero is undefined, not infinite.",
  not_comparable:
    "The previous period's total was zero or negative, so there is no base to divide by.",
};

/**
 * A direction marker that does not depend on colour.
 *
 * Red and green alone exclude anyone who cannot distinguish them, and print
 * and forced-colours modes drop the distinction entirely. The glyph carries the
 * direction; colour only reinforces it.
 */
export const DIRECTION_MARKS: Record<RevenueDirection, string> = {
  increasing: "▲",
  decreasing: "▼",
  unchanged: "–",
};

export const DIRECTION_LABELS: Record<RevenueDirection, string> = {
  increasing: "Increasing",
  decreasing: "Decreasing",
  unchanged: "Unchanged",
};

// --- sorting -----------------------------------------------------------------

export type ProductColumn =
  | "product"
  | "net_sales"
  | "net_units"
  | "payment_orders"
  | "average_price"
  | "share"
  | "discounts"
  | "discount_rate"
  | "movement";

export type SortDirection = "asc" | "desc";

export interface ProductSortState {
  column: ProductColumn;
  direction: SortDirection;
}

/**
 * The value a column sorts on.
 *
 * Nullable measures return null rather than 0. A product with no defined
 * average selling price has not got a price of zero, and sorting it among the
 * cheapest would state something the data does not.
 */
function sortValue(row: MenuEvidenceRow, column: ProductColumn): number | string | null {
  switch (column) {
    case "product":
      return `${row.product.name} ${row.product.variation}`.toLowerCase();
    case "net_sales":
      return row.net_sales_pence;
    case "net_units":
      return row.net_units;
    case "payment_orders":
      return row.payment_order_count;
    case "average_price":
      return row.average_selling_price_pence;
    case "share":
      return row.share_of_menu_net_sales_percent;
    case "discounts":
      return row.discounts_pence;
    case "discount_rate":
      return row.discount_rate_percent;
    case "movement":
      // Sorts on the absolute money change, which every row has, rather than
      // on the percentage, which is undefined for new_in_period rows.
      return row.net_sales_change_pence;
  }
}

/**
 * Rows sorted by one column.
 *
 * Nulls always sort LAST regardless of direction: an undefined value is not
 * the smallest value, and letting it lead an ascending sort would put "we
 * cannot say" at the top of a ranking.
 */
export function sortEvidenceRows(
  rows: MenuEvidenceRow[],
  { column, direction }: ProductSortState,
): MenuEvidenceRow[] {
  const factor = direction === "asc" ? 1 : -1;

  return [...rows].sort((a, b) => {
    const left = sortValue(a, column);
    const right = sortValue(b, column);

    if (left === null && right === null) return 0;
    if (left === null) return 1;
    if (right === null) return -1;

    if (typeof left === "string" || typeof right === "string") {
      return String(left).localeCompare(String(right)) * factor;
    }
    return (left - right) * factor;
  });
}

/** The direction a column should take when first selected. */
export function defaultDirectionFor(column: ProductColumn): SortDirection {
  // Names read naturally A-Z; every measure is more useful largest-first.
  return column === "product" ? "asc" : "desc";
}

// --- filtering ---------------------------------------------------------------

/**
 * Case-insensitive substring match over name and variation.
 *
 * A plain `includes` rather than fuzzy matching: the whole catalogue is already
 * in memory, an operator searching a menu knows what the item is called, and a
 * fuzzy index would be a dependency and a source of surprising matches for no
 * gain at this size.
 */
export function filterEvidenceRows(
  rows: MenuEvidenceRow[],
  query: string,
): MenuEvidenceRow[] {
  const needle = query.trim().toLowerCase();
  if (!needle) return rows;

  return rows.filter((row) =>
    `${row.product.name} ${row.product.variation}`.toLowerCase().includes(needle),
  );
}

/**
 * Drops rows with no net revenue.
 *
 * OFF by default, and surfaced as a labelled control rather than applied
 * quietly. `Tap Water / Regular` is a real menu item that sells hundreds of
 * units at £0.00 and appears throughout the basket data; hiding it silently
 * would misrepresent the menu. This exists only so an operator can set it
 * aside deliberately when ranking by revenue.
 */
export function excludeZeroRevenue(rows: MenuEvidenceRow[]): MenuEvidenceRow[] {
  return rows.filter((row) => row.net_sales_pence !== 0);
}

// --- summary -----------------------------------------------------------------

export interface EvidenceSummary {
  /** Product variations matching the filter, as counted by the response. */
  variationCount: number;
  menuNetSalesPence: number;
  menuNetUnits: number;
  leadingBySales: MenuEvidenceRow | null;
  leadingByUnits: MenuEvidenceRow | null;
}

/**
 * Headline figures, taken only from what the response already reports.
 *
 * `total_net_sales_pence` and `total_net_units` are the backend's own totals
 * over every matching product before any limit — NOT a sum of the rows on
 * screen, which would quietly change meaning as soon as a filter was applied.
 */
export function summariseEvidence(
  response: MenuEvidenceResponse,
): EvidenceSummary {
  const leadingBySales = response.rows.reduce<MenuEvidenceRow | null>(
    (best, row) =>
      best === null || row.net_sales_pence > best.net_sales_pence ? row : best,
    null,
  );
  const leadingByUnits = response.rows.reduce<MenuEvidenceRow | null>(
    (best, row) => (best === null || row.net_units > best.net_units ? row : best),
    null,
  );

  return {
    variationCount: response.rows.length,
    menuNetSalesPence: response.total_net_sales_pence,
    menuNetUnits: response.total_net_units,
    leadingBySales,
    leadingByUnits,
  };
}

// --- trend -------------------------------------------------------------------

export interface ProductTrendPoint {
  periodStart: string;
  label: string;
  netSalesPence: number;
  netUnits: number;
  paymentOrderCount: number;
  discountsPence: number;
}

/**
 * Trend buckets as chart points, in the order the API returned them.
 *
 * Zero buckets are KEPT, for the same reason as the revenue series: the API
 * zero-fills so a period with no sales is explicit, and dropping those would
 * join the line across a gap and invent sales that did not happen.
 */
export function productTrendPoints(
  response: ProductTrendResponse,
): ProductTrendPoint[] {
  return response.buckets.map((bucket) => ({
    periodStart: bucket.period_start,
    label: formatShortDate(bucket.period_start),
    netSalesPence: bucket.net_sales_pence,
    netUnits: bucket.net_units,
    paymentOrderCount: bucket.payment_order_count,
    discountsPence: bucket.discounts_pence,
  }));
}
