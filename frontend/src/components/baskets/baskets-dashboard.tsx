"use client";

import { useCallback, useMemo, useState } from "react";

import { DateRangeControl } from "@/components/date-range-control";
import { EmptyNote } from "@/components/empty-note";
import { ErrorPanel } from "@/components/error-panel";
import { PageHeader } from "@/components/page-header";
import { SectionPanel } from "@/components/section-panel";
import {
  getBasketPairs,
  type PairSort,
  type ProductPairsResponse,
} from "@/lib/api";
import { useAnalyticsResource } from "@/lib/use-analytics-resource";
import {
  defaultDateRange,
  validateDateRange,
  type DateRange,
} from "@/lib/date-range";
import { DEFAULT_MIN_PAIR_ORDERS, filterPairs } from "@/lib/baskets";
import { formatCount, formatDateRangeLabel } from "@/lib/format";

import { PairScatter } from "./pair-scatter";
import { PairTable } from "./pair-table";

/** Enough rows to explore without rendering thousands of table rows at once. */
const PAIR_LIMIT = 200;

const SORT_LABELS: Record<PairSort, string> = {
  pair_orders: "Pair orders",
  lift: "Lift",
  support: "Support",
};

export function BasketsDashboard() {
  const [range, setRange] = useState<DateRange>(() => defaultDateRange());
  const [minPairOrders, setMinPairOrders] = useState(DEFAULT_MIN_PAIR_ORDERS);
  const [sort, setSort] = useState<PairSort>("pair_orders");
  const [query, setQuery] = useState("");

  const validationError = validateDateRange(range);

  // One request. Threshold, sort and limit are all applied by the SERVER, so
  // the page never re-ranks or re-filters what the API already ordered.
  const pairs = useAnalyticsResource<ProductPairsResponse>(
    `pairs|${range.startDate}|${range.endDate}|${minPairOrders}|${sort}`,
    useCallback(
      (signal) =>
        getBasketPairs(range, {
          signal,
          minPairOrders,
          sort,
          limit: PAIR_LIMIT,
        }),
      [range, minPairOrders, sort],
    ),
    { enabled: validationError === null },
  );

  const { data, error, busy, retry } = pairs;

  const visiblePairs = useMemo(
    () => (data ? filterPairs(data.pairs, query) : []),
    [data, query],
  );

  return (
    <>
      <PageHeader
        title="Basket Analysis"
        description="Which products are bought together, measured across payment orders. Evidence only — nothing here recommends bundling, promoting or repricing anything."
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
          <h2 className="text-[13px] font-semibold text-ink">
            {formatDateRangeLabel(range.startDate, range.endDate)}
          </h2>

          <Explainer data={data} />

          <SectionPanel
            title="Pair orders against lift"
            description="Every qualifying pair, positioned by how often it was observed and how unusual that is."
            busy={busy}
            hasData={data !== null}
            error={error}
            onRetry={retry}
          >
            {data ? (
              data.pairs.length === 0 ? (
                <EmptyNote>
                  No pair reached {formatCount(minPairOrders)} shared order
                  {minPairOrders === 1 ? "" : "s"} in this range. Lower the
                  minimum to see thinner pairings.
                </EmptyNote>
              ) : (
                <PairScatter pairs={data} />
              )
            ) : (
              <div className="h-[260px] animate-pulse rounded-md bg-surface-muted" />
            )}
          </SectionPanel>

          <SectionPanel
            title="Product pairs"
            description="Each unordered pair appears once. Confidence is directional, so both readings are shown."
            busy={busy}
            hasData={data !== null}
            error={error}
            onRetry={retry}
            actions={
              <PairControls
                minPairOrders={minPairOrders}
                onMinPairOrdersChange={setMinPairOrders}
                sort={sort}
                onSortChange={setSort}
                query={query}
                onQueryChange={setQuery}
              />
            }
          >
            {data && visiblePairs.length === 0 ? (
              <EmptyNote>
                {data.pairs.length === 0
                  ? `No pair reached ${formatCount(minPairOrders)} shared orders in this range.`
                  : "No pair matches the current filter."}
              </EmptyNote>
            ) : (
              <>
                <PairTable pairs={visiblePairs} />
                {data && (
                  <p className="mt-3 text-[11px] leading-relaxed text-ink-subtle">
                    Showing {formatCount(visiblePairs.length)} of{" "}
                    {formatCount(data.qualifying_pair_count)} pairs meeting the
                    minimum of {formatCount(data.min_pair_orders)} shared order
                    {data.min_pair_orders === 1 ? "" : "s"}
                    {data.qualifying_pair_count > PAIR_LIMIT &&
                      `, capped at the first ${formatCount(PAIR_LIMIT)} by ${SORT_LABELS[data.sort].toLowerCase()}`}
                    .
                  </p>
                )}
              </>
            )}
          </SectionPanel>
        </div>
      )}
    </>
  );
}

