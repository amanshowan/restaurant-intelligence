import { describe, expect, it } from "vitest";

import {
  DIRECTION_MARKS,
  MOVEMENT_STATUS_LABELS,
  defaultDirectionFor,
  excludeZeroRevenue,
  filterEvidenceRows,
  productLabel,
  productTrendPoints,
  sortEvidenceRows,
  summariseEvidence,
} from "./products";
import type {
  MenuEvidenceResponse,
  MenuEvidenceRow,
  ProductTrendResponse,
} from "./api";

function row(overrides: Partial<MenuEvidenceRow> = {}): MenuEvidenceRow {
  return {
    product: { product_id: 1, name: "Caffe Latte", variation: "Regular" },
    kind: "menu_item",
    gross_sales_pence: 217170,
    discounts_pence: 4384,
    net_sales_pence: 212786,
    net_units: 570,
    payment_order_count: 470,
    average_selling_price_pence: 373,
    discount_rate_percent: 2.0187,
    share_of_menu_net_sales_percent: 4.53,
    share_of_menu_units_percent: 6.55,
    previous_net_sales_pence: 0,
    previous_net_units: 0,
    net_sales_change_pence: 212786,
    net_units_change: 570,
    net_sales_percent_change: null,
    movement_status: "new_in_period",
    revenue_direction: "increasing",
    strongest_attachment: null,
    ...overrides,
  };
}

function evidence(rows: MenuEvidenceRow[]): MenuEvidenceResponse {
  return {
    start_date: "2026-08-01",
    end_date: "2026-08-31",
    previous_start_date: "2026-07-01",
    previous_end_date: "2026-07-31",
    kinds: ["menu_item"],
    min_pair_orders: 5,
    eligible_order_count: 2704,
    total_net_sales_pence: 4691591,
    total_net_units: 8705,
    rows,
  };
}

describe("productLabel", () => {
  it("joins name and variation", () => {
    expect(productLabel("Caffe Latte", "Regular")).toBe("Caffe Latte · Regular");
  });

  it("uses the name alone when there is no price point", () => {
    // An empty variation is normal, not missing data.
    expect(productLabel("Poached Egg", "")).toBe("Poached Egg");
  });
});

describe("movement vocabulary", () => {
  it("describes the arithmetic, never the business", () => {
    const wording = Object.values(MOVEMENT_STATUS_LABELS).join(" ").toLowerCase();
    for (const judgement of [
      "star", "dog", "winner", "loser", "opportunity", "poor", "best", "worst",
    ]) {
      expect(wording).not.toContain(judgement);
    }
    expect(MOVEMENT_STATUS_LABELS.new_in_period).toBe("New in period");
    expect(MOVEMENT_STATUS_LABELS.not_comparable).toBe("Not comparable");
  });

  it("marks direction with a glyph, so colour is never the only signal", () => {
    expect(DIRECTION_MARKS.increasing).not.toBe(DIRECTION_MARKS.decreasing);
    expect(DIRECTION_MARKS.unchanged).toBeTruthy();
  });
});

describe("sortEvidenceRows", () => {
  const rows = [
    row({ product: { product_id: 1, name: "Beta", variation: "" }, net_sales_pence: 200, net_units: 5 }),
    row({ product: { product_id: 2, name: "Alpha", variation: "" }, net_sales_pence: 300, net_units: 1 }),
    row({ product: { product_id: 3, name: "Gamma", variation: "" }, net_sales_pence: 100, net_units: 9 }),
  ];

  it("sorts a measure descending", () => {
    const sorted = sortEvidenceRows(rows, { column: "net_sales", direction: "desc" });
    expect(sorted.map((r) => r.net_sales_pence)).toEqual([300, 200, 100]);
  });

  it("sorts a measure ascending", () => {
    const sorted = sortEvidenceRows(rows, { column: "net_units", direction: "asc" });
    expect(sorted.map((r) => r.net_units)).toEqual([1, 5, 9]);
  });

  it("sorts names alphabetically, not by id", () => {
    const sorted = sortEvidenceRows(rows, { column: "product", direction: "asc" });
    expect(sorted.map((r) => r.product.name)).toEqual(["Alpha", "Beta", "Gamma"]);
  });

  it("puts undefined values LAST in both directions", () => {
    // An undefined average selling price is not the cheapest price. Letting
    // null lead an ascending sort would put "we cannot say" top of a ranking.
    const withNulls = [
      row({ product: { product_id: 1, name: "A", variation: "" }, average_selling_price_pence: 500 }),
      row({ product: { product_id: 2, name: "B", variation: "" }, average_selling_price_pence: null }),
      row({ product: { product_id: 3, name: "C", variation: "" }, average_selling_price_pence: 100 }),
    ];

    for (const direction of ["asc", "desc"] as const) {
      const sorted = sortEvidenceRows(withNulls, { column: "average_price", direction });
      expect(sorted[sorted.length - 1].average_selling_price_pence).toBeNull();
    }
  });

  it("sorts movement on the money change, which every row has", () => {
    // The percentage is undefined for new_in_period rows, so it cannot be the
    // sort key without dropping them to the bottom regardless of size.
    const movers = [
      row({ product: { product_id: 1, name: "A", variation: "" }, net_sales_change_pence: -33743, net_sales_percent_change: -43.57, movement_status: "comparable" }),
      row({ product: { product_id: 2, name: "B", variation: "" }, net_sales_change_pence: 17660, net_sales_percent_change: 38.37, movement_status: "comparable" }),
      row({ product: { product_id: 3, name: "C", variation: "" }, net_sales_change_pence: 5000, net_sales_percent_change: null, movement_status: "new_in_period" }),
    ];
    const sorted = sortEvidenceRows(movers, { column: "movement", direction: "desc" });
    expect(sorted.map((r) => r.net_sales_change_pence)).toEqual([17660, 5000, -33743]);
  });

  it("does not mutate its input", () => {
    const original = rows.map((r) => r.net_sales_pence);
    sortEvidenceRows(rows, { column: "net_sales", direction: "asc" });
    expect(rows.map((r) => r.net_sales_pence)).toEqual(original);
  });

  it("handles an empty set", () => {
    expect(sortEvidenceRows([], { column: "net_sales", direction: "desc" })).toEqual([]);
  });
});

