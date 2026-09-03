/**
 * Presentation logic for the Basket Analysis page.
 *
 * Support, confidence and lift all arrive computed from
 * `/analytics/baskets/pairs`. Nothing here recalculates them — this file only
 * shapes them for a table and a scatter plot.
 */

import type { ProductPairEntry, ProductPairsResponse } from "./api";
import { productLabel } from "./products";

/**
 * A stable key for a pair.
 *
 * Built from both product ids in ascending order, so it identifies the
 * UNORDERED pair: the same two products always produce the same key whichever
 * way round the response happens to list them.
 */
export function pairKey(pair: ProductPairEntry): string {
  const [low, high] = [pair.product_a.product_id, pair.product_b.product_id].sort(
    (a, b) => a - b,
  );
  return `${low}-${high}`;
}

export function pairALabel(pair: ProductPairEntry): string {
  return productLabel(pair.product_a.name, pair.product_a.variation);
}

export function pairBLabel(pair: ProductPairEntry): string {
  return productLabel(pair.product_b.name, pair.product_b.variation);
}

/**
 * The default minimum co-occurrence count for the pairs table.
 *
 * The API's own default is 1, which returns thousands of pairs and puts
 * one-off co-occurrences with enormous lift at the top of a lift-sorted list —
 * arithmetically correct and analytically worthless. Twenty is a starting
 * point, not a rule: the control is on screen, the value is shown, and the
 * response echoes the threshold actually applied.
 */
export const DEFAULT_MIN_PAIR_ORDERS = 20;

/** Pairs at or below this count are flagged as thin evidence in the table. */
export const WEAK_EVIDENCE_PAIR_ORDERS = 5;

export interface PairScatterPoint {
  key: string;
  /** x — how often the two were actually bought together. */
  pairOrders: number;
  /** y — how much more often than independence predicts. Null pairs are dropped. */
  lift: number;
  supportPercent: number | null;
  confidenceAtoB: number | null;
  confidenceBtoA: number | null;
  labelA: string;
  labelB: string;
}

/**
 * Pairs as scatter points: co-occurrence count against lift.
 *
 * The two axes together are the point of the plot. Lift alone rewards rarity —
 * two products bought together twice, and never apart, score enormously — so
 * plotting it against the count shows at a glance which associations are both
 * strong AND actually observed. Points with an undefined lift are omitted
 * rather than plotted at zero, which would assert no association where the
 * ratio is simply undefined.
 */
export function pairScatterPoints(
  response: ProductPairsResponse,
): PairScatterPoint[] {
  return response.pairs
    .filter((pair): pair is ProductPairEntry & { lift: number } =>
      pair.lift !== null && Number.isFinite(pair.lift),
    )
    .map((pair) => ({
      key: pairKey(pair),
      pairOrders: pair.pair_orders,
      lift: pair.lift,
      supportPercent: pair.support_percent,
      confidenceAtoB: pair.confidence_a_to_b_percent,
      confidenceBtoA: pair.confidence_b_to_a_percent,
      labelA: pairALabel(pair),
      labelB: pairBLabel(pair),
    }));
}

/**
 * Case-insensitive match against either side of the pair.
 *
 * Matches either product, because "what goes with tea?" is the question an
 * operator actually asks, and the pair is unordered so tea may be listed on
 * either side.
 */
export function filterPairs(
  pairs: ProductPairEntry[],
  query: string,
): ProductPairEntry[] {
  const needle = query.trim().toLowerCase();
  if (!needle) return pairs;

  return pairs.filter((pair) =>
    `${pairALabel(pair)} ${pairBLabel(pair)}`.toLowerCase().includes(needle),
  );
}
