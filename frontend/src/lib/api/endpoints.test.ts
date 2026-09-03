import { afterEach, describe, expect, it, vi } from "vitest";

import { getOverview, getReadiness } from "./endpoints";
import type { OverviewResponse } from "./types";

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
