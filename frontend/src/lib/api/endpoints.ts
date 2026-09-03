/**
 * One function per endpoint. Components call these; nothing outside this
 * directory calls `fetch` or knows a URL.
 *
 * Endpoints are added as each is wired to a view rather than speculatively, so
 * the product, basket and menu-evidence surface is not here yet.
 */

import { apiFetch, type ApiFetchOptions } from "./client";
import type { DateRange } from "../date-range";
import type {
  ChannelMixResponse,
  DayOfWeekResponse,
  Granularity,
  ImportSummary,
  LivenessResponse,
  MenuEvidenceResponse,
  OverviewResponse,
  PairSort,
  PeakHoursResponse,
  ProductAttachmentsResponse,
  ProductKind,
  ProductListResponse,
  ProductMoversResponse,
  ProductSort,
  ProductTrendResponse,
  ProductPairsResponse,
  ReadinessResponse,
  RevenueResponse,
} from "./types";

/** Every analytics endpoint takes the same inclusive local date range. */
function rangeQuery(range: DateRange) {
  return { start_date: range.startDate, end_date: range.endDate };
}

/** `GET /health` — is the API process alive? */
export function getLiveness(options?: ApiFetchOptions) {
  return apiFetch<LivenessResponse>("/health", options);
}

/**
 * `GET /health/ready` — can the API reach the database?
 *
 * Returns 503 with the same error envelope when it cannot, so a failure
 * arrives as an `ApiError` like any other.
 */
export function getReadiness(options?: ApiFetchOptions) {
  return apiFetch<ReadinessResponse>("/health/ready", options);
}

/** `GET /analytics/overview` — headline KPIs for an inclusive date range. */
export function getOverview(range: DateRange, options?: ApiFetchOptions) {
  return apiFetch<OverviewResponse>("/analytics/overview", {
    ...options,
    query: rangeQuery(range),
  });
}


/**
 * `GET /analytics/revenue` — net sales and volume over time.
 *
 * `granularity` is part of the request, not something to derive by re-bucketing
 * daily data: weekly buckets are Monday-based and computed in the database,
 * and re-summing them here would be a second implementation of the same rule.
 */
export function getRevenue(
  range: DateRange,
  granularity: Granularity,
  options?: ApiFetchOptions,
) {
  return apiFetch<RevenueResponse>("/analytics/revenue", {
    ...options,
    query: { ...rangeQuery(range), granularity },
  });
}

/** `GET /analytics/day-of-week` — Monday-to-Sunday totals across the period. */
export function getDayOfWeek(range: DateRange, options?: ApiFetchOptions) {
  return apiFetch<DayOfWeekResponse>("/analytics/day-of-week", {
    ...options,
    query: rangeQuery(range),
  });
}

/** `GET /analytics/peak-hours` — the 7x24 local-hour grid. */
export function getPeakHours(range: DateRange, options?: ApiFetchOptions) {
  return apiFetch<PeakHoursResponse>("/analytics/peak-hours", {
    ...options,
    query: rangeQuery(range),
  });
}

/** `GET /analytics/channels` — how orders reached the business. */
export function getChannels(range: DateRange, options?: ApiFetchOptions) {
  return apiFetch<ChannelMixResponse>("/analytics/channels", {
    ...options,
    query: rangeQuery(range),
  });
}


// --- products, menu evidence and baskets -------------------------------------
//
// `kind` is repeatable on every endpoint below. It is passed through
// `buildQuery`, which serialises an array as REPEATED KEYS — the only form
// FastAPI reads as a list. Left undefined, the server applies its own default
// of `menu_item` only, which is what these pages want; passing it explicitly is
// for when a caller needs gift vouchers or open-price lines included.

/**
 * `GET /analytics/menu/evidence` — every measurable fact about each product
 * variation, in one row.
 *
 * Preferred over composing the same evidence from `/products`, `/movers` and
 * `/attachments`: it is one request instead of three, the movement and
 * attachment figures are computed against the same window, and the shares are
 * taken over every matching product rather than only those returned.
 *
 * EVIDENCE ONLY. No field recommends an action.
 */
export function getMenuEvidence(
  range: DateRange,
  options?: ApiFetchOptions & {
    limit?: number;
    minPairOrders?: number;
    kinds?: ProductKind[];
  },
) {
  const { limit, minPairOrders, kinds, ...fetchOptions } = options ?? {};
  return apiFetch<MenuEvidenceResponse>("/analytics/menu/evidence", {
    ...fetchOptions,
    query: {
      ...rangeQuery(range),
      limit,
      min_pair_orders: minPairOrders,
      kind: kinds,
    },
  });
}

