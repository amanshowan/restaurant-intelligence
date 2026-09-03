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

// --- products, menu evidence and baskets (M4) --------------------------------

/** Sort orders accepted by `/analytics/products`. */
export type ProductSort = "net_sales" | "gross_sales" | "net_units" | "discounts";

/** Sort orders accepted by `/analytics/baskets/pairs`. */
export type PairSort = "pair_orders" | "lift" | "support";

/**
 * backend/app/analytics/service.py :: MovementStatus
 *
 * Why a percentage change is or is not defined. Describes the ARITHMETIC, not
 * the business — nothing here says a product is doing well or badly.
 *
 *   comparable      previous period was positive, so a percentage is meaningful
 *                   (including a fall to zero, a well-defined -100%)
 *   new_in_period   nothing before, something now. Growth from zero is not
 *                   infinite, it is undefined
 *   not_comparable  previous total was zero or negative — no base to divide by
 */
export type MovementStatus = "comparable" | "new_in_period" | "not_comparable";

/**
 * backend/app/analytics/service.py :: RevenueDirection
 * Sign of the change in net sales. Factual, not a judgement.
 */
export type RevenueDirection = "increasing" | "decreasing" | "unchanged";

/**
 * A product VARIATION — the grain everything here is keyed on.
 * "Regular" and "Large" are different products, and `variation` is "" when the
 * item has no price point.
 */
export interface ProductIdentity {
  product_id: number;
  name: string;
  variation: string;
  kind: ProductKind;
}

/** backend/app/schemas/products.py :: ProductPerformance */
export interface ProductPerformance extends ProductIdentity {
  gross_sales_pence: number;
  /** Recorded by the source for this exact line, not apportioned. */
  discounts_pence: number;
  net_sales_pence: number;
  net_units: number;
  /** Distinct payment orders containing this product, not the line count. */
  payment_order_count: number;
  /** Null when net units is not positive: no selling price is meaningful. */
  average_selling_price_pence: number | null;
  share_of_net_sales_percent: number | null;
  share_of_units_percent: number | null;
}

/** backend/app/schemas/products.py :: ProductListResponse */
export interface ProductListResponse {
  start_date: string;
  end_date: string;
  kinds: ProductKind[];
  sort: ProductSort;
  /** Across every product matching `kinds`, BEFORE any limit is applied. */
  total_net_sales_pence: number;
  total_net_units: number;
  products: ProductPerformance[];
}

/** backend/app/schemas/products.py :: ProductTrendBucket */
export interface ProductTrendBucket {
  period_start: string;
  gross_sales_pence: number;
  discounts_pence: number;
  net_sales_pence: number;
  net_units: number;
  payment_order_count: number;
}

/** backend/app/schemas/products.py :: ProductTrendResponse */
export interface ProductTrendResponse {
  start_date: string;
  end_date: string;
  granularity: Granularity;
  product: ProductPerformance;
  /** Chronological and zero-filled: a period with no sales is an explicit zero. */
  buckets: ProductTrendBucket[];
}

/** backend/app/schemas/products.py :: ProductMovement */
export interface ProductMovement extends ProductIdentity {
  current_net_sales_pence: number;
  previous_net_sales_pence: number;
  net_sales_change_pence: number;
  /** Null unless the previous period's net sales was positive. */
  net_sales_percent_change: number | null;
  current_net_units: number;
  previous_net_units: number;
  net_units_change: number;
  status: MovementStatus;
}

/** backend/app/schemas/products.py :: ProductMoversResponse */
export interface ProductMoversResponse {
  start_date: string;
  end_date: string;
  /** The equal-length period immediately preceding, chosen by the backend. */
  previous_start_date: string;
  previous_end_date: string;
  kinds: ProductKind[];
  movements: ProductMovement[];
}

/** backend/app/schemas/baskets.py :: BasketProduct */
export interface BasketProduct {
  product_id: number;
  name: string;
  variation: string;
}

