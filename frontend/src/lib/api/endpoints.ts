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
  LivenessResponse,
  OverviewResponse,
  PeakHoursResponse,
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
