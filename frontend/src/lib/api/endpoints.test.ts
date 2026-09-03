import { afterEach, describe, expect, it, vi } from "vitest";

import {
  getChannels,
  getDayOfWeek,
  getOverview,
  getPeakHours,
  getReadiness,
  getRevenue,
} from "./endpoints";
import type { OverviewResponse } from "./types";

const AUGUST = { startDate: "2026-08-01", endDate: "2026-08-31" };

/** A complete overview payload, shaped exactly as the API returns one. */
function overviewPayload(
  overrides: Partial<OverviewResponse> = {},
): OverviewResponse {
  return {
    start_date: "2026-08-01",
    end_date: "2026-08-31",
    net_sales_pence: 1234567,
    gross_sales_pence: 1300000,
    discounts_pence: 65433,
    payment_order_count: 812,
    refund_event_count: 3,
    net_units: 2044,
    average_order_value_pence: 1520,
    ...overrides,
  };
}

function stubFetch(body: unknown, status = 200) {
  const spy = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
    void input;
    void init;
    return Promise.resolve(
      new Response(JSON.stringify(body), {
        status,
        headers: { "Content-Type": "application/json" },
      }),
    );
  });
  vi.stubGlobal("fetch", spy);
  return spy;
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("getOverview", () => {
  it("requests the range as inclusive local dates through the same-origin proxy", async () => {
    const spy = stubFetch(overviewPayload());

    await getOverview({ startDate: "2026-08-01", endDate: "2026-08-31" });

    expect(spy.mock.calls[0][0]).toBe(
      "/api/analytics/overview?start_date=2026-08-01&end_date=2026-08-31",
    );
  });

  it("returns every field the page renders", async () => {
    stubFetch(overviewPayload());

    const data = await getOverview({
      startDate: "2026-08-01",
      endDate: "2026-08-31",
    });

    // The six figures the Overview page displays, plus the two it reads for
    // context. A field silently dropped from the response would surface here.
    expect(data.net_sales_pence).toBe(1234567);
    expect(data.gross_sales_pence).toBe(1300000);
    expect(data.discounts_pence).toBe(65433);
    expect(data.payment_order_count).toBe(812);
    expect(data.net_units).toBe(2044);
    expect(data.average_order_value_pence).toBe(1520);
    expect(data.refund_event_count).toBe(3);
    expect(data.start_date).toBe("2026-08-01");
  });

  it("passes a zero period through as real data, not as an error", async () => {
    // A month with no trade is a legitimate answer. It must not be conflated
    // with a failed request.
    stubFetch(
      overviewPayload({
        net_sales_pence: 0,
        gross_sales_pence: 0,
        discounts_pence: 0,
        payment_order_count: 0,
        refund_event_count: 0,
        net_units: 0,
        average_order_value_pence: 0,
      }),
    );

    const data = await getOverview({
      startDate: "2026-09-01",
      endDate: "2026-09-30",
    });

    expect(data.payment_order_count).toBe(0);
    expect(data.net_sales_pence).toBe(0);
  });

  it("surfaces a rejected range as the backend's own error code", async () => {
    stubFetch(
      {
        detail: "end_date (2026-08-01) must not be before start_date (2026-08-31)",
        code: "invalid_date_range",
      },
      400,
    );

    await expect(
      getOverview({ startDate: "2026-08-31", endDate: "2026-08-01" }),
    ).rejects.toMatchObject({ code: "invalid_date_range", status: 400 });
  });
});

describe("getReadiness", () => {
  it("reports a database that cannot be reached as an ApiError", async () => {
    // /health/ready answers 503 in the same envelope as every other failure.
    stubFetch({ detail: "database unreachable", code: "not_ready" }, 503);

    await expect(getReadiness()).rejects.toMatchObject({
      code: "not_ready",
      status: 503,
    });
  });
});


describe("trading endpoints", () => {
  it("sends granularity as a request parameter, not something derived client-side", async () => {
    // Weekly buckets are Monday-based and computed in the database. Asking the
    // API for them keeps that rule in one place; re-bucketing daily data here
    // would be a second implementation of it.
    const spy = stubFetch({ start_date: "", end_date: "", granularity: "week", buckets: [] });

    await getRevenue(AUGUST, "week");

    expect(spy.mock.calls[0][0]).toBe(
      "/api/analytics/revenue?start_date=2026-08-01&end_date=2026-08-31&granularity=week",
    );
  });

  it("requests daily granularity explicitly", async () => {
    const spy = stubFetch({ start_date: "", end_date: "", granularity: "day", buckets: [] });
    await getRevenue(AUGUST, "day");
    expect(spy.mock.calls[0][0]).toContain("granularity=day");
  });

  it("builds the day-of-week, peak-hours and channel URLs from the same range", async () => {
    for (const [call, path] of [
      [() => getDayOfWeek(AUGUST), "/api/analytics/day-of-week"],
      [() => getPeakHours(AUGUST), "/api/analytics/peak-hours"],
      [() => getChannels(AUGUST), "/api/analytics/channels"],
    ] as const) {
      const spy = stubFetch({});
      await call();
      expect(spy.mock.calls[0][0]).toBe(
        `${path}?start_date=2026-08-01&end_date=2026-08-31`,
      );
      vi.unstubAllGlobals();
    }
  });

  it("parses a revenue series including its zero buckets", async () => {
    stubFetch({
      start_date: "2026-08-01",
      end_date: "2026-08-31",
      granularity: "day",
      buckets: [
        {
          period_start: "2026-08-01",
          net_sales_pence: 171960,
          gross_sales_pence: 174341,
          discounts_pence: 2381,
          payment_order_count: 105,
          net_units: 326,
        },
        {
          period_start: "2026-08-02",
          net_sales_pence: 0,
          gross_sales_pence: 0,
          discounts_pence: 0,
          payment_order_count: 0,
          net_units: 0,
        },
      ],
    });

    const data = await getRevenue(AUGUST, "day");

    expect(data.buckets).toHaveLength(2);
    expect(data.buckets[1].payment_order_count).toBe(0);
    expect(data.granularity).toBe("day");
  });

  it("parses a channel mix with a null share", async () => {
    stubFetch({
      start_date: "2026-08-01",
      end_date: "2026-08-31",
      channels: [
        {
          channel: "unknown",
          net_sales_pence: 0,
          payment_order_count: 0,
          net_units: 0,
          average_order_value_pence: 0,
          share_of_payment_orders_percent: null,
          share_of_net_sales_percent: null,
        },
      ],
    });

    const data = await getChannels(AUGUST);

    // Null must survive the round trip: it means undefined, not zero.
    expect(data.channels[0].share_of_net_sales_percent).toBeNull();
    expect(data.channels[0].share_of_payment_orders_percent).toBeNull();
  });

  it("parses a completely empty analytics period without inventing values", async () => {
    stubFetch({
      start_date: "2026-09-01",
      end_date: "2026-09-30",
      cells: [],
      peak_payment_order_count: 0,
      busiest: [],
    });

    const data = await getPeakHours({
      startDate: "2026-09-01",
      endDate: "2026-09-30",
    });

    expect(data.cells).toEqual([]);
    expect(data.peak_payment_order_count).toBe(0);
    expect(data.busiest).toEqual([]);
  });

  it("surfaces a rejected range from a trading endpoint too", async () => {
    stubFetch(
      { detail: "range too long", code: "invalid_date_range" },
      400,
    );
    await expect(getDayOfWeek(AUGUST)).rejects.toMatchObject({
      code: "invalid_date_range",
      status: 400,
    });
  });
});