/** backend/app/schemas/baskets.py :: AttachmentEntry */
export interface AttachmentEntry {
  product: BasketProduct;
  /** Payment orders containing both the anchor and this product. */
  pair_orders: number;
  /** Payment orders containing this product at all. */
  product_orders: number;
  /** orders with both / orders with the ANCHOR. Null when the ratio is undefined. */
  attachment_rate_percent: number | null;
  /** orders with both / orders with THIS product. High when it rarely appears alone. */
  reverse_attachment_rate_percent: number | null;
  support_percent: number | null;
  lift: number | null;
}

/** backend/app/schemas/baskets.py :: ProductAttachmentsResponse */
export interface ProductAttachmentsResponse {
  start_date: string;
  end_date: string;
  kinds: ProductKind[];
  min_pair_orders: number;
  anchor: BasketProduct;
  /** Eligible payment orders containing the anchor — the denominator for
   *  `attachment_rate_percent`. */
  anchor_order_count: number;
  eligible_order_count: number;
  attachments: AttachmentEntry[];
}

/** backend/app/schemas/baskets.py :: ProductPairEntry */
export interface ProductPairEntry {
  /**
   * The pair is UNORDERED — each unordered pair appears exactly once, and
   * (A,A) never appears. The two confidences below are the directional
   * readings of that one symmetric fact.
   */
  product_a: BasketProduct;
  product_b: BasketProduct;
  /** Distinct payment orders containing both. Quantity is irrelevant. */
  pair_orders: number;
  product_a_orders: number;
  product_b_orders: number;
  /** orders with both / eligible payment orders. */
  support_percent: number | null;
  confidence_a_to_b_percent: number | null;
  confidence_b_to_a_percent: number | null;
  /**
   * support(A,B) / (support(A) x support(B)). 1.0 means they co-occur exactly
   * as often as independence predicts. Read WITH `pair_orders`: a pair seen
   * twice can show a very high lift that means almost nothing.
   */
  lift: number | null;
}

/** backend/app/schemas/baskets.py :: ProductPairsResponse */
export interface ProductPairsResponse {
  start_date: string;
  end_date: string;
  kinds: ProductKind[];
  sort: PairSort;
  /** Pairs occurring fewer times than this are excluded by the SERVER. */
  min_pair_orders: number;
  /** Payment orders containing at least one included product — support's denominator. */
  eligible_order_count: number;
  distinct_product_count: number;
  /** Pairs meeting `min_pair_orders`, BEFORE `limit` is applied. */
  qualifying_pair_count: number;
  pairs: ProductPairEntry[];
}

/** backend/app/schemas/menu.py :: EvidenceProduct */
export interface EvidenceProduct {
  product_id: number;
  name: string;
  variation: string;
}

/** backend/app/schemas/menu.py :: AttachmentEvidenceEntry */
export interface AttachmentEvidenceEntry {
  product: EvidenceProduct;
  pair_orders: number;
  attachment_rate_percent: number | null;
  lift: number | null;
}

/**
 * backend/app/schemas/menu.py :: MenuEvidenceRowResponse
 *
 * A decision-EVIDENCE row, not a recommendation. Nothing in it says a product
 * should be repriced, promoted or removed: those claims need cost, margin and
 * price-elasticity data the system does not hold.
 */
export interface MenuEvidenceRow {
  product: EvidenceProduct;
  kind: ProductKind;

  gross_sales_pence: number;
  /** EXACT per-line values from the source export, not apportioned. */
  discounts_pence: number;
  net_sales_pence: number;
  net_units: number;
  payment_order_count: number;

  average_selling_price_pence: number | null;
  /** discounts / gross sales. Null when gross is not positive. */
  discount_rate_percent: number | null;
  share_of_menu_net_sales_percent: number | null;
  share_of_menu_units_percent: number | null;

  previous_net_sales_pence: number;
  previous_net_units: number;
  net_sales_change_pence: number;
  net_units_change: number;
  net_sales_percent_change: number | null;
  movement_status: MovementStatus;
  revenue_direction: RevenueDirection;

  /** Highest-lift qualifying partner, or null when none meets the threshold. */
  strongest_attachment: AttachmentEvidenceEntry | null;
}

