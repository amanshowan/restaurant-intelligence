"use client";

import type { MenuEvidenceRow } from "@/lib/api";
import {
  defaultDirectionFor,
  type ProductColumn,
  type ProductSortState,
} from "@/lib/products";
import { formatCount, formatMoneyPence, formatPercent } from "@/lib/format";

import { MovementCell } from "./movement-cell";

interface Column {
  key: ProductColumn;
  label: string;
  align: "left" | "right";
  /**
   * Hidden while the table's CONTAINER is narrow.
   *
   * A container query, not a viewport one: the table sits beside the detail
   * panel on a wide screen, so the space it actually has depends on whether a
   * product is selected, not on how large the window is.
   */
  secondary?: boolean;
}

/**
 * Headline measures first, supporting detail after.
 *
 * Movement sits with net sales and units rather than at the far right, so the
 * four columns an operator scans are the four that survive when the table
 * narrows and the rest scroll.
 */
const COLUMNS: Column[] = [
  { key: "product", label: "Product", align: "left" },
  { key: "net_sales", label: "Net sales", align: "right" },
  { key: "net_units", label: "Units", align: "right" },
  { key: "movement", label: "Movement", align: "right" },
  { key: "payment_orders", label: "Orders", align: "right", secondary: true },
  { key: "average_price", label: "Avg price", align: "right", secondary: true },
  { key: "share", label: "Share", align: "right", secondary: true },
  { key: "discounts", label: "Discounts", align: "right", secondary: true },
  { key: "discount_rate", label: "Disc. rate", align: "right", secondary: true },
];

export function ProductTable({
  rows,
  sort,
  onSortChange,
  selectedId,
  onSelect,
}: {
  rows: MenuEvidenceRow[];
  sort: ProductSortState;
  onSortChange: (next: ProductSortState) => void;
  selectedId: number | null;
  onSelect: (productId: number) => void;
}) {
  function toggle(column: ProductColumn) {
    onSortChange(
      sort.column === column
        ? { column, direction: sort.direction === "asc" ? "desc" : "asc" }
        : { column, direction: defaultDirectionFor(column) },
    );
  }

  return (
    // Horizontal scroll rather than shrinking: these are precise figures meant
    // to be compared down a column, and squeezing them wraps every heading.
    <div className="@container overflow-x-auto">
      <table className="w-full min-w-[430px] border-collapse text-[12px]">
        <thead>
          <tr className="border-b border-line">
            {COLUMNS.map((column) => {
              const active = sort.column === column.key;
              return (
                <th
                  key={column.key}
                  scope="col"
                  className={[
                    "sticky top-0 z-10 bg-surface pb-1.5 text-[11px] font-semibold uppercase tracking-wider",
                    column.align === "right" ? "text-right" : "text-left",
                    column.secondary ? "hidden @3xl:table-cell" : "",
                  ].join(" ")}
                >
                  <button
                    type="button"
                    onClick={() => toggle(column.key)}
                    // Announces the current sort to assistive technology, which
                    // an arrow glyph alone does not.
                    aria-sort={
                      active
                        ? sort.direction === "asc"
                          ? "ascending"
                          : "descending"
                        : "none"
                    }
                    className={`inline-flex items-center gap-1 uppercase tracking-wider ${
                      active ? "text-accent" : "text-ink-subtle hover:text-ink"
                    }`}
                  >
                    {column.label}
                    <span aria-hidden className="text-[9px]">
                      {active ? (sort.direction === "asc" ? "▲" : "▼") : "↕"}
                    </span>
                  </button>
                </th>
              );
            })}
          </tr>
        </thead>

        <tbody>
          {rows.map((row) => {
            const selected = row.product.product_id === selectedId;
            return (
              <tr
                key={row.product.product_id}
                onClick={() => onSelect(row.product.product_id)}
                className={`cursor-pointer border-b border-line last:border-0 ${
                  selected ? "bg-accent-soft" : "hover:bg-surface-muted"
                }`}
              >
                <th scope="row" className="py-1.5 pr-3 text-left font-normal">
                  <button
                    type="button"
                    // The row is clickable, but the name is the keyboard-
                    // reachable control: a tr cannot take focus meaningfully.
                    onClick={(event) => {
                      event.stopPropagation();
                      onSelect(row.product.product_id);
                    }}
                    aria-pressed={selected}
                    className="text-left"
                  >
                    <span className="font-medium text-ink">{row.product.name}</span>
                    {/* Variation kept visually distinct from the name: Regular
                        and Large are different products, not one with a label. */}
                    {row.product.variation && (
                      <span className="ml-1.5 rounded border border-line px-1 py-px text-[10px] text-ink-muted">
                        {row.product.variation}
                      </span>
                    )}
                  </button>
                </th>
                <td className="tabular py-1.5 text-right text-ink">
                  {formatMoneyPence(row.net_sales_pence)}
                </td>
                <td className="tabular py-1.5 text-right text-ink-muted">
                  {formatCount(row.net_units)}
                </td>
                <td className="py-1.5 pl-3 text-right">
                  <MovementCell row={row} />
                </td>
                <td className="tabular hidden py-1.5 text-right text-ink-muted @3xl:table-cell">
                  {formatCount(row.payment_order_count)}
                </td>
                <td className="tabular hidden py-1.5 text-right text-ink-muted @3xl:table-cell">
                  {row.average_selling_price_pence === null
                    ? "—"
                    : formatMoneyPence(row.average_selling_price_pence)}
                </td>
                <td className="tabular hidden py-1.5 text-right text-ink-muted @3xl:table-cell">
                  {formatPercent(row.share_of_menu_net_sales_percent, 2)}
                </td>
                <td className="tabular hidden py-1.5 text-right text-ink-muted @3xl:table-cell">
                  {formatMoneyPence(row.discounts_pence)}
                </td>
                <td className="tabular hidden py-1.5 text-right text-ink-muted @3xl:table-cell">
                  {formatPercent(row.discount_rate_percent, 2)}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
