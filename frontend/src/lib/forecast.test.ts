import { describe, expect, it } from "vitest";

import type { ForecastResponse } from "./api";
import {
  DEFAULT_HORIZON_DAYS,
  FORECAST_TARGETS,
  HORIZON_OPTIONS,
  MAX_HORIZON_DAYS,
  MIN_HORIZON_DAYS,
  clampHorizon,
  evaluatedDayCount,
  forecastChartPoints,
  forecastTotal,
  formatDailyError,
  formatForecastAxisValue,
  formatForecastValue,
  formatWapePercent,
  historicalErrorContext,
  horizonLabel,
  isValidHorizon,
  methodLabel,
  targetOption,
} from "./forecast";

/**
 * A response shaped exactly as `GET /analytics/forecast` returns one.
 *
 * The numbers are INVENTED, and deliberately so. Every assertion below is
 * about a presentation rule — that 123456 pence renders as £1,234.56, that a
 * WAPE is never inverted — and none of them is about what the model predicts.
 * Pinning today's live forecast into a test would make retraining, or simply
 * importing another month, fail a suite that has nothing to do with either.
 */
function forecastPayload(
  overrides: Partial<ForecastResponse> = {},
): ForecastResponse {
  return {
    target: "net_sales",
    unit: "pence",
    method: "ridge_holiday",
    trained_through: "2026-08-31",
    forecast_start: "2026-09-01",
    forecast_end: "2026-09-03",
    horizon_days: 3,
    points: [
      { date: "2026-09-01", predicted_value: 123456 },
      { date: "2026-09-02", predicted_value: 140000 },
      { date: "2026-09-03", predicted_value: 98765 },
    ],
    historical_wape_percent: 12.345678,
    historical_mae: 20000.4,
    backtest_folds: 17,
    backtest_horizon_days: 14,
    ...overrides,
  };
}

describe("horizon", () => {
  it("offers every legal horizon and nothing else", () => {
    expect(HORIZON_OPTIONS).toHaveLength(MAX_HORIZON_DAYS);
    expect(HORIZON_OPTIONS[0]).toBe(MIN_HORIZON_DAYS);
    expect(HORIZON_OPTIONS.at(-1)).toBe(MAX_HORIZON_DAYS);
    expect(HORIZON_OPTIONS.every(isValidHorizon)).toBe(true);
  });

  it("matches the backend's own bound", () => {
    // backend/app/forecasting/service.py :: MAX_HORIZON_DAYS
    expect(MAX_HORIZON_DAYS).toBe(14);
    expect(DEFAULT_HORIZON_DAYS).toBe(14);
  });

  it("rejects horizons the API would answer with a 422", () => {
    expect(isValidHorizon(0)).toBe(false);
    expect(isValidHorizon(15)).toBe(false);
    expect(isValidHorizon(-3)).toBe(false);
    expect(isValidHorizon(7.5)).toBe(false);
  });

  it("clamps anything out of range rather than sending it", () => {
    expect(clampHorizon(0)).toBe(1);
    expect(clampHorizon(-3)).toBe(1);
    expect(clampHorizon(15)).toBe(14);
    expect(clampHorizon(99)).toBe(14);
    expect(clampHorizon(7.4)).toBe(7);
    expect(clampHorizon(Number.NaN)).toBe(DEFAULT_HORIZON_DAYS);
  });

  it("labels one day in the singular", () => {
    expect(horizonLabel(1)).toBe("1 day");
    expect(horizonLabel(14)).toBe("14 days");
  });
});

describe("targets", () => {
  it("covers exactly the three the endpoint accepts", () => {
    expect(FORECAST_TARGETS.map((option) => option.value)).toEqual([
      "net_sales",
      "payment_orders",
      "net_units",
    ]);
  });

  it("resolves each target to its own wording", () => {
    expect(targetOption("net_sales").measure).toBe("net sales");
    expect(targetOption("payment_orders").measure).toBe("payment orders");
    expect(targetOption("net_units").measure).toBe("net units");
  });
});

