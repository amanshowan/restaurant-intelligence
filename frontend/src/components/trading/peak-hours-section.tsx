"use client";

import { useState } from "react";

import { SectionPanel } from "@/components/section-panel";
import type { AnalyticsResource } from "@/lib/use-analytics-resource";
import type { PeakHourCell, PeakHoursResponse } from "@/lib/api";
import { HEATMAP_BINS, heatmapRows, intensityBin } from "@/lib/charts";
import { formatCount, formatHour, formatMoneyPence } from "@/lib/format";

import { EmptyNote } from "./revenue-section";

/**
 * The validated sequential ramp, index 0 = no trade.
 *
 * One hue, monotonic in lightness, with adjacent steps far enough apart to be
 * told apart and a light end that clears 2:1 against the surface. Binned rather
 * than continuous: past a handful of classes adjacent shades stop being
 * distinguishable and the legend stops meaning anything.
 */
const HEAT_TOKENS = [
  "var(--color-heat-0)",
  "var(--color-heat-1)",
  "var(--color-heat-2)",
  "var(--color-heat-3)",
  "var(--color-heat-4)",
];

/** Hours labelled on the axis. All 24 columns render; only some are labelled. */
const LABELLED_HOURS = new Set([0, 3, 6, 9, 12, 15, 18, 21]);

interface HoverState {
  cell: PeakHourCell;
  /** Horizontal centre of the cell, within the scrolling grid. */
  x: number;
  /** Top of the cell, within the scrolling grid. */
  y: number;
  /**
   * Place the panel BELOW the cell rather than above it.
   *
   * The grid scrolls horizontally, and `overflow-x: auto` makes the vertical
   * axis clip too — so a panel drawn above the first row is cut off by the
   * container rather than overflowing it. The top rows flip downwards.
   */
  below: boolean;
}

/** Half the panel's width, used to keep it inside the grid at either edge. */
const TOOLTIP_HALF_WIDTH = 92;

function hoverStateFor(
  cell: PeakHourCell,
  element: HTMLElement,
  rowIndex: number,
): HoverState {
  const gridWidth = (element.offsetParent as HTMLElement | null)?.scrollWidth ?? 0;
  const centre = element.offsetLeft + element.offsetWidth / 2;

  return {
    cell,
    // Clamped, so the panel for hour 00 or hour 23 stays within the grid
    // instead of being clipped at the edge it sits against.
    x: gridWidth
      ? Math.min(Math.max(centre, TOOLTIP_HALF_WIDTH), gridWidth - TOOLTIP_HALF_WIDTH)
      : centre,
    y: element.offsetTop,
    below: rowIndex < 3,
  };
}

