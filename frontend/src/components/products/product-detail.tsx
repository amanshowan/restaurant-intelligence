"use client";

import { useCallback, useState } from "react";

import { ErrorPanel } from "@/components/error-panel";
import {
  getProductAttachments,
  getProductTrend,
  type Granularity,
  type MenuEvidenceRow,
  type ProductAttachmentsResponse,
  type ProductTrendResponse,
} from "@/lib/api";
import { useAnalyticsResource } from "@/lib/use-analytics-resource";
import type { DateRange } from "@/lib/date-range";
import { productLabel } from "@/lib/products";
import {
  formatCount,
  formatMoneyPence,
  formatPercent,
} from "@/lib/format";

import { ProductAttachments } from "./product-attachments";
import { ProductTrendChart } from "./product-trend-chart";
import { MovementCell } from "./movement-cell";

/** Attachments below this co-occurrence count are omitted rather than reported
 *  as if they were evidence. Shown in the panel, not applied silently. */
const MIN_ATTACHMENT_ORDERS = 5;
const ATTACHMENT_LIMIT = 8;

/**
 * Everything measured about one selected product.
 *
 * Detail data is fetched ONLY for the current selection — two requests, no
 * matter how large the catalogue. Fetching a trend and an attachment list per
 * table row would be 276 requests for this menu.
 *
 * The headline figures are read from the evidence row the table already holds
 * rather than refetched, so the panel cannot disagree with the row that opened
 * it.
 */
export function ProductDetail({
  row,
  range,
  onClose,
}: {
  row: MenuEvidenceRow;
  range: DateRange;
  onClose: () => void;
}) {
  const [granularity, setGranularity] = useState<Granularity>("day");
  const productId = row.product.product_id;
  const label = productLabel(row.product.name, row.product.variation);

  const rangeKey = `${range.startDate}|${range.endDate}`;

  const trend = useAnalyticsResource<ProductTrendResponse>(
    `trend|${productId}|${rangeKey}|${granularity}`,
    useCallback(
      (signal) => getProductTrend(productId, range, granularity, { signal }),
      [productId, range, granularity],
    ),
  );

  const attachments = useAnalyticsResource<ProductAttachmentsResponse>(
    `attachments|${productId}|${rangeKey}`,
    useCallback(
      (signal) =>
        getProductAttachments(productId, range, {
          signal,
          minPairOrders: MIN_ATTACHMENT_ORDERS,
          limit: ATTACHMENT_LIMIT,
        }),
      [productId, range],
    ),
  );

  return (
    <section
      className="rounded-lg border border-line bg-surface"
      aria-label={`Detail for ${label}`}
    >
      <header className="flex items-start justify-between gap-3 border-b border-line px-4 py-3">
        <div className="min-w-0">
          <h2 className="text-[13px] font-semibold tracking-tight text-ink">
            {row.product.name}
          </h2>
          {row.product.variation && (
            <p className="mt-0.5 text-[11px] text-ink-muted">
              {row.product.variation}
            </p>
          )}
        </div>
        <button
          type="button"
          onClick={onClose}
          className="shrink-0 rounded-md border border-line px-2 py-1 text-[11px] font-medium text-ink-muted hover:bg-surface-muted"
        >
          Close
        </button>
      </header>

      <div className="flex flex-col gap-5 p-4">
        {/* Figures taken from the table's own row — one source of truth. */}
        <dl className="grid grid-cols-2 gap-x-4 gap-y-2 text-[12px]">
          <Figure label="Net sales" value={formatMoneyPence(row.net_sales_pence)} />
          <Figure label="Units" value={formatCount(row.net_units)} />
          <Figure label="Payment orders" value={formatCount(row.payment_order_count)} />
          <Figure
            label="Avg selling price"
            value={
              row.average_selling_price_pence === null
                ? "—"
                : formatMoneyPence(row.average_selling_price_pence)
            }
          />
          <Figure
            label="Discounts"
            value={formatMoneyPence(row.discounts_pence)}
            hint={`${formatPercent(row.discount_rate_percent, 2)} of gross`}
          />
          <Figure
            label="Menu share"
            value={formatPercent(row.share_of_menu_net_sales_percent, 2)}
            hint="of menu net sales"
          />
        </dl>

        <div className="flex items-center justify-between gap-3 border-t border-line pt-3">
          <div>
            <p className="text-[11px] font-semibold uppercase tracking-wider text-ink-subtle">
              Movement
            </p>
            <p className="mt-0.5 text-[11px] text-ink-subtle">
              vs the previous comparable period
            </p>
          </div>
          <MovementCell row={row} />
        </div>

        {/* --- trend --- */}
        <div className="border-t border-line pt-4">
          <div className="mb-2 flex items-center justify-between gap-3">
            <h3 className="text-[12px] font-semibold text-ink">Over time</h3>
            <div
              role="group"
              aria-label="Bucket size"
              className="flex rounded-md border border-line-strong p-0.5"
            >
              {(["day", "week"] as const).map((option) => (
                <button
                  key={option}
                  type="button"
                  onClick={() => setGranularity(option)}
                  aria-pressed={granularity === option}
                  className={`rounded px-2 py-0.5 text-[11px] font-medium ${
                    granularity === option
                      ? "bg-accent-soft text-accent"
                      : "text-ink-muted hover:text-ink"
                  }`}
                >
                  {option === "day" ? "Daily" : "Weekly"}
                </button>
              ))}
            </div>
          </div>

          {trend.error && !trend.data ? (
            <ErrorPanel error={trend.error} onRetry={trend.retry} />
          ) : trend.data ? (
            <div className={trend.busy ? "opacity-50 transition-opacity" : ""}>
              <ProductTrendChart trend={trend.data} granularity={granularity} />
            </div>
          ) : (
            <LoadingBlock height={280} />
          )}
        </div>

        {/* --- attachments --- */}
        <div className="border-t border-line pt-4">
          <h3 className="mb-2 text-[12px] font-semibold text-ink">
            Bought with {label}
          </h3>

          {attachments.error && !attachments.data ? (
            <ErrorPanel error={attachments.error} onRetry={attachments.retry} />
          ) : attachments.data ? (
            <div className={attachments.busy ? "opacity-50 transition-opacity" : ""}>
              <ProductAttachments
                attachments={attachments.data}
                anchorLabel={label}
              />
            </div>
          ) : (
            <LoadingBlock height={140} />
          )}
        </div>
      </div>
    </section>
  );
}

function Figure({
  label,
  value,
  hint,
}: {
  label: string;
  value: string;
  hint?: string;
}) {
  return (
    <div>
      <dt className="text-[11px] font-semibold uppercase tracking-wider text-ink-subtle">
        {label}
      </dt>
      <dd className="tabular mt-0.5 font-semibold text-ink">{value}</dd>
      {hint && <dd className="text-[11px] text-ink-subtle">{hint}</dd>}
    </div>
  );
}

/** Holds the panel's height while detail loads, so nothing below it jumps. */
function LoadingBlock({ height }: { height: number }) {
  return (
    <div
      style={{ height }}
      className="animate-pulse rounded-md bg-surface-muted"
      aria-hidden
    />
  );
}
