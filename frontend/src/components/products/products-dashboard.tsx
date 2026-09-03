"use client";

import { useCallback, useMemo, useState } from "react";

import { DateRangeControl } from "@/components/date-range-control";
import { EmptyNote } from "@/components/empty-note";
import { ErrorPanel } from "@/components/error-panel";
import { PageHeader } from "@/components/page-header";
import { SectionPanel } from "@/components/section-panel";
import { getMenuEvidence, type MenuEvidenceResponse } from "@/lib/api";
import { useAnalyticsResource } from "@/lib/use-analytics-resource";
import {
  defaultDateRange,
  validateDateRange,
  type DateRange,
} from "@/lib/date-range";
import {
  excludeZeroRevenue,
  filterEvidenceRows,
  productLabel,
  sortEvidenceRows,
  summariseEvidence,
  type ProductSortState,
} from "@/lib/products";
import {
  formatCount,
  formatDateRangeLabel,
  formatMoneyPence,
} from "@/lib/format";

import { ProductDetail } from "./product-detail";
import { ProductTable } from "./product-table";

export function ProductsDashboard() {
  const [range, setRange] = useState<DateRange>(() => defaultDateRange());
  const [sort, setSort] = useState<ProductSortState>({
    column: "net_sales",
    direction: "desc",
  });
  const [query, setQuery] = useState("");
  const [hideZeroRevenue, setHideZeroRevenue] = useState(false);
  const [selectedId, setSelectedId] = useState<number | null>(null);

  const validationError = validateDateRange(range);

  /**
   * ONE request for the whole table.
   *
   * `/analytics/menu/evidence` carries performance, discounting, share,
   * movement and the strongest attachment per product in a single row, so the
   * table needs no per-product follow-up. Composing the same view from
   * /products + /movers + /attachments would be three requests and three
   * windows to keep aligned.
   *
   * No `limit`: the response is the complete menu, which makes the shares
   * correct and lets sorting and filtering happen locally without paging.
   */
  const evidence = useAnalyticsResource<MenuEvidenceResponse>(
    `menu-evidence|${range.startDate}|${range.endDate}`,
    useCallback((signal) => getMenuEvidence(range, { signal }), [range]),
    { enabled: validationError === null },
  );

  const { data, error, busy, retry } = evidence;

  const visibleRows = useMemo(() => {
    if (!data) return [];
    const filtered = filterEvidenceRows(
      hideZeroRevenue ? excludeZeroRevenue(data.rows) : data.rows,
      query,
    );
    return sortEvidenceRows(filtered, sort);
  }, [data, query, hideZeroRevenue, sort]);

  const summary = data ? summariseEvidence(data) : null;

  /**
   * The selected row, resolved from the CURRENT result set.
   *
   * Deliberately derived rather than stored: when the date range changes or a
   * filter hides the product, this becomes null and the detail panel closes,
   * instead of leaving figures attached to a product no longer on screen.
   */
  const selectedRow =
    selectedId === null
      ? null
      : (visibleRows.find((row) => row.product.product_id === selectedId) ?? null);

  return (
    <>
      <PageHeader
        title="Products"
        description="Sales, units, discounting and period movement for every menu variation. Evidence only — nothing here recommends repricing, promoting or removing a product."
        actions={
          <DateRangeControl
            value={range}
            onChange={setRange}
            error={validationError}
            busy={busy}
          />
        }
      />

      {error && !data ? (
        <ErrorPanel error={error} onRetry={retry} />
      ) : (
        <div className="flex flex-col gap-4">
          <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
            <h2 className="text-[13px] font-semibold text-ink">
              {formatDateRangeLabel(range.startDate, range.endDate)}
            </h2>
            {data && (
              <p className="text-[11px] text-ink-subtle">
                Menu items only. Gift vouchers and open-price lines are excluded
                from menu revenue, and compared against{" "}
                {formatDateRangeLabel(
                  data.previous_start_date,
                  data.previous_end_date,
                )}
                .
              </p>
            )}
          </div>

          {summary && <SummaryStrip summary={summary} />}

          {/*
            Two mutually exclusive class strings rather than a conditional
            suffix: emitting `xl:grid-cols-[...]` and `xl:grid-cols-1` together
            leaves the winner to stylesheet order, which reserved an empty
            column for a detail panel that was not open.
          */}
          <div
            className={
              selectedRow
                ? "grid gap-4 xl:grid-cols-[minmax(0,1.85fr)_minmax(0,1fr)] xl:items-start"
                : "grid gap-4"
            }
          >
            {/* Detail first on narrow viewports so a tap does not require
                scrolling back up; beside the table on wide ones. */}
            {selectedRow && (
              <div className="order-1 xl:order-2 xl:sticky xl:top-6">
                <ProductDetail
                  row={selectedRow}
                  range={range}
                  onClose={() => setSelectedId(null)}
                />
              </div>
            )}

            <div className="order-2 xl:order-1">
              <SectionPanel
                title="Product performance"
                description="Select a product for its trend over time and what it is bought with."
                busy={busy}
                hasData={data !== null}
                error={error}
                onRetry={retry}
                actions={
                  <TableControls
                    query={query}
                    onQueryChange={setQuery}
                    hideZeroRevenue={hideZeroRevenue}
                    onHideZeroRevenueChange={setHideZeroRevenue}
                  />
                }
              >
                {data && visibleRows.length === 0 ? (
                  <EmptyNote>
                    {data.rows.length === 0
                      ? "No menu products sold in this range."
                      : "No product matches the current filter."}
                  </EmptyNote>
                ) : (
                  <>
                    <ProductTable
                      rows={visibleRows}
                      sort={sort}
                      onSortChange={setSort}
                      selectedId={selectedRow?.product.product_id ?? null}
                      onSelect={(id) =>
                        setSelectedId((current) => (current === id ? null : id))
                      }
                    />
                    {data && (
                      <p className="mt-3 text-[11px] text-ink-subtle">
                        Showing {formatCount(visibleRows.length)} of{" "}
                        {formatCount(data.rows.length)} menu variations.
                      </p>
                    )}
                  </>
                )}
              </SectionPanel>
            </div>
          </div>
        </div>
      )}
    </>
  );
}