export function PeakHoursSection({
  resource,
}: {
  resource: AnalyticsResource<PeakHoursResponse>;
}) {
  const { data, error, busy, retry } = resource;
  const [hover, setHover] = useState<HoverState | null>(null);

  const rows = data ? heatmapRows(data) : [];
  const peak = data?.peak_payment_order_count ?? 0;

  return (
    <SectionPanel
      title="Peak hours"
      description="Payment orders by local trading hour, aggregated across the range. Hours are Europe/London as the till recorded them."
      error={error}
      onRetry={retry}
      busy={busy}
      hasData={data !== null}
    >
      {rows.length === 0 ? (
        <EmptyNote>No hourly data for this range.</EmptyNote>
      ) : peak === 0 ? (
        <EmptyNote>No payment orders in any hour in this range.</EmptyNote>
      ) : (
        <div className="flex flex-col gap-3">
          {/*
            Horizontally scrollable on narrow viewports. 24 columns cannot be
            legible across a phone, and shrinking them until they are not is
            worse than asking for a swipe: the weekday labels stay pinned to the
            left edge so a scrolled row is still identifiable.
          */}
          <div className="relative overflow-x-auto">
            <div className="min-w-[620px]">
              {rows.map((row, rowIndex) => (
                <div key={row.isoWeekday} className="flex items-center gap-1">
                  {/*
                    self-stretch so the label's opaque background covers the
                    FULL row height. Sized to its text alone, it leaves a few
                    pixels of cell visible above and below it, and scrolled
                    cells bleed through the gap.
                  */}
                  <span className="sticky left-0 z-10 flex w-[38px] shrink-0 items-center justify-end self-stretch bg-surface pr-1.5 text-[11px] text-ink-muted">
                    {row.weekday.slice(0, 3)}
                  </span>
                  <div className="flex flex-1 gap-[2px] py-[1px]">
                    {row.cells.map((cell) => {
                      const bin = intensityBin(cell.payment_order_count, peak);
                      return (
                        <button
                          key={cell.hour}
                          type="button"
                          // Focusable, so the figures are reachable without a
                          // pointer; the same handler serves hover and focus.
                          onMouseEnter={(event) =>
                            setHover(hoverStateFor(cell, event.currentTarget, rowIndex))
                          }
                          onFocus={(event) =>
                            setHover(hoverStateFor(cell, event.currentTarget, rowIndex))
                          }
                          onMouseLeave={() => setHover(null)}
                          onBlur={() => setHover(null)}
                          aria-label={`${row.weekday} ${formatHour(cell.hour)}: ${formatCount(cell.payment_order_count)} payment orders, ${formatMoneyPence(cell.net_sales_pence)}, ${formatCount(cell.net_units)} units`}
                          className="h-[22px] flex-1 rounded-[2px] transition-transform hover:scale-[1.18]"
                          style={{
                            backgroundColor: HEAT_TOKENS[bin],
                            // A hairline on the empty class, so a closed hour
                            // still reads as a cell rather than a hole.
                            boxShadow:
                              bin === 0 ? "inset 0 0 0 1px var(--color-line)" : undefined,
                          }}
                        />
                      );
                    })}
                  </div>
                </div>
              ))}

              {/* Hour axis, aligned to the cell track by the same left offset. */}
              <div className="flex items-center gap-1 pt-1">
                <span className="w-[38px] shrink-0" />
                <div className="flex flex-1 gap-[2px]">
                  {Array.from({ length: 24 }, (_, hour) => (
                    <span
                      key={hour}
                      className="flex-1 text-center text-[10px] text-ink-subtle"
                    >
                      {LABELLED_HOURS.has(hour) ? String(hour).padStart(2, "0") : ""}
                    </span>
                  ))}
                </div>
              </div>

              {hover && (
                <div
                  className={`pointer-events-none absolute z-20 w-max -translate-x-1/2 rounded-md border border-line bg-surface px-3 py-2 text-[12px] shadow-md ${
                    hover.below ? "" : "-translate-y-full"
                  }`}
                  style={{ left: hover.x, top: hover.below ? hover.y + 28 : hover.y - 6 }}
                  role="status"
                >
                  <p className="font-semibold text-ink">
                    {hover.cell.weekday} {formatHour(hover.cell.hour)}
                  </p>
                  <dl className="mt-1.5 grid grid-cols-[auto_auto] gap-x-4 gap-y-0.5">
                    <dt className="text-ink-muted">Payment orders</dt>
                    <dd className="tabular text-right font-medium text-ink">
                      {formatCount(hover.cell.payment_order_count)}
                    </dd>
                    <dt className="text-ink-muted">Net sales</dt>
                    <dd className="tabular text-right font-medium text-ink">
                      {formatMoneyPence(hover.cell.net_sales_pence)}
                    </dd>
                    <dt className="text-ink-muted">Net units</dt>
                    <dd className="tabular text-right font-medium text-ink">
                      {formatCount(hover.cell.net_units)}
                    </dd>
                  </dl>
                </div>
              )}
            </div>
          </div>

          <div className="flex flex-wrap items-center justify-between gap-3">
            <HeatLegend peak={peak} />
            {data && data.busiest.length > 0 && (
              <p className="text-[12px] text-ink-muted">
                Busiest:{" "}
                <span className="font-medium text-ink">
                  {data.busiest[0].weekday} {formatHour(data.busiest[0].hour)}
                </span>{" "}
                · {formatCount(data.busiest[0].payment_order_count)} orders
              </p>
            )}
          </div>
        </div>
      )}
    </SectionPanel>
  );
}

function HeatLegend({ peak }: { peak: number }) {
  return (
    <div className="flex items-center gap-2 text-[11px] text-ink-subtle">
      <span>0</span>
      <div className="flex gap-[2px]">
        {HEAT_TOKENS.map((token, index) => (
          <span
            key={token}
            className="h-3 w-6 rounded-[2px]"
            style={{
              backgroundColor: token,
              boxShadow: index === 0 ? "inset 0 0 0 1px var(--color-line)" : undefined,
            }}
          />
        ))}
      </div>
      <span>
        {formatCount(peak)} order{peak === 1 ? "" : "s"}
      </span>
      <span className="hidden sm:inline">
        · {HEATMAP_BINS} bands, scaled to the busiest hour
      </span>
    </div>
  );
}
