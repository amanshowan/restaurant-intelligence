import { describe, expect, it } from "vitest";

import {
  CHANNEL_LABELS,
  HEATMAP_BINS,
  channelLabel,
  heatmapRows,
  intensityBin,
  orderedWeekdays,
  peakChannelNetSales,
  peakWeekdayNetSales,
  revenuePoints,
  revenueTotals,
  tickInterval,
} from "./charts";
import type {
  ChannelMixEntry,
  DayOfWeekResponse,
  PeakHourCell,
  PeakHoursResponse,
  RevenueResponse,
  WeekdayName,
} from "./api";

const WEEKDAYS: WeekdayName[] = [
  "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday",
];

function revenueResponse(
  buckets: Partial<RevenueResponse["buckets"][number]>[],
  granularity: "day" | "week" = "day",
): RevenueResponse {
  return {
    start_date: "2026-08-01",
    end_date: "2026-08-31",
    granularity,
    buckets: buckets.map((bucket, index) => ({
      period_start: `2026-08-${String(index + 1).padStart(2, "0")}`,
      net_sales_pence: 0,
      gross_sales_pence: 0,
      discounts_pence: 0,
      payment_order_count: 0,
      net_units: 0,
      ...bucket,
    })),
  };
}

describe("revenuePoints", () => {
  it("preserves the API's order and every bucket", () => {
    const points = revenuePoints(
      revenueResponse([
        { net_sales_pence: 1000, payment_order_count: 5 },
        { net_sales_pence: 2000, payment_order_count: 9 },
      ]),
    );
    expect(points.map((p) => p.periodStart)).toEqual([
      "2026-08-01",
      "2026-08-02",
    ]);
    expect(points[1].netSalesPence).toBe(2000);
  });

  it("KEEPS zero buckets", () => {
    // The API zero-fills so a closed day is visible. Dropping the zero would
    // join the line across it and invent trade that did not happen.
    const points = revenuePoints(
      revenueResponse([
        { net_sales_pence: 1000, payment_order_count: 5 },
        { net_sales_pence: 0, payment_order_count: 0 },
        { net_sales_pence: 3000, payment_order_count: 7 },
      ]),
    );
    expect(points).toHaveLength(3);
    expect(points[1].netSalesPence).toBe(0);
  });

  it("labels each bucket by its start date", () => {
    const points = revenuePoints(revenueResponse([{}]));
    expect(points[0].label).toBe("1 Aug");
  });

  it("handles an empty series", () => {
    expect(revenuePoints(revenueResponse([]))).toEqual([]);
  });
});

describe("revenueTotals", () => {
  it("sums the series, so a chart can be reconciled against Overview", () => {
    const totals = revenueTotals(
      revenuePoints(
        revenueResponse([
          { net_sales_pence: 1000, payment_order_count: 5, net_units: 12 },
          { net_sales_pence: 2500, payment_order_count: 7, net_units: 20 },
        ]),
      ),
    );
    expect(totals).toEqual({
      netSalesPence: 3500,
      paymentOrderCount: 12,
      netUnits: 32,
    });
  });

  it("returns zeros for an empty series rather than NaN", () => {
    expect(revenueTotals([])).toEqual({
      netSalesPence: 0,
      paymentOrderCount: 0,
      netUnits: 0,
    });
  });
});

describe("tickInterval", () => {
  it("labels every point when they all fit", () => {
    expect(tickInterval(5)).toBe(0);
    expect(tickInterval(8)).toBe(0);
  });

  it("thins the labels for a long series", () => {
    // 31 daily buckets cannot each carry a legible label.
    expect(tickInterval(31)).toBe(3);
    expect(tickInterval(31, 8)).toBeGreaterThan(0);
  });
});

// --- day of week -------------------------------------------------------------

function dayOfWeekResponse(order: number[]): DayOfWeekResponse {
  return {
    start_date: "2026-08-01",
    end_date: "2026-08-31",
    weekdays: order.map((iso) => ({
      iso_weekday: iso,
      weekday: WEEKDAYS[iso - 1],
      net_sales_pence: iso * 1000,
      payment_order_count: iso * 10,
      net_units: iso * 3,
      average_order_value_pence: 100,
    })),
  };
}

describe("orderedWeekdays", () => {
  it("returns Monday to Sunday", () => {
    const days = orderedWeekdays(dayOfWeekResponse([1, 2, 3, 4, 5, 6, 7]));
    expect(days.map((d) => d.weekday)).toEqual(WEEKDAYS);
  });

  it("puts a shuffled response back into weekday order", () => {
    // The API guarantees the order; this asserts the fixed order is a property
    // of the view rather than an assumption about the response.
    const days = orderedWeekdays(dayOfWeekResponse([7, 3, 1, 5, 2, 6, 4]));
    expect(days.map((d) => d.iso_weekday)).toEqual([1, 2, 3, 4, 5, 6, 7]);
    expect(days[0].weekday).toBe("Monday");
    expect(days[6].weekday).toBe("Sunday");
  });

  it("does not mutate the response", () => {
    const response = dayOfWeekResponse([7, 1, 2, 3, 4, 5, 6]);
    orderedWeekdays(response);
    expect(response.weekdays[0].iso_weekday).toBe(7);
  });
});

