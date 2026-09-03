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
