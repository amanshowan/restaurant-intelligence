/**
 * Turning one `/analytics/ask` response into things a café owner can read.
 *
 * Everything here is pure and presentational. No decision about what the AI
 * may claim is made in this file — that is settled in the backend, where the
 * model's entire factual input is controlled. What these functions do is make
 * the resulting evidence legible: name the operations in English, summarise a
 * bundle without dumping its internals, and keep the line between a measured
 * fact and a prediction visible in the UI as well as in the prose.
 */

import type {
  AskResponse,
  EvidenceBundle,
  EvidenceForecast,
  ResolvedProduct,
} from "./api";
import { formatDateRangeLabel, formatIsoDate } from "./format";

/**
 * The starter questions on the page.
 *
 * Chosen to span the analytics surface rather than to flatter it: a period
 * comparison, a timing pattern, a product movement, a basket association, a
 * channel split and a forecast. Between them they exercise six of the twelve
 * operations and both answer shapes — measured and predicted.
 */
export const EXAMPLE_QUESTIONS: readonly string[] = [
  "How did we perform last month?",
  "What are our busiest days?",
  "Which products are declining?",
  "What tends to be ordered with The Big Breakfast?",
  "How is delivery performing?",
  "What does the next two weeks look like?",
];

/** Matches the backend's own bound, so an over-long question fails locally. */
export const MAX_QUESTION_LENGTH = 1000;
export const MIN_QUESTION_LENGTH = 3;

/**
 * Operation codes as a person would say them.
 *
 * The backend's codes are precise and unlovely — `product_attachments`,
 * `menu_evidence`. Showing them raw would be showing internals; hiding them
 * entirely would remove the one thing that makes an answer checkable. So they
 * are translated, and the code is kept available for anyone who wants it.
 */
const OPERATION_LABELS: Record<string, string> = {
  overview: "Headline figures",
  revenue_over_time: "Revenue over time",
  day_of_week: "Trade by weekday",
  peak_hours: "Busiest hours",
  channel_mix: "Channel mix",
  product_performance: "Product ranking",
  product_movers: "Product movement",
  product_trend: "One product over time",
  product_attachments: "Bought alongside",
  basket_pairs: "Products bought together",
  menu_evidence: "Menu evidence",
  forecast: "Forecast",
};

export function operationLabel(operation: string): string {
  return OPERATION_LABELS[operation] ?? operation.replace(/_/g, " ");
}

/** True when this bundle is prediction rather than record. */
export function isForecastBundle(bundle: EvidenceBundle): boolean {
  return bundle.forecast !== null;
}

/**
 * The period a bundle covers, in words.
 *
 * A forecast has no measured period — it measured nothing — so its dates come
 * from the forecast block instead, and are labelled as the days being
 * predicted rather than the days observed.
 */
export function periodLabel(bundle: EvidenceBundle): string | null {
  if (bundle.forecast) {
    return formatDateRangeLabel(
      bundle.forecast.forecast_start,
      bundle.forecast.forecast_end,
    );
  }
  if (!bundle.period) return null;
  return formatDateRangeLabel(bundle.period.start_date, bundle.period.end_date);
}

/**
 * The comparable previous period a bundle measured itself against, in words.
 *
 * Formatted like every other date on the page. An earlier version rendered the
 * raw ISO strings, which sat beside a formatted period and read as a leaked
 * internal.
 */
export function comparisonPeriodLabel(bundle: EvidenceBundle): string | null {
  if (!bundle.comparison_period) return null;
  return formatDateRangeLabel(
    bundle.comparison_period.start_date,
    bundle.comparison_period.end_date,
  );
}

/**
 * How much data stood behind a bundle, and whether it was the whole set.
 *
 * Null when there is nothing worth saying — an operation whose figures are
 * totals rather than rows has no row count a reader benefits from.
 */
export function recordsLabel(bundle: EvidenceBundle): string | null {
  const limits = bundle.limits;
  if (!limits || limits.returned_rows === 0) return null;

  const rows = `${limits.returned_rows} ${limits.returned_rows === 1 ? "record" : "records"}`;
  if (limits.truncated && limits.available_rows !== null) {
    return `${rows} of ${limits.available_rows}`;
  }
  return rows;
}

/**
 * WAPE, stated as what it is.
 *
 * The one sentence in this file that exists to prevent a specific wrong
 * reading. A WAPE of 12.7% is not "87.3% accurate", and the difference is not
 * pedantry: one is a measurement of past error, the other is a promise about
 * these particular numbers that nothing in the system supports.
 */
export function describeWape(forecast: EvidenceForecast): string | null {
  if (forecast.historical_wape_percent === null) return null;
  return (
    `Typical error ${forecast.historical_wape_percent.toFixed(1)}% on days ` +
    `the model had never seen, measured over ${forecast.backtest_folds} ` +
    `backtests. That is past error, not a confidence level for these figures.`
  );
}

/** "Caffe Latte (Large)", or just the name when there is no price point. */
export function productLabel(product: ResolvedProduct): string {
  return product.variation ? `${product.name} (${product.variation})` : product.name;
}

/**
 * The forecast's honesty line: the last day anything was actually recorded.
 */
export function trainedThroughLabel(forecast: EvidenceForecast): string {
  return formatIsoDate(forecast.trained_through);
}

/**
 * Every distinct limitation across the response, in order, without repeats.
 *
 * The backend attaches warnings per bundle, and a two-operation answer often
 * repeats the same caveat. Showing it twice reads as noise and trains a reader
 * to skip the box that matters.
 */
export function distinctWarnings(response: AskResponse): string[] {
  const seen = new Set<string>();
  const ordered: string[] = [];
  for (const warning of response.warnings) {
    if (seen.has(warning)) continue;
    seen.add(warning);
    ordered.push(warning);
  }
  return ordered;
}

/** Whether the question produced anything worth showing evidence for. */
export function hasEvidence(response: AskResponse): boolean {
  return response.evidence.length > 0;
}

/** Local pre-flight, so an obviously unusable question costs nothing. */
export function questionProblem(question: string): string | null {
  const trimmed = question.trim();
  if (trimmed.length < MIN_QUESTION_LENGTH) {
    return "Type a question first.";
  }
  if (trimmed.length > MAX_QUESTION_LENGTH) {
    return `Questions are limited to ${MAX_QUESTION_LENGTH} characters; this one is ${trimmed.length}.`;
  }
  return null;
}
