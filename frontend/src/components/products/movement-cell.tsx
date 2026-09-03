import type { MenuEvidenceRow } from "@/lib/api";
import {
  DIRECTION_LABELS,
  DIRECTION_MARKS,
  MOVEMENT_STATUS_EXPLANATIONS,
  MOVEMENT_STATUS_LABELS,
} from "@/lib/products";
import { formatMoneyChangePence, formatPercentChange } from "@/lib/format";

/**
 * Movement against the previous comparable period.
 *
 * Reported mechanically. The glyph and the wording carry the direction, and
 * colour only reinforces them — red and green alone are invisible to a
 * significant number of readers and vanish in print and forced-colours modes.
 *
 * Where the backend says the percentage is UNDEFINED it stays undefined: a
 * product with nothing in the previous period has not grown by infinity, and
 * has certainly not grown by 0%.
 */
export function MovementCell({ row }: { row: MenuEvidenceRow }) {
  const { revenue_direction: direction, movement_status: status } = row;

  const tone =
    direction === "increasing"
      ? "text-positive"
      : direction === "decreasing"
        ? "text-negative"
        : "text-ink-muted";

  return (
    <div className="flex flex-col items-end gap-0.5">
      <span className={`tabular flex items-center gap-1 font-medium ${tone}`}>
        <span aria-hidden>{DIRECTION_MARKS[direction]}</span>
        <span className="sr-only">{DIRECTION_LABELS[direction]}:</span>
        {formatMoneyChangePence(row.net_sales_change_pence)}
      </span>

      {status === "comparable" ? (
        <span className="tabular text-[11px] text-ink-subtle">
          {formatPercentChange(row.net_sales_percent_change)}
        </span>
      ) : (
        // Named rather than shown as a dash alone, so the reader learns WHY
        // there is no percentage rather than assuming data is missing.
        <span
          className="text-[11px] text-ink-subtle"
          title={MOVEMENT_STATUS_EXPLANATIONS[status]}
        >
          {MOVEMENT_STATUS_LABELS[status]}
        </span>
      )}
    </div>
  );
}
