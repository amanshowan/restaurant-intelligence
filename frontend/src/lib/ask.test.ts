import { describe, expect, it } from "vitest";

import type { EvidenceBundle, EvidenceForecast } from "./api";
import {
  EXAMPLE_QUESTIONS,
  comparisonPeriodLabel,
  MAX_QUESTION_LENGTH,
  describeWape,
  distinctWarnings,
  isForecastBundle,
  operationLabel,
  periodLabel,
  productLabel,
  questionProblem,
  recordsLabel,
} from "./ask";

function bundle(overrides: Partial<EvidenceBundle> = {}): EvidenceBundle {
  return {
    operation: "overview",
    status: "ok",
    parameters: {},
    period: { start_date: "2026-08-01", end_date: "2026-08-31", days: 31 },
    comparison_period: null,
    rows: [],
    totals: {},
    field_provenance: {},
    units: {},
    limits: null,
    forecast: null,
    product_resolution: null,
    warnings: [],
    ...overrides,
  };
}

const FORECAST: EvidenceForecast = {
  method: "ridge_holiday",
  trained_through: "2026-08-31",
  forecast_start: "2026-09-01",
  forecast_end: "2026-09-14",
  horizon_days: 14,
  unit: "pence",
  historical_wape_percent: 12.690493,
  historical_mae: 17969.85,
  backtest_folds: 17,
  backtest_horizon_days: 14,
};

describe("operationLabel", () => {
  it("names every operation the backend can return", () => {
    const operations = [
      "overview", "revenue_over_time", "day_of_week", "peak_hours",
      "channel_mix", "product_performance", "product_movers", "product_trend",
      "product_attachments", "basket_pairs", "menu_evidence", "forecast",
    ];
    for (const operation of operations) {
      const label = operationLabel(operation);
      expect(label).not.toBe(operation);
      expect(label).not.toContain("_");
    }
  });

  it("degrades readably rather than throwing on an unknown operation", () => {
    expect(operationLabel("some_new_operation")).toBe("some new operation");
  });
});

describe("forecast evidence", () => {
  it("is identified by the presence of a forecast block", () => {
    expect(isForecastBundle(bundle())).toBe(false);
    expect(isForecastBundle(bundle({ forecast: FORECAST }))).toBe(true);
  });

  it("dates a forecast by the days it predicts, not a measured period", () => {
    const predicted = bundle({ operation: "forecast", period: null, forecast: FORECAST });
    expect(periodLabel(predicted)).toBe("1 Sept 2026 – 14 Sept 2026");
  });

  it("uses the measured period for everything else", () => {
    expect(periodLabel(bundle())).toBe("1 Aug 2026 – 31 Aug 2026");
  });

  it("returns null when there is no period at all", () => {
    expect(periodLabel(bundle({ period: null }))).toBeNull();
  });
});

describe("comparisonPeriodLabel", () => {
  it("formats the comparison period like every other date on the page", () => {
    const compared = bundle({
      comparison_period: {
        start_date: "2026-07-01",
        end_date: "2026-07-31",
        days: 31,
      },
    });
    // Not "2026-07-01 to 2026-07-31": a raw ISO string beside a formatted one
    // reads as a leaked internal.
    expect(comparisonPeriodLabel(compared)).toBe("1 Jul 2026 – 31 Jul 2026");
  });

  it("says nothing when the operation did not compare", () => {
    expect(comparisonPeriodLabel(bundle())).toBeNull();
  });
});

describe("describeWape", () => {
  it("calls WAPE past error and refuses the accuracy reading", () => {
    const described = describeWape(FORECAST) ?? "";

    expect(described).toContain("Typical error 12.7%");
    expect(described).toContain("never seen");
    expect(described).toContain("past error, not a confidence level");
    expect(described).not.toMatch(/accurate|accuracy|87\.3/i);
  });

  it("says nothing when the backend measured no error", () => {
    expect(describeWape({ ...FORECAST, historical_wape_percent: null })).toBeNull();
  });
});

describe("recordsLabel", () => {
  it("reports the count and the total when truncated", () => {
    const limits = {
      returned_rows: 25, applied_limit: 25, maximum_rows: 50,
      available_rows: 140, truncated: true,
    };
    expect(recordsLabel(bundle({ limits }))).toBe("25 records of 140");
  });

  it("reports a plain count when nothing was withheld", () => {
    const limits = {
      returned_rows: 7, applied_limit: null, maximum_rows: 7,
      available_rows: 7, truncated: false,
    };
    expect(recordsLabel(bundle({ limits }))).toBe("7 records");
  });

  it("uses the singular for one record", () => {
    const limits = {
      returned_rows: 1, applied_limit: null, maximum_rows: 50,
      available_rows: 1, truncated: false,
    };
    expect(recordsLabel(bundle({ limits }))).toBe("1 record");
  });

  it("says nothing for an operation whose figures are totals", () => {
    expect(recordsLabel(bundle({ limits: null }))).toBeNull();
  });
});

describe("productLabel", () => {
  it("includes the price point when there is one", () => {
    expect(
      productLabel({ product_id: 4, name: "Caffe Latte", variation: "Large", kind: "menu_item" }),
    ).toBe("Caffe Latte (Large)");
  });

  it("omits an empty variation rather than showing empty brackets", () => {
    expect(
      productLabel({ product_id: 9, name: "Poached Egg", variation: "", kind: "menu_item" }),
    ).toBe("Poached Egg");
  });
});

describe("distinctWarnings", () => {
  it("keeps order and drops repeats", () => {
    const response = {
      warnings: ["Truncated.", "Measured, not judged.", "Truncated."],
    } as Parameters<typeof distinctWarnings>[0];

    expect(distinctWarnings(response)).toEqual([
      "Truncated.",
      "Measured, not judged.",
    ]);
  });
});

describe("questionProblem", () => {
  it("accepts an ordinary question", () => {
    expect(questionProblem("How did we perform last month?")).toBeNull();
  });

  it("rejects an empty or near-empty question", () => {
    expect(questionProblem("   ")).toBe("Type a question first.");
    expect(questionProblem("a")).toBe("Type a question first.");
  });

  it("rejects a question longer than the backend accepts", () => {
    const problem = questionProblem("x".repeat(MAX_QUESTION_LENGTH + 1));
    expect(problem).toContain("1000 characters");
  });

  it("matches the backend's own bound so the limits cannot drift", () => {
    // backend/app/nlq/orchestrator.py :: MAX_QUESTION_LENGTH
    expect(MAX_QUESTION_LENGTH).toBe(1000);
  });
});

describe("example questions", () => {
  it("offers six that span measured analysis and prediction", () => {
    expect(EXAMPLE_QUESTIONS).toHaveLength(6);
    expect(EXAMPLE_QUESTIONS).toContain("How did we perform last month?");
    expect(EXAMPLE_QUESTIONS).toContain("What does the next two weeks look like?");
  });

  it("names a product exactly as the catalogue holds it", () => {
    // The backend resolver refuses to guess: "Big Breakfast" would not match.
    expect(
      EXAMPLE_QUESTIONS.some((q) => q.includes("The Big Breakfast")),
    ).toBe(true);
  });
});
