/**
 * One function per endpoint. Components call these; nothing outside this
 * directory calls `fetch` or knows a URL.
 *
 * Only the endpoints Commit 17 actually uses are here. The M3/M4 analytics
 * surface — revenue, day-of-week, peak hours, channels, products, baskets, menu
 * evidence — is added as each is wired to a view, not speculatively.
 */

import { apiFetch, type ApiFetchOptions } from "./client";
import type { DateRange } from "../date-range";
import type {
  LivenessResponse,
  OverviewResponse,
  ReadinessResponse,
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
