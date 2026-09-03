/**
 * Presenting a forecast honestly.
 *
 * Everything the Forecast page renders about a prediction — its wording, its
 * units, its error figures — is decided here rather than inside a component,
 * so the rules that matter can be tested without rendering anything.
 *
 * THE RULE THIS FILE EXISTS TO ENFORCE
 * `historical_wape_percent` is a MEASURED ERROR on days the model had never
 * seen. It is not an accuracy, not a confidence, and not a property of the
 * fourteen predictions on screen. "12.69% WAPE" must never become "87.31%
 * accurate": the first is a statement about past errors, the second is a claim
 * about how right these particular numbers are, and the backtest supports only
 * the first. Nothing here computes `100 - wape`, and nothing here invents an
 * interval — the API returns no bounds because their coverage has not been
 * validated, so there are none to render.
 *
 * No metric is recalculated. WAPE, MAE and the fold counts arrive computed by
 * the backtest harness; a second implementation on this side would be a second
 * thing to get wrong.
 */

import type { ForecastResponse, ForecastTarget, ForecastUnit } from "./api";
import {
  NOT_APPLICABLE,
  formatAxisMoney,
  formatCount,
  formatMoneyPence,
  formatShortDate,
} from "./format";

// --- targets -----------------------------------------------------------------

export interface ForecastTargetOption {
  value: ForecastTarget;
  /** Button label. */
  label: string;
  /** Used in headings and axis captions, lower case mid-sentence. */
  measure: string;
}

/**
 * The three measures the endpoint forecasts, in the order the switcher shows
 * them. Money first: it is the figure a manager acts on, and the other two
 * explain it.
 */
export const FORECAST_TARGETS: readonly ForecastTargetOption[] = [
  { value: "net_sales", label: "Net sales", measure: "net sales" },
  { value: "payment_orders", label: "Payment orders", measure: "payment orders" },
  { value: "net_units", label: "Net units", measure: "net units" },
];

export const DEFAULT_TARGET: ForecastTarget = "net_sales";

export function targetOption(target: ForecastTarget): ForecastTargetOption {
  return (
    FORECAST_TARGETS.find((option) => option.value === target) ??
    FORECAST_TARGETS[0]
  );
}

// --- horizon -----------------------------------------------------------------

/** Matches `MAX_HORIZON_DAYS` in backend/app/forecasting/service.py. */
export const MIN_HORIZON_DAYS = 1;
export const MAX_HORIZON_DAYS = 14;
export const DEFAULT_HORIZON_DAYS = 14;

/** Every horizon the control offers: 1..14, and nothing else. */
export const HORIZON_OPTIONS: readonly number[] = Array.from(
  { length: MAX_HORIZON_DAYS - MIN_HORIZON_DAYS + 1 },
  (_, index) => MIN_HORIZON_DAYS + index,
);

export function isValidHorizon(value: number): boolean {
  return (
    Number.isInteger(value) &&
    value >= MIN_HORIZON_DAYS &&
    value <= MAX_HORIZON_DAYS
  );
}

/**
 * A horizon forced into range.
 *
 * The control is a fixed list of the fourteen legal values, so an invalid one
 * is unreachable through the UI by construction. This is the second line: a
 * value arriving from anywhere else is clamped rather than sent to the server
 * to be rejected with a 422 the reader cannot act on.
 */
export function clampHorizon(value: number): number {
  if (!Number.isFinite(value)) return DEFAULT_HORIZON_DAYS;
  const whole = Math.round(value);
  return Math.min(Math.max(whole, MIN_HORIZON_DAYS), MAX_HORIZON_DAYS);
}

/** `1` -> `"1 day"`, `14` -> `"14 days"`. */
export function horizonLabel(days: number): string {
  return days === 1 ? "1 day" : `${days} days`;
}

// --- method ------------------------------------------------------------------

/**
 * Human wording for the backend's method names.
 *
 * Descriptive, not promotional: it says what the model is, so a reader can
 * judge it. An unknown name falls through unchanged rather than being dressed
 * up — a forecast produced by a method this build does not recognise should
 * look unfamiliar.
 */
