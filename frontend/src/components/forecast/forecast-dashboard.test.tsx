// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { ForecastResponse, ForecastTarget, ForecastUnit } from "@/lib/api";

import { ForecastDashboard } from "./forecast-dashboard";

/**
 * What the Forecast page must never do is a property of the RENDERED page, not
 * of any one function: a prediction presented as a record, or a measured error
 * presented as an accuracy or a confidence. Those claims are made in JSX, so
 * they are tested against a DOM.
 *
 * The chart is mocked out. Recharts needs a laid-out container and a
 * ResizeObserver, neither of which jsdom has, and what it draws is decided by
 * `forecastChartPoints` — which is tested directly in lib/forecast.test.ts.
 * What is under test here is the page's states, its controls and its wording.
 *
 * NO FIGURE HERE COMES FROM THE LIVE DATABASE. The stub generates a response
 * from the query it was given, out of invented constants, so every assertion
 * checks that the page renders what the API SAID — never that the API says
 * anything in particular. Retraining the model, or importing another month,
 * must not be able to fail this file.
 */
vi.mock("./forecast-chart", () => ({
  ForecastChart: ({ points }: { points: unknown[] }) => (
    <div data-testid="forecast-chart">{points.length} points</div>
  ),
}));

const UNITS: Record<ForecastTarget, ForecastUnit> = {
  net_sales: "pence",
  payment_orders: "orders",
  net_units: "units",
};

/** Invented per-target day-one values; each later day adds one. */
const DAILY: Record<ForecastTarget, number> = {
  net_sales: 123456,
  payment_orders: 77,
  net_units: 321,
};

/** Invented error figures, distinct per target so a mix-up is visible. */
const WAPE: Record<ForecastTarget, number> = {
  net_sales: 12.345678,
  payment_orders: 9.876543,
  net_units: 11.111944,
};

const MAE: Record<ForecastTarget, number> = {
  net_sales: 20000.4,
  payment_orders: 8.25,
  net_units: 40.06,
};

/** `2026-09-01` plus `offset` days, without leaving September. */
function septemberDay(offset: number): string {
  return `2026-09-${String(1 + offset).padStart(2, "0")}`;
}

function payloadFor(url: string): ForecastResponse {
  const query = new URLSearchParams(url.split("?")[1] ?? "");
  const target = (query.get("target") ?? "net_sales") as ForecastTarget;
  const horizon = Number(query.get("horizon_days") ?? "14");

  return {
    target,
    unit: UNITS[target],
    method: "ridge_holiday",
    trained_through: "2026-08-31",
    forecast_start: septemberDay(0),
    forecast_end: septemberDay(horizon - 1),
    horizon_days: horizon,
    points: Array.from({ length: horizon }, (_, index) => ({
      date: septemberDay(index),
      predicted_value: DAILY[target] + index,
    })),
    historical_wape_percent: WAPE[target],
    historical_mae: MAE[target],
    backtest_folds: 17,
    backtest_horizon_days: 14,
  };
}