describe("defaultDirectionFor", () => {
  it("reads names A-Z and measures largest first", () => {
    expect(defaultDirectionFor("product")).toBe("asc");
    expect(defaultDirectionFor("net_sales")).toBe("desc");
  });
});

describe("filterEvidenceRows", () => {
  const rows = [
    row({ product: { product_id: 1, name: "Caffe Latte", variation: "Regular" } }),
    row({ product: { product_id: 2, name: "Caffe Latte", variation: "Large" } }),
    row({ product: { product_id: 3, name: "Poached Egg", variation: "" } }),
  ];

  it("matches on name, case-insensitively", () => {
    expect(filterEvidenceRows(rows, "latte")).toHaveLength(2);
    expect(filterEvidenceRows(rows, "POACHED")).toHaveLength(1);
  });

  it("matches on variation, keeping the two price points distinct", () => {
    const large = filterEvidenceRows(rows, "large");
    expect(large).toHaveLength(1);
    expect(large[0].product.variation).toBe("Large");
  });

  it("returns everything for an empty or whitespace query", () => {
    expect(filterEvidenceRows(rows, "")).toHaveLength(3);
    expect(filterEvidenceRows(rows, "   ")).toHaveLength(3);
  });

  it("returns nothing when there is no match", () => {
    expect(filterEvidenceRows(rows, "zzz")).toEqual([]);
  });
});

describe("excludeZeroRevenue", () => {
  it("removes only genuinely zero-revenue rows when asked", () => {
    // Tap Water is a real menu item selling hundreds of units at £0.00. It is
    // never hidden by default — this runs only behind an explicit control.
    const rows = [
      row({ product: { product_id: 1, name: "Tap Water", variation: "Regular" }, net_sales_pence: 0, net_units: 424 }),
      row({ product: { product_id: 2, name: "Caffe Latte", variation: "Regular" }, net_sales_pence: 212786 }),
    ];
    const kept = excludeZeroRevenue(rows);
    expect(kept).toHaveLength(1);
    expect(kept[0].product.name).toBe("Caffe Latte");
    // The unfiltered set still holds it: nothing is dropped at parse time.
    expect(rows).toHaveLength(2);
  });
});

describe("summariseEvidence", () => {
  it("uses the backend's own totals, not a sum of the rows on screen", () => {
    // total_* covers every matching product before any limit. Re-summing the
    // visible rows would silently change meaning as soon as a filter applied.
    const summary = summariseEvidence(
      evidence([row({ net_sales_pence: 1, net_units: 1 })]),
    );
    expect(summary.menuNetSalesPence).toBe(4691591);
    expect(summary.menuNetUnits).toBe(8705);
    expect(summary.variationCount).toBe(1);
  });

  it("finds the leading product by sales and by units separately", () => {
    const summary = summariseEvidence(
      evidence([
        row({ product: { product_id: 1, name: "Big Breakfast", variation: "Regular" }, net_sales_pence: 366796, net_units: 282 }),
        row({ product: { product_id: 2, name: "Tap Water", variation: "Regular" }, net_sales_pence: 0, net_units: 424 }),
      ]),
    );
    expect(summary.leadingBySales?.product.name).toBe("Big Breakfast");
    // Different products can lead each measure, and a zero-revenue item can
    // legitimately lead on units.
    expect(summary.leadingByUnits?.product.name).toBe("Tap Water");
  });

  it("returns nulls for an empty period rather than inventing a leader", () => {
    const summary = summariseEvidence(evidence([]));
    expect(summary.leadingBySales).toBeNull();
    expect(summary.leadingByUnits).toBeNull();
    expect(summary.variationCount).toBe(0);
  });
});

describe("productTrendPoints", () => {
  function trend(buckets: Partial<ProductTrendResponse["buckets"][number]>[]): ProductTrendResponse {
    return {
      start_date: "2026-08-01",
      end_date: "2026-08-31",
      granularity: "day",
      product: {
        product_id: 1, name: "Caffe Latte", variation: "Regular", kind: "menu_item",
        gross_sales_pence: 0, discounts_pence: 0, net_sales_pence: 0, net_units: 0,
        payment_order_count: 0, average_selling_price_pence: null,
        share_of_net_sales_percent: null, share_of_units_percent: null,
      },
      buckets: buckets.map((b, i) => ({
        period_start: `2026-08-0${i + 1}`,
        gross_sales_pence: 0, discounts_pence: 0, net_sales_pence: 0,
        net_units: 0, payment_order_count: 0, ...b,
      })),
    };
  }

  it("keeps zero buckets so a period with no sales stays visible", () => {
    const points = productTrendPoints(
      trend([{ net_sales_pence: 500 }, { net_sales_pence: 0 }, { net_sales_pence: 700 }]),
    );
    expect(points).toHaveLength(3);
    expect(points[1].netSalesPence).toBe(0);
  });

  it("preserves the API's order and labels each bucket", () => {
    const points = productTrendPoints(trend([{}, {}]));
    expect(points.map((p) => p.periodStart)).toEqual(["2026-08-01", "2026-08-02"]);
    expect(points[0].label).toBe("1 Aug");
  });

  it("handles a product with no buckets", () => {
    expect(productTrendPoints(trend([]))).toEqual([]);
  });
});