/** backend/app/schemas/menu.py :: MenuEvidenceResponse */
export interface MenuEvidenceResponse {
  start_date: string;
  end_date: string;
  previous_start_date: string;
  previous_end_date: string;
  kinds: ProductKind[];
  min_pair_orders: number;
  eligible_order_count: number;
  /** Across every matching product, BEFORE `limit`. */
  total_net_sales_pence: number;
  total_net_units: number;
  rows: MenuEvidenceRow[];
}

// --- forecasting (M6) --------------------------------------------------------

/**
 * backend/app/schemas/forecast.py :: ForecastTarget
 *
 * The external measure names. They map onto internal targets whose names carry
 * their unit (`net_sales` -> `net_sales_pence`); the mapping lives in the
 * backend and nothing here needs to know it.
 */
export type ForecastTarget = "net_sales" | "payment_orders" | "net_units";

/**
 * What a `predicted_value` counts, so it is never ambiguous.
 *
 * `pence` follows the same rule as every `*_pence` field above: an INTEGER
 * number of pence, formatted at display time and never divided beforehand.
 */
export type ForecastUnit = "pence" | "orders" | "units";

/** backend/app/schemas/forecast.py :: ForecastPointResponse */
export interface ForecastPoint {
  /** Local calendar day being PREDICTED. Always after `trained_through`. */
  date: string;
  predicted_value: number;
}

/**
 * backend/app/schemas/forecast.py :: ForecastResponse
 *
 * A prediction, not a record. Three fields exist so a consumer cannot present
 * it as one: `method` names what produced it, `trained_through` is the last day
 * of REAL data behind it, and `historical_wape_percent` is the error that
 * method actually made on unseen days.
 *
 * There are deliberately no interval bounds on this shape. The backend returns
 * none — validating an interval's coverage has not been done — so the UI must
 * not synthesise one.
 */
export interface ForecastResponse {
  target: ForecastTarget;
  unit: ForecastUnit;
  /** Machine name, e.g. "ridge_holiday". Render it through `methodLabel`. */
  method: string;
  /** Last day of OBSERVED data. Everything from `forecast_start` is predicted. */
  trained_through: string;
  forecast_start: string;
  forecast_end: string;
  horizon_days: number;
  /** Chronological, one per day, exactly `horizon_days` long. */
  points: ForecastPoint[];
  /**
   * sum|actual - forecast| / sum|actual| over a rolling-origin backtest, as a
   * percentage. Null when the evaluated period contained no trade.
   *
   * MEASURED ERROR, not a confidence level and not a property of the
   * predictions above. Never render it as "100 - x % accurate".
   */
  historical_wape_percent: number | null;
  /** Mean absolute error over the same backtest, in `unit`. */
  historical_mae: number | null;
  /** Independent forecast origins the metrics were pooled over. */
  backtest_folds: number;
  /** Horizon each backtest fold forecast, in days. */
  backtest_horizon_days: number;
}

// --- imports -----------------------------------------------------------------

/** backend/app/models/enums.py :: ImportStatus */
export type ImportStatus = "pending" | "processing" | "completed" | "failed";

/** backend/app/schemas/imports.py :: ReconciliationResult */
export interface ReconciliationResult {
  /**
   * FALSE when no Items Summary was supplied. When false, nothing was checked
   * — `matches` must not be read as a pass, and the UI must not claim a
   * reconciliation happened.
   */
  performed: boolean;
  matches: boolean;
  net_sales_pence_ours: number;
  net_sales_pence_theirs: number;
  line_totals_pence_ours: number;
  line_totals_pence_theirs: number;
  units_ours: number;
  units_theirs: number;
}

/** backend/app/schemas/imports.py :: ImportSummary */
export interface ImportSummary {
  batch_id: number;
  status: ImportStatus;
  label: string | null;
  /** Derived from the FILE CONTENTS — client filenames are never trusted. */
  period_start: string | null;
  period_end: string | null;

  orders_imported: number;
  order_items_imported: number;
  products_created: number;
  products_reused: number;

  rows_skipped: number;
  /** Row-level outcomes keyed by code, e.g. {"zero_value_transaction": 57}. */
  issue_counts: Record<string, number>;

  net_sales_pence: number;
  reconciliation: ReconciliationResult;
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