/** `GET /analytics/products` — performance per product variation. */
export function getProducts(
  range: DateRange,
  options?: ApiFetchOptions & {
    sort?: ProductSort;
    limit?: number;
    kinds?: ProductKind[];
  },
) {
  const { sort, limit, kinds, ...fetchOptions } = options ?? {};
  return apiFetch<ProductListResponse>("/analytics/products", {
    ...fetchOptions,
    query: { ...rangeQuery(range), sort, limit, kind: kinds },
  });
}

/**
 * `GET /analytics/products/movers` — movement against the previous comparable
 * period, which the SERVER chooses (an equal-length window immediately before)
 * and reports back on the response.
 */
export function getProductMovers(
  range: DateRange,
  options?: ApiFetchOptions & { limit?: number; kinds?: ProductKind[] },
) {
  const { limit, kinds, ...fetchOptions } = options ?? {};
  return apiFetch<ProductMoversResponse>("/analytics/products/movers", {
    ...fetchOptions,
    query: { ...rangeQuery(range), limit, kind: kinds },
  });
}

/** `GET /analytics/products/{id}/trend` — one product over time. */
export function getProductTrend(
  productId: number,
  range: DateRange,
  granularity: Granularity,
  options?: ApiFetchOptions,
) {
  return apiFetch<ProductTrendResponse>(
    `/analytics/products/${productId}/trend`,
    { ...options, query: { ...rangeQuery(range), granularity } },
  );
}

/** `GET /analytics/products/{id}/attachments` — what else is in the basket. */
export function getProductAttachments(
  productId: number,
  range: DateRange,
  options?: ApiFetchOptions & {
    minPairOrders?: number;
    limit?: number;
    kinds?: ProductKind[];
  },
) {
  const { minPairOrders, limit, kinds, ...fetchOptions } = options ?? {};
  return apiFetch<ProductAttachmentsResponse>(
    `/analytics/products/${productId}/attachments`,
    {
      ...fetchOptions,
      query: {
        ...rangeQuery(range),
        min_pair_orders: minPairOrders,
        limit,
        kind: kinds,
      },
    },
  );
}

/**
 * `GET /analytics/baskets/pairs` — products bought together.
 *
 * `minPairOrders` is applied by the SERVER, and the response echoes both the
 * threshold used and how many pairs qualified, so the UI can state the filter
 * it is showing you rather than quietly applying one.
 */
export function getBasketPairs(
  range: DateRange,
  options?: ApiFetchOptions & {
    minPairOrders?: number;
    sort?: PairSort;
    limit?: number;
    kinds?: ProductKind[];
  },
) {
  const { minPairOrders, sort, limit, kinds, ...fetchOptions } = options ?? {};
  return apiFetch<ProductPairsResponse>("/analytics/baskets/pairs", {
    ...fetchOptions,
    query: {
      ...rangeQuery(range),
      min_pair_orders: minPairOrders,
      sort,
      limit,
      kind: kinds,
    },
  });
}


// --- imports -----------------------------------------------------------------

export interface SquareImportFiles {
  /** Square Transactions export. Required. */
  transactions: File;
  /** Square Items Detail export. Required. */
  items: File;
  /** Square Items Summary export. Optional; used only to reconcile. */
  summary?: File | null;
  /** Human-readable batch name, e.g. "august-2026". */
  label?: string;
}

/**
 * Builds the multipart body for `POST /imports/square`.
 *
 * Field names match the backend's `File(...)` / `Form(...)` parameters exactly.
 * An absent optional file is OMITTED rather than appended as an empty value:
 * the handler treats a part with no filename as no file, and sending one
 * anyway invites it to be spooled as an empty summary and fail reconciliation.
 *
 * Exported so the shape of the request can be tested without a network.
 */
export function buildSquareImportBody(files: SquareImportFiles): FormData {
  const form = new FormData();
  form.append("transactions", files.transactions);
  form.append("items", files.items);
  if (files.summary) form.append("summary", files.summary);

  const label = files.label?.trim();
  if (label) form.append("label", label);

  return form;
}

/**
 * `POST /imports/square` — ingest one logical Square export set.
 *
 * The browser posts to the same-origin `/api` path and the Next.js rewrite
 * forwards it to FastAPI, so the upload takes the same route as every other
 * request and no CORS policy is involved.
 *
 * No parsing or validation happens here. Square's format is asserted, the
 * period derived from file contents and the totals reconciled by the BACKEND;
 * duplicating any of that in TypeScript would be a second implementation that
 * could disagree with the one that actually writes the data.
 */
export function importSquareExport(
  files: SquareImportFiles,
  options?: ApiFetchOptions,
) {
  return apiFetch<ImportSummary>("/imports/square", {
    ...options,
    method: "POST",
    body: buildSquareImportBody(files),
  });
}
