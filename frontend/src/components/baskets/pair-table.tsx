"use client";

import type { ProductPairEntry } from "@/lib/api";
import {
  WEAK_EVIDENCE_PAIR_ORDERS,
  pairALabel,
  pairBLabel,
  pairKey,
} from "@/lib/baskets";
import { formatCount, formatMultiplier, formatPercent } from "@/lib/format";

/**
 * Pairs, with both directional readings of each symmetric fact.
 *
 * The dataset is UNORDERED — each pair appears exactly once — but confidence is
 * directional, so both A→B and B→A are shown. They differ whenever the two
 * products have different overall popularity, and reading only one of them is
 * the commonest way to misread association data.
 */
export function PairTable({ pairs }: { pairs: ProductPairEntry[] }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[620px] text-[12px]">
        <thead>
          <tr className="border-b border-line text-left text-[11px] uppercase tracking-wider text-ink-subtle">
            <th scope="col" className="pb-1.5 font-semibold">Product A</th>
            <th scope="col" className="pb-1.5 font-semibold">Product B</th>
            <th scope="col" className="pb-1.5 text-right font-semibold">Pair orders</th>
            <th scope="col" className="pb-1.5 text-right font-semibold">Support</th>
            <th scope="col" className="pb-1.5 text-right font-semibold">A → B</th>
            <th scope="col" className="pb-1.5 text-right font-semibold">B → A</th>
            <th scope="col" className="pb-1.5 text-right font-semibold">Lift</th>
          </tr>
        </thead>
        <tbody>
          {pairs.map((pair) => {
            const thin = pair.pair_orders <= WEAK_EVIDENCE_PAIR_ORDERS;
            return (
              <tr key={pairKey(pair)} className="border-b border-line last:border-0">
                <th scope="row" className="py-1.5 pr-3 text-left font-medium text-ink">
                  {pairALabel(pair)}
                </th>
                <td className="py-1.5 pr-3 font-medium text-ink">
                  {pairBLabel(pair)}
                </td>
                <td className="tabular py-1.5 text-right text-ink">
                  {formatCount(pair.pair_orders)}
                  {thin && (
                    <span
                      className="ml-1 text-[10px] text-ink-subtle"
                      title="Few shared orders — read the lift with caution."
                    >
                      thin
                    </span>
                  )}
                </td>
                <td className="tabular py-1.5 text-right text-ink-muted">
                  {formatPercent(pair.support_percent, 2)}
                </td>
                <td className="tabular py-1.5 text-right text-ink-muted">
                  {formatPercent(pair.confidence_a_to_b_percent)}
                </td>
                <td className="tabular py-1.5 text-right text-ink-muted">
                  {formatPercent(pair.confidence_b_to_a_percent)}
                </td>
                {/* Null lift is an undefined ratio, never 1.0. */}
                <td className="tabular py-1.5 text-right font-medium text-ink">
                  {formatMultiplier(pair.lift)}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