function Explainer({ data }: { data: ProductPairsResponse | null }) {
  return (
    <div className="rounded-lg border border-line bg-surface px-4 py-3">
      <dl className="grid grid-cols-1 gap-x-6 gap-y-2 text-[11px] leading-relaxed sm:grid-cols-3">
        <div>
          <dt className="font-semibold text-ink">Support</dt>
          <dd className="text-ink-muted">
            Share of all eligible payment orders containing both products.
          </dd>
        </div>
        <div>
          <dt className="font-semibold text-ink">Confidence (A → B)</dt>
          <dd className="text-ink-muted">
            Share of orders containing A that also contained B. Directional, so
            A → B and B → A differ.
          </dd>
        </div>
        <div>
          <dt className="font-semibold text-ink">Lift</dt>
          <dd className="text-ink-muted">
            How much more often the two appear together than their individual
            popularity predicts. 1.0× is exactly as often.
          </dd>
        </div>
      </dl>

      <p className="mt-3 border-t border-line pt-3 text-[11px] leading-relaxed text-ink-muted">
        <span className="font-medium text-ink">Read lift with the order count.</span>{" "}
        A pair seen once or twice can show an enormous lift and still be
        nothing: the arithmetic is correct, the evidence is not. These are
        observed co-occurrence rates, not tests of statistical significance, and
        they say nothing about cause.
        {data && (
          <>
            {" "}
            Measured across{" "}
            <span className="tabular font-medium text-ink-muted">
              {formatCount(data.eligible_order_count)}
            </span>{" "}
            payment orders containing at least one menu item, over{" "}
            <span className="tabular font-medium text-ink-muted">
              {formatCount(data.distinct_product_count)}
            </span>{" "}
            product variations.
          </>
        )}
      </p>
    </div>
  );
}

function PairControls({
  minPairOrders,
  onMinPairOrdersChange,
  sort,
  onSortChange,
  query,
  onQueryChange,
}: {
  minPairOrders: number;
  onMinPairOrdersChange: (next: number) => void;
  sort: PairSort;
  onSortChange: (next: PairSort) => void;
  query: string;
  onQueryChange: (next: string) => void;
}) {
  return (
    <div className="flex flex-wrap items-center gap-3">
      <label className="flex items-center gap-1.5 text-[11px] text-ink-muted">
        {/* The threshold is a visible, editable control — never applied
            silently. The response echoes the value actually used. */}
        Min pair orders
        <input
          type="number"
          min={1}
          max={1000}
          value={minPairOrders}
          onChange={(event) => {
            const parsed = Number.parseInt(event.target.value, 10);
            if (Number.isFinite(parsed) && parsed >= 1) onMinPairOrdersChange(parsed);
          }}
          className="tabular h-8 w-16 rounded-md border border-line-strong bg-surface px-2 text-[12px] text-ink"
        />
      </label>

      <label className="flex items-center gap-1.5 text-[11px] text-ink-muted">
        Sort
        <select
          value={sort}
          onChange={(event) => onSortChange(event.target.value as PairSort)}
          className="h-8 rounded-md border border-line-strong bg-surface px-2 text-[12px] text-ink"
        >
          {(Object.keys(SORT_LABELS) as PairSort[]).map((option) => (
            <option key={option} value={option}>
              {SORT_LABELS[option]}
            </option>
          ))}
        </select>
      </label>

      <input
        type="search"
        value={query}
        onChange={(event) => onQueryChange(event.target.value)}
        placeholder="Filter pairs"
        aria-label="Filter pairs by product name"
        className="h-8 w-40 rounded-md border border-line-strong bg-surface px-2.5 text-[12px] text-ink"
      />
    </div>
  );
}