describe("value formatting", () => {
  it("renders money from integer pence, as GBP, only at display time", () => {
    expect(formatForecastValue("pence", 123456)).toBe("£1,234.56");
    expect(formatForecastValue("pence", 100)).toBe("£1.00");
    expect(formatForecastValue("pence", 0)).toBe("£0.00");
  });

  it("keeps a negative predicted day signed outside the symbol", () => {
    // Net sales is not floored: a day whose refunds outweigh its sales
    // genuinely takes less than nothing, and the model may predict one.
    expect(formatForecastValue("pence", -4250)).toBe("-£42.50");
  });

  it("renders counts as counts, with no currency anywhere near them", () => {
    expect(formatForecastValue("orders", 77)).toBe("77");
    expect(formatForecastValue("units", 1252)).toBe("1,252");
    expect(formatForecastValue("orders", 1000)).not.toContain("£");
    expect(formatForecastValue("units", 1000)).not.toContain("£");
  });

  it("abbreviates money on an axis but never a count", () => {
    expect(formatForecastAxisValue("pence", 123456)).toBe("£1.2k");
    expect(formatForecastAxisValue("orders", 1250)).toBe("1,250");
  });
});

describe("chart points", () => {
  it("keeps every predicted day, in the order the API returned them", () => {
    const points = forecastChartPoints(forecastPayload());

    expect(points.map((point) => point.date)).toEqual([
      "2026-09-01",
      "2026-09-02",
      "2026-09-03",
    ]);
    expect(points[0].predictedValue).toBe(123456);
  });

  it("keeps a predicted zero rather than dropping it", () => {
    const points = forecastChartPoints(
      forecastPayload({
        points: [
          { date: "2026-12-25", predicted_value: 0 },
          { date: "2026-12-26", predicted_value: 41200 },
        ],
      }),
    );

    expect(points).toHaveLength(2);
    expect(points[0].predictedValue).toBe(0);
  });

  it("totals the horizon in the target's own unit", () => {
    expect(forecastTotal(forecastPayload())).toBe(123456 + 140000 + 98765);
  });
});

describe("historical error", () => {
  it("reports WAPE as an error percentage, never inverted into an accuracy", () => {
    const data = forecastPayload();

    expect(formatWapePercent(data.historical_wape_percent)).toBe("12.35%");
    // The inverse would be "87.65%". Nothing in this module produces it, and
    // nothing in this module subtracts a WAPE from 100 at all.
    expect(formatWapePercent(data.historical_wape_percent)).not.toBe("87.65%");
  });

  it("keeps two decimals, because the margin over the baseline is under a point", () => {
    // The model was selected on a margin of roughly half a percentage point
    // over its baseline; rounding to whole percent would erase it.
    expect(formatWapePercent(13.2249)).toBe("13.22%");
    expect(formatWapePercent(12.6905)).toBe("12.69%");
  });

  it("renders an undefined WAPE as an em dash rather than zero error", () => {
    expect(formatWapePercent(null)).toBe("—");
  });

  it("translates MAE into pounds per day for money", () => {
    expect(formatDailyError("pence", 20000.4)).toBe("£200.00 per day");
    // MAE is a float. Rounded to whole pence before formatting, and never
    // divided by 100 beforehand.
    expect(formatDailyError("pence", 12345.678901234)).toBe(
      "£123.46 per day",
    );
  });

  it("translates MAE into counts per day, keeping a decimal", () => {
    // A mean is not a whole number of orders, and "10" would assert a
    // roundness it does not have.
    expect(formatDailyError("orders", 9.751119)).toBe("9.8 orders per day");
    expect(formatDailyError("units", 44.449999)).toBe("44.4 units per day");
  });

  it("renders an undefined MAE as an em dash", () => {
    expect(formatDailyError("pence", null)).toBe("—");
  });

  it("counts the unseen days the metrics were pooled over", () => {
    expect(evaluatedDayCount(forecastPayload())).toBe(238);
  });

  it("states how many unseen days the error came from", () => {
    const context = historicalErrorContext(forecastPayload());

    expect(context).toContain("238 previously unseen forecast days");
    expect(context).toContain("17 rolling-origin backtest folds");
    expect(context).toContain("14 days each");
  });

  it("says so plainly when no fold completed", () => {
    expect(
      historicalErrorContext(forecastPayload({ backtest_folds: 0 })),
    ).toBe("No completed backtest folds are available.");
  });
});

describe("method naming", () => {
  it("expands the production method into something a reader can judge", () => {
    expect(methodLabel("ridge_holiday")).toBe(
      "Ridge regression on weekday, lag and holiday features",
    );
  });

  it("leaves an unrecognised method looking unfamiliar", () => {
    expect(methodLabel("some_future_model")).toBe("some_future_model");
  });
});