function SummaryStrip({
  summary,
}: {
  summary: ReturnType<typeof summariseEvidence>;
}) {
  return (
    <dl className="grid grid-cols-2 gap-x-6 gap-y-3 rounded-lg border border-line bg-surface px-4 py-3 sm:grid-cols-3 xl:grid-cols-5">
      <Item label="Menu variations" value={formatCount(summary.variationCount)} />
      <Item label="Menu net sales" value={formatMoneyPence(summary.menuNetSalesPence)} />
      <Item label="Menu units" value={formatCount(summary.menuNetUnits)} />
      <Item
        label="Leading by sales"
        value={
          summary.leadingBySales
            ? productLabel(
                summary.leadingBySales.product.name,
                summary.leadingBySales.product.variation,
              )
            : "—"
        }
        hint={
          summary.leadingBySales
            ? formatMoneyPence(summary.leadingBySales.net_sales_pence)
            : undefined
        }
      />
      <Item
        label="Leading by units"
        value={
          summary.leadingByUnits
            ? productLabel(
                summary.leadingByUnits.product.name,
                summary.leadingByUnits.product.variation,
              )
            : "—"
        }
        hint={
          summary.leadingByUnits
            ? `${formatCount(summary.leadingByUnits.net_units)} units`
            : undefined
        }
      />
    </dl>
  );
}

function Item({
  label,
  value,
  hint,
}: {
  label: string;
  value: string;
  hint?: string;
}) {
  return (
    <div className="min-w-0">
      <dt className="text-[11px] font-semibold uppercase tracking-wider text-ink-subtle">
        {label}
      </dt>
      <dd className="tabular mt-0.5 truncate text-[13px] font-semibold text-ink">
        {value}
      </dd>
      {hint && (
        <dd className="tabular truncate text-[11px] text-ink-subtle">{hint}</dd>
      )}
    </div>
  );
}

function TableControls({
  query,
  onQueryChange,
  hideZeroRevenue,
  onHideZeroRevenueChange,
}: {
  query: string;
  onQueryChange: (next: string) => void;
  hideZeroRevenue: boolean;
  onHideZeroRevenueChange: (next: boolean) => void;
}) {
  return (
    <div className="flex flex-wrap items-center gap-3">
      <input
        type="search"
        value={query}
        onChange={(event) => onQueryChange(event.target.value)}
        placeholder="Filter products"
        aria-label="Filter products by name or variation"
        className="h-8 w-44 rounded-md border border-line-strong bg-surface px-2.5 text-[12px] text-ink"
      />
      {/*
        OFF by default and explicitly labelled. Tap Water is a genuine menu item
        selling hundreds of units at £0.00; it is never hidden unless an
        operator asks for it.
      */}
      <label className="flex items-center gap-1.5 text-[11px] text-ink-muted">
        <input
          type="checkbox"
          checked={hideZeroRevenue}
          onChange={(event) => onHideZeroRevenueChange(event.target.checked)}
          className="h-3.5 w-3.5"
        />
        Hide £0.00 items
      </label>
    </div>
  );
}