/** Resolves every forecast request from the query it carries. */
function stubForecastFetch() {
  const spy = vi.fn((input: RequestInfo | URL) =>
    Promise.resolve(
      new Response(JSON.stringify(payloadFor(String(input))), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    ),
  );
  vi.stubGlobal("fetch", spy);
  return spy;
}

function stubErrorFetch(body: unknown, status: number) {
  const spy = vi.fn(() =>
    Promise.resolve(
      new Response(JSON.stringify(body), {
        status,
        headers: { "Content-Type": "application/json" },
      }),
    ),
  );
  vi.stubGlobal("fetch", spy);
  return spy;
}

/** The request URLs a spy was called with, newest last. */
function urls(spy: ReturnType<typeof stubForecastFetch>): string[] {
  return spy.mock.calls.map((call) => String(call[0]));
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("initial load", () => {
  it("says these are predictions before any data has arrived", () => {
    stubForecastFetch();

    render(<ForecastDashboard />);

    expect(
      screen.getByText(/these are predictions, not recorded trade/i),
    ).toBeTruthy();
  });

  it("asks for the default 14-day net sales forecast, once", async () => {
    const spy = stubForecastFetch();

    render(<ForecastDashboard />);

    await screen.findByTestId("forecast-chart");
    expect(urls(spy)).toEqual([
      "/api/analytics/forecast?target=net_sales&horizon_days=14",
    ]);
  });
});

describe("a successful 14-day forecast", () => {
  it("renders the trained-through day, the forecast period and every day", async () => {
    stubForecastFetch();

    render(<ForecastDashboard />);
    await screen.findByTestId("forecast-chart");

    expect(screen.getByText("31 Aug 2026")).toBeTruthy();
    expect(screen.getByText("1 Sept 2026 – 14 Sept 2026")).toBeTruthy();
    expect(screen.getByTestId("forecast-chart").textContent).toBe("14 points");

    const table = screen.getByRole("table");
    // One row per predicted day, plus the header row.
    expect(within(table).getAllByRole("row")).toHaveLength(15);
    expect(within(table).getByText("Tue, 1 Sept 2026")).toBeTruthy();
    expect(within(table).getByText("Mon, 14 Sept 2026")).toBeTruthy();
  });

  it("formats revenue as GBP from integer pence", async () => {
    stubForecastFetch();

    render(<ForecastDashboard />);
    await screen.findByTestId("forecast-chart");

    const table = screen.getByRole("table");
    // 123456 pence on the first day, +1 per subsequent day.
    expect(within(table).getByText("£1,234.56")).toBeTruthy();
    expect(within(table).getByText("£1,234.69")).toBeTruthy();
  });

  it("names the method in words rather than leaving it as a code", async () => {
    stubForecastFetch();

    render(<ForecastDashboard />);
    await screen.findByTestId("forecast-chart");

    expect(
      screen.getByText("Ridge regression on weekday, lag and holiday features"),
    ).toBeTruthy();
  });
});

describe("historical error", () => {
  it("shows WAPE as an error with the unseen days behind it", async () => {
    stubForecastFetch();

    render(<ForecastDashboard />);
    await screen.findByTestId("forecast-chart");

    expect(screen.getByText("Historical WAPE")).toBeTruthy();
    expect(screen.getByText("12.35%")).toBeTruthy();
    expect(
      screen.getByText(/238 previously unseen forecast days/),
    ).toBeTruthy();
    expect(
      screen.getByText(/17 rolling-origin backtest folds of 14 days each/),
    ).toBeTruthy();
  });

  it("translates MAE into money per day", async () => {
    stubForecastFetch();

    render(<ForecastDashboard />);
    await screen.findByTestId("forecast-chart");

    expect(screen.getByText("£200.00 per day")).toBeTruthy();
  });

  it("never presents the error as an accuracy or a confidence", async () => {
    stubForecastFetch();

    const { container } = render(<ForecastDashboard />);
    await screen.findByTestId("forecast-chart");

    const text = container.textContent ?? "";
    // The inverse of the stubbed 12.35% WAPE. It must appear nowhere.
    expect(text).not.toContain("87.65");
    expect(text).not.toContain("87%");
    // The page does not use the vocabulary of accuracy AT ALL, so there is no
    // wording for a reader to misread as one.
    expect(text).not.toMatch(/accurate|accuracy/i);
    expect(text).not.toMatch(/\d+(\.\d+)?\s*%?\s*confiden/i);
    expect(text).not.toMatch(/confidence (interval|band)/i);
    // ...and it says what the figures ARE instead.
    expect(text).toMatch(/error measures, not confidence levels/i);
    expect(text).toMatch(/no prediction intervals are shown/i);
  });
});

describe("switching target", () => {
  it("issues exactly one new request and renders counts, not currency", async () => {
    const spy = stubForecastFetch();

    render(<ForecastDashboard />);
    await screen.findByTestId("forecast-chart");

    fireEvent.click(screen.getByRole("button", { name: "Payment orders" }));

    await waitFor(() =>
      expect(urls(spy)).toEqual([
        "/api/analytics/forecast?target=net_sales&horizon_days=14",
        "/api/analytics/forecast?target=payment_orders&horizon_days=14",
      ]),
    );

    await waitFor(() => {
      const table = screen.getByRole("table");
      expect(within(table).getByText("77")).toBeTruthy();
      expect(table.textContent ?? "").not.toContain("£");
    });
  });

  it("carries the new measure into the error figures too", async () => {
    stubForecastFetch();

    render(<ForecastDashboard />);
    await screen.findByTestId("forecast-chart");

    fireEvent.click(screen.getByRole("button", { name: "Net units" }));

    await waitFor(() => {
      expect(screen.getByText("11.11%")).toBeTruthy();
      expect(screen.getByText("40.1 units per day")).toBeTruthy();
    });
  });

  it("keeps the previous measure's labels while the new one is loading", async () => {
    // The first request resolves; the second never does, leaving the page in
    // exactly the state it holds mid-switch. The hook keeps the last good
    // response on screen, so the labels must keep describing THAT response —
    // relabelling order counts "net sales" would be a confident lie.
    let served = false;
    vi.stubGlobal(
      "fetch",
      vi.fn((input: RequestInfo | URL) => {
        if (served) return new Promise<Response>(() => {});
        served = true;
        return Promise.resolve(
          new Response(JSON.stringify(payloadFor(String(input))), {
            status: 200,
            headers: { "Content-Type": "application/json" },
          }),
        );
      }),
    );

    render(<ForecastDashboard />);
    await screen.findByTestId("forecast-chart");

    fireEvent.click(screen.getByRole("button", { name: "Payment orders" }));

    // The control has moved...
    await waitFor(() =>
      expect(
        screen
          .getByRole("button", { name: "Payment orders" })
          .getAttribute("aria-pressed"),
      ).toBe("true"),
    );

    // ...but what is on screen is still the net sales response, and still
    // says so, in money.
    expect(screen.getByText("Predicted daily net sales")).toBeTruthy();
    const table = screen.getByRole("table");
    expect(within(table).getByText("£1,234.56")).toBeTruthy();
    expect(table.textContent ?? "").not.toMatch(/predicted payment orders/i);
  });

  it("marks the selected measure for assistive technology", async () => {
    stubForecastFetch();

    render(<ForecastDashboard />);
    await screen.findByTestId("forecast-chart");

    const netSales = screen.getByRole("button", { name: "Net sales" });
    const netUnits = screen.getByRole("button", { name: "Net units" });
    expect(netSales.getAttribute("aria-pressed")).toBe("true");
    expect(netUnits.getAttribute("aria-pressed")).toBe("false");

    fireEvent.click(netUnits);

    await waitFor(() =>
      expect(netUnits.getAttribute("aria-pressed")).toBe("true"),
    );
  });
});

describe("switching horizon", () => {
  it("offers 1 to 14 days and nothing outside that", () => {
    stubForecastFetch();

    render(<ForecastDashboard />);

    const select = screen.getByLabelText("Horizon") as HTMLSelectElement;
    const values = Array.from(select.options).map((option) => option.value);

    expect(values).toEqual(
      Array.from({ length: 14 }, (_, index) => String(index + 1)),
    );
    expect(select.options[0].textContent).toBe("1 day");
    expect(select.options[13].textContent).toBe("14 days");
  });

  it("re-requests a one-day horizon and renders a single day", async () => {
    const spy = stubForecastFetch();

    render(<ForecastDashboard />);
    await screen.findByTestId("forecast-chart");

    fireEvent.change(screen.getByLabelText("Horizon"), {
      target: { value: "1" },
    });

    await waitFor(() =>
      expect(urls(spy)).toEqual([
        "/api/analytics/forecast?target=net_sales&horizon_days=14",
        "/api/analytics/forecast?target=net_sales&horizon_days=1",
      ]),
    );

    await waitFor(() => {
      expect(screen.getByTestId("forecast-chart").textContent).toBe("1 points");
      expect(within(screen.getByRole("table")).getAllByRole("row")).toHaveLength(
        2,
      );
      expect(screen.getByText("1 Sept 2026")).toBeTruthy();
    });
  });

  it("returns to a 14-day horizon without a further request per day", async () => {
    const spy = stubForecastFetch();

    render(<ForecastDashboard />);
    await screen.findByTestId("forecast-chart");

    fireEvent.change(screen.getByLabelText("Horizon"), {
      target: { value: "7" },
    });
    await waitFor(() => expect(spy).toHaveBeenCalledTimes(2));

    fireEvent.change(screen.getByLabelText("Horizon"), {
      target: { value: "14" },
    });
    await waitFor(() => expect(spy).toHaveBeenCalledTimes(3));

    // Three control changes, three requests. Never one per forecast point.
    expect(urls(spy)).toEqual([
      "/api/analytics/forecast?target=net_sales&horizon_days=14",
      "/api/analytics/forecast?target=net_sales&horizon_days=7",
      "/api/analytics/forecast?target=net_sales&horizon_days=14",
    ]);
  });
});

describe("failure states", () => {
  it("says the API is unreachable rather than blaming the request", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(() => Promise.reject(new TypeError("fetch failed"))),
    );

    render(<ForecastDashboard />);

    expect(await screen.findByText(/cannot reach the api/i)).toBeTruthy();
    // Still no forecast presented as fact.
    expect(screen.queryByTestId("forecast-chart")).toBeNull();
  });

  it("explains too little history on its own terms, not as a rejected request", async () => {
    stubErrorFetch(
      {
        detail:
          "42 day(s) of history is not enough to forecast; at least 134 are required",
        code: "insufficient_history",
      },
      422,
    );

    render(<ForecastDashboard />);

    expect(
      await screen.findByText("Not enough history to forecast"),
    ).toBeTruthy();
    expect(
      screen.getByText(/at least 134 are required/),
    ).toBeTruthy();
    expect(screen.queryByText(/the api rejected this request/i)).toBeNull();
  });

  it("surfaces any other rejection through the shared error panel", async () => {
    stubErrorFetch(
      { detail: "target is not one of the accepted values", code: "validation_error" },
      422,
    );

    render(<ForecastDashboard />);

    expect(
      await screen.findByText(/the api rejected this request/i),
    ).toBeTruthy();
    expect(screen.getByText("validation_error · HTTP 422")).toBeTruthy();
  });
});
