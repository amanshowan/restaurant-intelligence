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

import {
  AXIS_STYLE,
  ChartFrame,
  GRID_STYLE,
  TOOLTIP_STYLE,
} from "@/components/charts/chart-frame";
import { EmptyNote } from "@/components/empty-note";
import type { Granularity } from "@/lib/api";
import { productTrendPoints, type ProductTrendPoint } from "@/lib/products";
import type { ProductTrendResponse } from "@/lib/api";
import {
  formatAxisMoney,
  formatCount,
  formatLongDate,
  formatMoneyPence,
} from "@/lib/format";
import { tickInterval } from "@/lib/charts";
import { NARROW_VIEWPORT, useMediaQuery } from "@/lib/use-media-query";

function TrendTooltip({
  active,
  payload,
  granularity,
}: {
  active?: boolean;
  payload?: { payload: ProductTrendPoint }[];
  granularity: Granularity;
}) {
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
        <dt className="text-ink-muted">Units</dt>
        <dd className="tabular text-right font-medium text-ink">
          {formatCount(point.netUnits)}
        </dd>
        <dt className="text-ink-muted">Orders</dt>
        <dd className="tabular text-right font-medium text-ink">
          {formatCount(point.paymentOrderCount)}
        </dd>
      </dl>
    </div>
  );
}

/**
 * One product over time: net sales and units.
 *
 * Two charts sharing an x-axis rather than one with two y-scales. Money and
 * unit counts have unrelated ranges, and aligning two axes on one plot invents
 * a correlation out of an arbitrary choice of scale.
 */
export function ProductTrendChart({
  trend,
  granularity,
}: {
  trend: ProductTrendResponse;
  granularity: Granularity;
}) {
  const points = productTrendPoints(trend);
  const narrow = useMediaQuery(NARROW_VIEWPORT);
  const interval = tickInterval(points.length, narrow ? 3 : 6);

  if (points.length === 0) {
    return <EmptyNote>No periods in this range.</EmptyNote>;
  }

  const traded = points.some((point) => point.netUnits !== 0);
  const flat = points.every((point) => point.netSalesPence === 0);

  return (
    <div className="flex flex-col gap-1">
      <p className="text-[11px] font-semibold uppercase tracking-wider text-ink-subtle">
        Net sales
      </p>
      <ChartFrame height={140} label="Net sales for the selected product over time">
        <AreaChart data={points} margin={{ top: 6, right: 24, bottom: 0, left: 0 }}>
          <CartesianGrid {...GRID_STYLE} vertical={false} />
          <XAxis dataKey="label" interval={interval} {...AXIS_STYLE} />
          <YAxis
            width={50}
            tickFormatter={formatAxisMoney}
            {...AXIS_STYLE}
            tick={flat ? false : AXIS_STYLE.tick}
          />
          <Tooltip
            {...TOOLTIP_STYLE}
            content={<TrendTooltip granularity={granularity} />}
          />
          <Area
            type="monotone"
            dataKey="netSalesPence"
            stroke="var(--color-chart-mark)"
            strokeWidth={2}
            fill="var(--color-chart-mark-soft)"
            dot={false}
            activeDot={{ r: 4, strokeWidth: 0 }}
            isAnimationActive={false}
          />
        </AreaChart>
      </ChartFrame>

      <p className="mt-2 text-[11px] font-semibold uppercase tracking-wider text-ink-subtle">
        Units
      </p>
      <ChartFrame height={110} label="Units sold for the selected product over time">
        <BarChart data={points} margin={{ top: 6, right: 24, bottom: 0, left: 0 }}>
          <CartesianGrid {...GRID_STYLE} vertical={false} />
          <XAxis dataKey="label" interval={interval} {...AXIS_STYLE} />
          <YAxis
            width={50}
            tickCount={3}
            allowDecimals={false}
            {...AXIS_STYLE}
            tick={traded ? AXIS_STYLE.tick : false}
          />
          <Tooltip
            {...TOOLTIP_STYLE}
            content={<TrendTooltip granularity={granularity} />}
          />
          <Bar
            dataKey="netUnits"
            fill="var(--color-chart-mark)"
            radius={[2, 2, 0, 0]}
            isAnimationActive={false}
          />
        </BarChart>
      </ChartFrame>

      {!traded && (
        <EmptyNote>No units sold in any period in this range.</EmptyNote>
      )}
    </div>
  );
}
