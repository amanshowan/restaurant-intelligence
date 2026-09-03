/**
 * The API's response shapes, mirroring the Pydantic models in
 * backend/app/schemas/.
 *
 * Hand-written rather than generated from the OpenAPI document. At this size
 * that is the smaller moving part: a generator is another container, another
 * build step and another thing to keep in sync, for types that change only when
 * an endpoint changes. If the surface grows past what one file can hold
 * honestly, generate them from `/openapi.json` instead.
 *
 * Two conventions carried over from the backend and relied on throughout:
 *
 *   - `*_pence` is an INTEGER number of pence. Never divide it before
 *     formatting; use `formatMoneyPence`.
 *   - `number | null` on a ratio means UNDEFINED — a zero denominator — not
 *     zero. Render it with `formatPercent`, which maps null to an em dash.
 */

/** backend/app/models/enums.py :: Channel */
export type Channel =
  | "in_store"
  | "collection"
  | "delivery"
  | "mixed"
  | "online"
  | "unknown";

/** backend/app/models/enums.py :: ProductKind */
export type ProductKind = "menu_item" | "gift_voucher" | "custom_amount";

/** backend/app/schemas/health.py */
export interface LivenessResponse {
  status: string;
}

export interface ReadinessResponse {
  status: string;
  database: string;
}

/** backend/app/schemas/analytics.py :: OverviewResponse */
export interface OverviewResponse {
  start_date: string;
  end_date: string;
  /** Includes refunds as negative amounts. */
  net_sales_pence: number;
  /** Before discounts. */
  gross_sales_pence: number;
  /** Positive. */
  discounts_pence: number;
  /** Payments only — refunds are excluded so they cannot inflate volume. */
  payment_order_count: number;
  refund_event_count: number;
  /** Units sold minus units refunded. */
  net_units: number;
  /** Net sales / paid orders; 0 when there are none. */
  average_order_value_pence: number;
}

/** backend/app/schemas/analytics.py :: WeekdayName */
export type WeekdayName =
  | "Monday"
  | "Tuesday"
  | "Wednesday"
  | "Thursday"
  | "Friday"
  | "Saturday"
  | "Sunday";

/** Bucket size for a time series. Weekly buckets start on Monday. */
export type Granularity = "day" | "week";

/** backend/app/schemas/analytics.py :: RevenueBucketResponse */
export interface RevenueBucket {
  /** Local calendar date the bucket starts on; the Monday for weekly. */
  period_start: string;
  net_sales_pence: number;
  gross_sales_pence: number;
  discounts_pence: number;
  payment_order_count: number;
  net_units: number;
}

/** backend/app/schemas/analytics.py :: RevenueResponse */
export interface RevenueResponse {
  start_date: string;
  end_date: string;
  granularity: Granularity;
  /**
   * Chronological, and ZERO-FILLED: a period with no trade is an explicit zero
   * bucket rather than a gap. Never filter these out — a closed day is a fact,
   * and dropping it would silently join the lines either side of it.
   *
   * With weekly granularity the FIRST bucket may start before `start_date`,
   * because a partial week is reported under the Monday it belongs to.
   */
  buckets: RevenueBucket[];
}

/** backend/app/schemas/analytics.py :: WeekdayTotalsResponse */
export interface WeekdayTotals {
  /** 1 = Monday … 7 = Sunday. */
  iso_weekday: number;
  weekday: WeekdayName;
  net_sales_pence: number;
  payment_order_count: number;
  net_units: number;
  /** 0 when the weekday has no paid orders. */
  average_order_value_pence: number;
}

/** backend/app/schemas/analytics.py :: DayOfWeekResponse */
export interface DayOfWeekResponse {
  start_date: string;
  end_date: string;
  /**
   * Always seven entries, Monday to Sunday, in fixed order — the backend
   * guarantees it, so the client does no ordering of its own.
   *
   * Each row aggregates EVERY occurrence of that weekday in the range: all the
   * Mondays summed, not one row per date.
   */
  weekdays: WeekdayTotals[];
}

/** backend/app/schemas/analytics.py :: PeakHourCell */
export interface PeakHourCell {
  iso_weekday: number;
  weekday: WeekdayName;
  /** Hour of the local trading day (Europe/London), 0-23. Already local: the
   *  client must not regroup or shift it. */
  hour: number;
  payment_order_count: number;
  net_sales_pence: number;
  net_units: number;
}

/** backend/app/schemas/analytics.py :: PeakHoursResponse */
export interface PeakHoursResponse {
  start_date: string;
  end_date: string;
  /** Always 168 cells (7 x 24), Monday 00:00 to Sunday 23:00, zero-filled. */
  cells: PeakHourCell[];
  /** Highest payment-order count in any single cell — enough on its own to
   *  scale the colour ramp. 0 for a period with no trade. */
  peak_payment_order_count: number;
  /** Busiest cells by payment-order volume, most first. */
  busiest: PeakHourCell[];
}

/** backend/app/schemas/analytics.py :: ChannelMixEntry */
export interface ChannelMixEntry {
  channel: Channel;
  net_sales_pence: number;
  payment_order_count: number;
  net_units: number;
  average_order_value_pence: number;
  /** Null when there are no paid orders — undefined, not zero. Rounded to 2dp,
   *  so entries may not sum to exactly 100. */
  share_of_payment_orders_percent: number | null;
  /** Null when total net sales is not positive, where a share would be
   *  undefined or misleading. */
  share_of_net_sales_percent: number | null;
}

/** backend/app/schemas/analytics.py :: ChannelMixResponse */
export interface ChannelMixResponse {
  start_date: string;
  end_date: string;
  /** Every canonical channel PRESENT in the period, highest net sales first.
   *  Channels absent from the period are omitted entirely, so this is not a
   *  fixed-length list and `unknown` appears only when it occurred. */
  channels: ChannelMixEntry[];
}

/**
 * backend/app/api/errors.py — the single envelope EVERY failure arrives in,
 * including FastAPI's own 422 request validation.
 */
export interface ApiErrorBody {
  detail: string;
  code: string;
  errors?: ApiValidationIssue[] | null;
}

/** backend/app/schemas/imports.py :: ValidationIssue */
export interface ApiValidationIssue {
  location: string;
  message: string;
  type: string;
}
