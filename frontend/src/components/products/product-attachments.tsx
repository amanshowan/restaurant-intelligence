"use client";

import { EmptyNote } from "@/components/empty-note";
import type { ProductAttachmentsResponse } from "@/lib/api";
import { productLabel } from "@/lib/products";
import { formatCount, formatMultiplier, formatPercent } from "@/lib/format";

/**
 * What else appears in orders containing the selected product.
 *
 * EVIDENCE, stated as a measured fact. The sentence a reader should be able to
 * build from a row is "17.7% of Big Breakfast orders also contained English
 * Breakfast Tea" — and nothing here suggests that either product should
 * therefore be promoted, repriced or bundled. That would need cost, margin and
 * elasticity data this system does not hold.
 */
export function ProductAttachments({
  attachments,
  anchorLabel,
}: {
  attachments: ProductAttachmentsResponse;
  anchorLabel: string;
}) {
  const rows = attachments.attachments;

  if (attachments.anchor_order_count === 0) {
    return (
      <EmptyNote>
        {anchorLabel} appears in no payment orders in this range, so there is
        nothing to attach.
      </EmptyNote>
    );
  }

  if (rows.length === 0) {
    return (
      <EmptyNote>
        No product met the minimum of{" "}
        {formatCount(attachments.min_pair_orders)} shared order
        {attachments.min_pair_orders === 1 ? "" : "s"} with {anchorLabel}.
      </EmptyNote>
    );
  }

  return (
    <div className="flex flex-col gap-2">
      <p className="text-[11px] leading-relaxed text-ink-subtle">
        Across{" "}
        <span className="tabular font-medium text-ink-muted">
          {formatCount(attachments.anchor_order_count)}
        </span>{" "}
        payment orders containing {anchorLabel}.{" "}
        <span className="font-medium">Attach</span> is the share of those orders
        that also contained the other product;{" "}
        <span className="font-medium">lift</span> is how much more often the two
        appear together than their individual popularity would predict.
      </p>

      {/* No min-width: this table lives inside a narrow detail panel, and a
          minimum that forced it to scroll hid the lift column by default. */}
      <div className="overflow-x-auto">
        <table className="w-full text-[12px]">
          <thead>
            <tr className="border-b border-line text-left text-[11px] uppercase tracking-wider text-ink-subtle">
              <th scope="col" className="pb-1.5 font-semibold">Also bought</th>
              <th scope="col" className="pb-1.5 text-right font-semibold">Orders</th>
              <th scope="col" className="pb-1.5 text-right font-semibold">Attach</th>
              <th scope="col" className="pb-1.5 text-right font-semibold">Lift</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((entry) => (
              <tr
                key={entry.product.product_id}
                className="border-b border-line last:border-0"
              >
                <th scope="row" className="py-1.5 pr-2 text-left font-medium text-ink">
                  {productLabel(entry.product.name, entry.product.variation)}
                </th>
                <td className="tabular py-1.5 text-right text-ink-muted">
                  {formatCount(entry.pair_orders)}
                </td>
                <td className="tabular py-1.5 text-right text-ink">
                  {formatPercent(entry.attachment_rate_percent)}
                </td>
                {/* A null lift is an undefined ratio, not 1.0. */}
                <td className="tabular py-1.5 text-right text-ink-muted">
                  {formatMultiplier(entry.lift)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <p className="text-[11px] leading-relaxed text-ink-subtle">
        Read lift alongside the order count: a pairing seen only a handful of
        times can show a large lift that means very little.
      </p>
    </div>
  );
}
