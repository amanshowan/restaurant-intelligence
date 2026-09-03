"use client";

import { useCallback, useEffect, useState } from "react";

import { DateRangeControl } from "@/components/date-range-control";
import { ErrorPanel } from "@/components/error-panel";
import { PageHeader } from "@/components/page-header";
import { StatCard } from "@/components/stat-card";
import { ApiError, getOverview, type OverviewResponse } from "@/lib/api";
import { discountRatePercent } from "@/lib/metrics";
import {
  defaultDateRange,
  validateDateRange,
  type DateRange,
} from "@/lib/date-range";
import {
  formatCount,
  formatDateRangeLabel,
  formatMoneyPence,
  formatPercent,
} from "@/lib/format";

/** A period the business either did not trade in or has no imported data for. */
function isEmptyPeriod(data: OverviewResponse): boolean {
  return (
    data.payment_order_count === 0 &&
    data.refund_event_count === 0 &&
    data.gross_sales_pence === 0
  );
}

export function OverviewDashboard() {
  // Computed once, on first render, from the clock — never pinned to a month
  // that happens to hold data. See `defaultDateRange`.
  const [range, setRange] = useState<DateRange>(() => defaultDateRange());

  const [data, setData] = useState<OverviewResponse | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  // The request whose result is currently on screen. Compared against the
  // request the current inputs describe, below.
  const [settledKey, setSettledKey] = useState<string | null>(null);
  // Bumped to re-run the effect on "Try again" without changing the range.
  const [attempt, setAttempt] = useState(0);

  const validationError = validateDateRange(range);

  // Identifies the request the current inputs ask for. Also the effect's
  // dependency, so an object identity change cannot re-fire a fetch that the
  // values themselves did not change.
  const requestKey = `${range.startDate}|${range.endDate}|${attempt}`;

  // Loading is DERIVED, never stored: we are loading exactly when the result
  // on screen is not the one the current inputs describe. Storing it would
  // mean calling setState synchronously inside the effect below, which
  // cascades an extra render on every fetch — and it would be a second source
  // of truth that could disagree with the data beside it.
  const busy = validationError === null && settledKey !== requestKey;

  useEffect(() => {
    // A range the server is certain to reject is not worth a round trip. The
    // message is already on screen next to the field that caused it.
    if (validationError) return;

    // Abort on cleanup so a slow response for an abandoned range cannot land
    // after a newer one and overwrite it.
    const controller = new AbortController();

    // Every setState below happens in an async callback, after the effect body
    // has returned — never synchronously within it.
    getOverview(range, { signal: controller.signal })
      .then((result) => {
        setData(result);
        setError(null);
        setSettledKey(requestKey);
      })
      .catch((caught: unknown) => {
        if (controller.signal.aborted) return;
        setError(
          caught instanceof ApiError
            ? caught
            : new ApiError({
                status: 0,
                code: "unexpected_error",
                detail: "Something went wrong loading these figures.",
              }),
        );
        setSettledKey(requestKey);
      });

    return () => controller.abort();
    // `range` is read inside, but `requestKey` is derived from its two fields
    // and is what actually decides whether a new request is needed.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [requestKey, validationError]);

  const retry = useCallback(() => setAttempt((value) => value + 1), []);

  // While a request is in flight the PREVIOUS figures stay on screen, dimmed,
  // instead of collapsing to skeletons. Nothing moves, and the numbers being
  // replaced are visibly the old ones.
  const stale = busy && data !== null;

  const value = (render: (d: OverviewResponse) => string): string | null =>
    data === null ? null : render(data);

  return (
    <>
      <PageHeader
        title="Overview"
        description={
          "Headline trading figures for an inclusive Europe/London date range. " +
          "Refunds reduce net sales but are not counted as orders, so average " +
          "order value stays honest."
        }
        actions={
          <DateRangeControl
            value={range}
            onChange={setRange}
            error={validationError}
            busy={busy}
          />
        }
      />

      {error ? (
        <ErrorPanel error={error} onRetry={retry} />
      ) : (
        <>
          <div className="mb-2 flex items-baseline justify-between gap-4">
            <h2 className="text-[13px] font-semibold text-ink">
              {data ? formatDateRangeLabel(data.start_date, data.end_date) : " "}
            </h2>
            {data && isEmptyPeriod(data) && (
              <span className="text-[12px] text-ink-muted">
                No trade recorded in this period.
              </span>
            )}
          </div>

          {/* Primary figures: what the operator came to see. */}
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-3">
            <StatCard
              label="Net Sales"
              value={value((d) => formatMoneyPence(d.net_sales_pence))}
              hint="After discounts and refunds"
              stale={stale}
            />
            <StatCard
              label="Payment Orders"
              value={value((d) => formatCount(d.payment_order_count))}
              hint={
                data && data.refund_event_count > 0
                  ? `${formatCount(data.refund_event_count)} refund events excluded`
                  : "Refund events excluded"
              }
              stale={stale}
            />
            <StatCard
              label="Average Order Value"
              value={value((d) => formatMoneyPence(d.average_order_value_pence))}
              hint="Net sales per paid order"
              stale={stale}
            />
          </div>

          {/* Supporting figures. */}
          <div className="mt-3 grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-3">
            <StatCard
              label="Net Units"
              value={value((d) => formatCount(d.net_units))}
              hint="Units sold less units refunded"
              emphasis="secondary"
              stale={stale}
            />
            <StatCard
              label="Gross Sales"
              value={value((d) => formatMoneyPence(d.gross_sales_pence))}
              hint="Before discounts"
              emphasis="secondary"
              stale={stale}
            />
            <StatCard
              label="Discounts"
              value={value((d) => formatMoneyPence(d.discounts_pence))}
              hint={
                data
                  ? `${formatPercent(
                      discountRatePercent(
                        data.discounts_pence,
                        data.gross_sales_pence,
                      ),
                    )} of gross sales`
                  : undefined
              }
              emphasis="secondary"
              stale={stale}
            />
          </div>

          <p className="mt-5 text-[12px] leading-relaxed text-ink-subtle">
            Dates are inclusive local calendar days, so the final day is
            included in full. Money is held as integer pence end to end and
            converted to pounds only for display.
          </p>
        </>
      )}
    </>
  );
}
