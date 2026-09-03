"use client";

import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { SectionPanel } from "@/components/section-panel";
import type { AnalyticsResource } from "@/lib/use-analytics-resource";
import { NARROW_VIEWPORT, useMediaQuery } from "@/lib/use-media-query";
import type { Granularity, RevenueResponse } from "@/lib/api";
import { revenuePoints, tickInterval, type RevenuePoint } from "@/lib/charts";
import {
  formatAxisMoney,
  formatCount,
  formatLongDate,
  formatMoneyPence,
} from "@/lib/format";

import { EmptyNote } from "@/components/empty-note";
import {
  AXIS_STYLE,
  ChartFrame,
  GRID_STYLE,
  TOOLTIP_STYLE,
} from "@/components/charts/chart-frame";

/** Axis labels in whole pounds. Pence on a tick would be unreadable noise. */
interface TooltipPayload {
  active?: boolean;
  payload?: { payload: RevenuePoint }[];
}

function RevenueTooltip({
  active,
  payload,
  granularity,
}: TooltipPayload & { granularity: Granularity }) {
  if (!active || !payload?.length) return null;
  const point = payload[0].payload;

  return (
    <div className="rounded-md border border-line bg-surface px-3 py-2 text-[12px] shadow-sm">
      <p className="font-semibold text-ink">
        {granularity === "week" ? "Week commencing " : ""}
        {formatLongDate(point.periodStart)}
      </p>
      <dl className="mt-1.5 grid grid-cols-[auto_auto] gap-x-4 gap-y-0.5">
        <dt className="text-ink-muted">Net sales</dt>
        <dd className="tabular text-right font-medium text-ink">
          {formatMoneyPence(point.netSalesPence)}
        </dd>
        <dt className="text-ink-muted">Payment orders</dt>
        <dd className="tabular text-right font-medium text-ink">
          {formatCount(point.paymentOrderCount)}
        </dd>
        <dt className="text-ink-muted">Net units</dt>
        <dd className="tabular text-right font-medium text-ink">
          {formatCount(point.netUnits)}
        </dd>
      </dl>
    </div>
  );
}

export function RevenueSection({
  resource,
  granularity,
  onGranularityChange,
}: {
  resource: AnalyticsResource<RevenueResponse>;
  granularity: Granularity;
  onGranularityChange: (next: Granularity) => void;
}) {
  const { data, error, busy, retry } = resource;
  const points = data ? revenuePoints(data) : [];

  // A phone fits roughly half the labels a dashboard-width chart does. Without
  // this the 31 daily ticks overlap into an unreadable smear at 375px.
  const narrow = useMediaQuery(NARROW_VIEWPORT);
  const interval = tickInterval(points.length, narrow ? 4 : 8);
  const traded = points.some((point) => point.paymentOrderCount !== 0);
  // With no trade at all the axis has no range, and Recharts renders five
  // identical "£0" ticks. There is no scale to read, so the labels are
  // suppressed rather than repeated; the note below says why the chart is flat.
  const flat = points.length > 0 && points.every((point) => point.netSalesPence === 0);
  const valueTick = flat ? false : AXIS_STYLE.tick;

  return (
    <SectionPanel
      title="Revenue over time"
      description={
        granularity === "week"
          ? "Weekly buckets start on Monday, so the first may open before the selected start date."
          : "One bucket per local trading day. Days with no trade are shown as zero, not omitted."
      }
      error={error}
      onRetry={retry}
      busy={busy}
      hasData={data !== null}
      actions={<GranularityToggle value={granularity} onChange={onGranularityChange} />}
    >
      {data && points.length === 0 ? (
        <EmptyNote>No periods in this range.</EmptyNote>
      ) : (
        <div className="flex flex-col gap-1">
          {/*
            Two charts sharing one x-axis, NOT one chart with two y-axes.
            Money and order counts have unrelated scales, and plotting them
            against two axes on one plot invents a correlation from an
            arbitrary alignment of the scales.
          */}
          <p className="text-[11px] font-semibold uppercase tracking-wider text-ink-subtle">
            Net sales
          </p>
          <ChartFrame
            height={190}
            label={`Net sales per ${granularity === "week" ? "week" : "day"}`}
          >
            {/* right margin leaves room for the final x tick, which is centred on the
                  last point and would otherwise be clipped by the SVG edge */}
            <AreaChart data={points} margin={{ top: 6, right: 24, bottom: 0, left: 0 }}>
              <CartesianGrid {...GRID_STYLE} vertical={false} />
              <XAxis dataKey="label" interval={interval} {...AXIS_STYLE} />
              <YAxis
                width={52}
                tickFormatter={formatAxisMoney}
                {...AXIS_STYLE}
                tick={valueTick}
              />
              <Tooltip
                {...TOOLTIP_STYLE}
                content={<RevenueTooltip granularity={granularity} />}
              />
              <Area
                type="monotone"
                dataKey="netSalesPence"
                stroke="var(--color-chart-mark)"
                strokeWidth={2}
                fill="var(--color-chart-mark-soft)"
                // No dot per point: 31 markers is chart junk. The hover
                // crosshair is how a single period gets read.
                dot={false}
                activeDot={{ r: 4, strokeWidth: 0 }}
                isAnimationActive={false}
              />
            </AreaChart>
          </ChartFrame>

          <p className="mt-3 text-[11px] font-semibold uppercase tracking-wider text-ink-subtle">
            Payment orders
          </p>
          <ChartFrame
            height={130}
            label={`Payment orders per ${granularity === "week" ? "week" : "day"}`}
          >
            <BarChart data={points} margin={{ top: 6, right: 24, bottom: 0, left: 0 }}>
              <CartesianGrid {...GRID_STYLE} vertical={false} />
              <XAxis dataKey="label" interval={interval} {...AXIS_STYLE} />
              {/* Three ticks, chosen rather than left to Recharts: this plot
                  is short enough that a denser set gets one label silently
                  dropped, leaving an axis that reads 0, 200, 400, 800. */}
              <YAxis
                width={52}
                tickCount={3}
                allowDecimals={false}
                {...AXIS_STYLE}
                tick={traded ? AXIS_STYLE.tick : false}
              />
              <Tooltip
                {...TOOLTIP_STYLE}
                content={<RevenueTooltip granularity={granularity} />}
              />
              <Bar
                dataKey="paymentOrderCount"
                fill="var(--color-chart-mark)"
                radius={[2, 2, 0, 0]}
                isAnimationActive={false}
              />
            </BarChart>
          </ChartFrame>

          {!traded && (
            <EmptyNote>
              No payment orders in any period in this range.
            </EmptyNote>
          )}
        </div>
      )}
    </SectionPanel>
  );
}

function GranularityToggle({
  value,
  onChange,
}: {
  value: Granularity;
  onChange: (next: Granularity) => void;
}) {
  return (
    <div
      role="group"
      aria-label="Bucket size"
      className="flex rounded-md border border-line-strong p-0.5"
    >
      {(["day", "week"] as const).map((option) => (
        <button
          key={option}
          type="button"
          onClick={() => onChange(option)}
          aria-pressed={value === option}
          className={`rounded px-2.5 py-1 text-[12px] font-medium transition-colors ${
            value === option
              ? "bg-accent-soft text-accent"
              : "text-ink-muted hover:text-ink"
          }`}
        >
          {option === "day" ? "Daily" : "Weekly"}
        </button>
      ))}
    </div>
  );
}
