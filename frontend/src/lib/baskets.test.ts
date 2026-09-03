import { describe, expect, it } from "vitest";

import {
  DEFAULT_MIN_PAIR_ORDERS,
  WEAK_EVIDENCE_PAIR_ORDERS,
  filterPairs,
  pairALabel,
  pairBLabel,
  pairKey,
  pairScatterPoints,
} from "./baskets";
import type { ProductPairEntry, ProductPairsResponse } from "./api";

function pair(overrides: Partial<ProductPairEntry> = {}): ProductPairEntry {
  return {
    product_a: { product_id: 2, name: "Caffe Latte", variation: "Regular" },
    product_b: { product_id: 38, name: "Tap Water", variation: "Regular" },
    pair_orders: 53,
    product_a_orders: 470,
    product_b_orders: 261,
    support_percent: 1.9601,
    confidence_a_to_b_percent: 11.2766,
    confidence_b_to_a_percent: 20.3065,
    lift: 1.1683,
    ...overrides,
  };
}

function pairsResponse(pairs: ProductPairEntry[]): ProductPairsResponse {
  return {
    start_date: "2026-08-01",
    end_date: "2026-08-31",
    kinds: ["menu_item"],
    sort: "pair_orders",
    min_pair_orders: 20,
    eligible_order_count: 2704,
    distinct_product_count: 138,
    qualifying_pair_count: pairs.length,
    pairs,
  };
}

describe("pairKey", () => {
  it("identifies the UNORDERED pair, whichever way round it is listed", () => {
    const forward = pair();
    const reversed = pair({
      product_a: { product_id: 38, name: "Tap Water", variation: "Regular" },
      product_b: { product_id: 2, name: "Caffe Latte", variation: "Regular" },
    });
    expect(pairKey(forward)).toBe(pairKey(reversed));
  });

  it("distinguishes different pairs", () => {
    expect(pairKey(pair())).not.toBe(
      pairKey(pair({ product_b: { product_id: 99, name: "X", variation: "" } })),
    );
  });
});

describe("pair labels", () => {
  it("shows the variation, keeping price points distinct", () => {
    expect(pairALabel(pair())).toBe("Caffe Latte · Regular");
  });

  it("omits an empty variation", () => {
    expect(
      pairBLabel(pair({ product_b: { product_id: 5, name: "Poached Egg", variation: "" } })),
    ).toBe("Poached Egg");
  });
});

describe("thresholds", () => {
  it("defaults above the API's own minimum of 1", () => {
    // At min_pair_orders=1 the API returns thousands of pairs and a lift-sorted
    // list opens on one-off co-occurrences: correct arithmetic, no evidence.
    expect(DEFAULT_MIN_PAIR_ORDERS).toBeGreaterThan(1);
    expect(WEAK_EVIDENCE_PAIR_ORDERS).toBeLessThan(DEFAULT_MIN_PAIR_ORDERS);
  });
});

describe("pairScatterPoints", () => {
  it("plots co-occurrence count against lift", () => {
    const points = pairScatterPoints(
      pairsResponse([pair({ pair_orders: 48, lift: 2.5372 })]),
    );
    expect(points).toHaveLength(1);
    expect(points[0].pairOrders).toBe(48);
    expect(points[0].lift).toBe(2.5372);
    expect(points[0].labelA).toBe("Caffe Latte · Regular");
  });

  it("DROPS pairs with an undefined lift rather than plotting them at zero", () => {
    // Plotting null as 0 would assert "no association" where the ratio is
    // simply undefined.
    const points = pairScatterPoints(
      pairsResponse([pair({ lift: null }), pair({ lift: 2.4 })]),
    );
    expect(points).toHaveLength(1);
    expect(points[0].lift).toBe(2.4);
  });

  it("carries the metrics a tooltip needs to identify the pair", () => {
    const [point] = pairScatterPoints(pairsResponse([pair()]));
    expect(point.supportPercent).toBe(1.9601);
    expect(point.confidenceAtoB).toBe(11.2766);
    expect(point.confidenceBtoA).toBe(20.3065);
  });

  it("handles an empty result", () => {
    expect(pairScatterPoints(pairsResponse([]))).toEqual([]);
  });
});

describe("filterPairs", () => {
  const pairs = [
    pair(),
    pair({
      product_a: { product_id: 16, name: "English Breakfast Tea", variation: "" },
      product_b: { product_id: 40, name: "Toasted Currant Tea Cake", variation: "" },
    }),
  ];

  it("matches EITHER side, because the pair is unordered", () => {
    // "What goes with tap water?" must find the pair whichever column it is in.
    expect(filterPairs(pairs, "tap water")).toHaveLength(1);
    expect(filterPairs(pairs, "currant")).toHaveLength(1);
  });

  it("matches case-insensitively and returns all for an empty query", () => {
    expect(filterPairs(pairs, "CAFFE")).toHaveLength(1);
    expect(filterPairs(pairs, "  ")).toHaveLength(2);
  });
});