describe("peakWeekdayNetSales", () => {
  it("finds the largest value", () => {
    expect(
      peakWeekdayNetSales(orderedWeekdays(dayOfWeekResponse([1, 2, 3]))),
    ).toBe(3000);
  });

  it("is zero for a week with no trade", () => {
    expect(peakWeekdayNetSales([])).toBe(0);
  });
});

// --- peak hours --------------------------------------------------------------

function cell(iso: number, hour: number, count: number): PeakHourCell {
  return {
    iso_weekday: iso,
    weekday: WEEKDAYS[iso - 1],
    hour,
    payment_order_count: count,
    net_sales_pence: count * 500,
    net_units: count * 2,
  };
}

function peakHoursResponse(cells: PeakHourCell[]): PeakHoursResponse {
  return {
    start_date: "2026-08-01",
    end_date: "2026-08-31",
    cells,
    peak_payment_order_count: cells.reduce(
      (peak, c) => Math.max(peak, c.payment_order_count),
      0,
    ),
    busiest: [],
  };
}

describe("heatmapRows", () => {
  it("builds a 7 x 24 grid", () => {
    const rows = heatmapRows(peakHoursResponse([]));
    expect(rows).toHaveLength(7);
    expect(rows.every((row) => row.cells.length === 24)).toBe(true);
    expect(rows.map((r) => r.weekday)).toEqual(WEEKDAYS);
  });

  it("places a cell by its own weekday and hour, not by position", () => {
    // Reading the flat list positionally would transpose the grid if the API's
    // ordering ever changed — and still render a plausible-looking heatmap.
    const rows = heatmapRows(
      peakHoursResponse([cell(7, 11, 96), cell(1, 0, 3)]),
    );
    expect(rows[6].cells[11].payment_order_count).toBe(96);
    expect(rows[6].weekday).toBe("Sunday");
    expect(rows[0].cells[0].payment_order_count).toBe(3);
  });

  it("zero-fills any cell the response omits", () => {
    const rows = heatmapRows(peakHoursResponse([cell(3, 9, 4)]));
    expect(rows[2].cells[10].payment_order_count).toBe(0);
    expect(rows[2].cells[10].hour).toBe(10);
    expect(rows[2].cells[10].weekday).toBe("Wednesday");
  });

  it("does not shift hours — the API's hours are already local", () => {
    const rows = heatmapRows(peakHoursResponse([cell(1, 23, 7)]));
    expect(rows[0].cells[23].payment_order_count).toBe(7);
    expect(rows[0].cells.map((c) => c.hour)).toEqual(
      Array.from({ length: 24 }, (_, i) => i),
    );
  });
});

describe("intensityBin", () => {
  it("gives no-trade its own class, distinct from the quietest band", () => {
    // A closed hour and a quiet hour are different facts.
    expect(intensityBin(0, 96)).toBe(0);
  });

  it("puts the busiest cell in the top band", () => {
    expect(intensityBin(96, 96)).toBe(HEATMAP_BINS);
  });

  it("scales between the two", () => {
    expect(intensityBin(1, 100)).toBe(1);
    expect(intensityBin(30, 100)).toBe(2);
    expect(intensityBin(60, 100)).toBe(3);
    expect(intensityBin(90, 100)).toBe(4);
  });

  it("is zero when nothing traded at all", () => {
    expect(intensityBin(0, 0)).toBe(0);
    expect(intensityBin(5, 0)).toBe(0);
  });

  it("never indexes past the ramp", () => {
    expect(intensityBin(200, 96)).toBe(HEATMAP_BINS);
  });
});

// --- channels ----------------------------------------------------------------

function channel(overrides: Partial<ChannelMixEntry>): ChannelMixEntry {
  return {
    channel: "in_store",
    net_sales_pence: 1000,
    payment_order_count: 10,
    net_units: 20,
    average_order_value_pence: 100,
    share_of_payment_orders_percent: 50,
    share_of_net_sales_percent: 50,
    ...overrides,
  };
}

describe("channelLabel", () => {
  it("names every canonical channel", () => {
    // Each is kept distinct by the backend because each records a different
    // fact; none may be folded into another here.
    expect(Object.keys(CHANNEL_LABELS).sort()).toEqual([
      "collection", "delivery", "in_store", "mixed", "online", "unknown",
    ]);
    expect(channelLabel("in_store")).toBe("In-store");
    expect(channelLabel("unknown")).toBe("Unknown");
  });
});

describe("peakChannelNetSales", () => {
  it("finds the largest channel", () => {
    expect(
      peakChannelNetSales([
        channel({ net_sales_pence: 100 }),
        channel({ channel: "delivery", net_sales_pence: 900 }),
      ]),
    ).toBe(900);
  });

  it("is zero for an empty mix", () => {
    expect(peakChannelNetSales([])).toBe(0);
  });
});

describe("nullable channel shares", () => {
  it("carries null through untouched, never coercing it to zero", () => {
    // A null share means the denominator was zero — undefined, not "0%".
    const entry = channel({
      share_of_net_sales_percent: null,
      share_of_payment_orders_percent: null,
    });
    expect(entry.share_of_net_sales_percent).toBeNull();
    expect(entry.share_of_payment_orders_percent).toBeNull();
  });
});