export const METHOD_LABELS: Record<string, string> = {
  ridge_holiday:
    "Ridge regression on weekday, lag and holiday features",
};

export function methodLabel(method: string): string {
  return METHOD_LABELS[method] ?? method;
}

// --- values ------------------------------------------------------------------

/**
 * A predicted value in its own unit.
 *
 * Money is integer pence right up to this call — the same discipline the
 * backend keeps, and the reason nothing divides by 100 before formatting.
 * Counts are whole things and read as counts, with no currency symbol
 * anywhere near them.
 */
export function formatForecastValue(
  unit: ForecastUnit,
  value: number,
): string {
  return unit === "pence" ? formatMoneyPence(value) : formatCount(value);
}

/** The same value abbreviated for a chart axis tick. */
export function formatForecastAxisValue(
  unit: ForecastUnit,
  value: number,
): string {
  return unit === "pence" ? formatAxisMoney(value) : formatCount(value);
}

// --- chart -------------------------------------------------------------------

export interface ForecastChartPoint {
  /** ISO day being predicted. */
  date: string;
  /** Axis tick label. */
  label: string;
  predictedValue: number;
}

/**
 * The response's points in the order the API returned them.
 *
 * Nothing is filtered. A predicted zero is a prediction, and dropping it would
 * join the line across a day the model expects to be quiet.
 */
export function forecastChartPoints(
  response: ForecastResponse,
): ForecastChartPoint[] {
  return response.points.map((point) => ({
    date: point.date,
    label: formatShortDate(point.date),
    predictedValue: point.predicted_value,
  }));
}

/**
 * The horizon's predicted values added up.
 *
 * A sum of PREDICTIONS, and labelled as one wherever it appears. Useful
 * because ordering and rota decisions are taken over a fortnight rather than a
 * day, but it inherits every error in the points beneath it.
 */
export function forecastTotal(response: ForecastResponse): number {
  return response.points.reduce(
    (total, point) => total + point.predicted_value,
    0,
  );
}

// --- historical error --------------------------------------------------------

/**
 * How many previously unseen days the quoted error was measured over.
 *
 * Each rolling-origin fold forecasts `backtest_horizon_days` days it was not
 * trained on, and the folds are pooled. 17 folds x 14 days = 238 days.
 */
export function evaluatedDayCount(response: ForecastResponse): number {
  return response.backtest_folds * response.backtest_horizon_days;
}

/**
 * WAPE as a percentage string — an ERROR, never inverted into an accuracy.
 *
 * Two decimal places because the margin over the baseline is itself under a
 * point: rounding 12.69% to 13% would erase the difference the model was
 * selected on.
 */
export function formatWapePercent(value: number | null): string {
  if (value === null || !Number.isFinite(value)) return NOT_APPLICABLE;
  return `${value.toFixed(2)}%`;
}

/**
 * MAE in units a reader can act on: pounds per day, orders per day, units
 * per day.
 *
 * Counts keep one decimal. MAE is a mean, so "10 orders" would assert a
 * roundness the figure does not have — and 9.8 and 10.4 are different answers
 * to "how many extra covers should I staff for".
 */
export function formatDailyError(
  unit: ForecastUnit,
  mae: number | null,
): string {
  if (mae === null || !Number.isFinite(mae)) return NOT_APPLICABLE;
  if (unit === "pence") return `${formatMoneyPence(Math.round(mae))} per day`;
  return `${mae.toFixed(1)} ${unit} per day`;
}

/**
 * The sentence that keeps the WAPE figure honest.
 *
 * Says what was measured, on how many days, and how those days were held out.
 * Without it a bare percentage invites the reader to supply their own meaning,
 * and the meaning most readers supply is "confidence".
 */
export function historicalErrorContext(response: ForecastResponse): string {
  const days = evaluatedDayCount(response);
  if (days <= 0) return "No completed backtest folds are available.";
  return (
    `Across ${formatCount(days)} previously unseen forecast days, pooled from ` +
    `${formatCount(response.backtest_folds)} rolling-origin backtest ` +
    `${response.backtest_folds === 1 ? "fold" : "folds"} of ` +
    `${horizonLabel(response.backtest_horizon_days)} each.`
  );
}
