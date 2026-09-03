"use client";

import { CartesianGrid, Line, LineChart, Tooltip, XAxis, YAxis } from "recharts";

import {
  AXIS_STYLE,
  ChartFrame,
  GRID_STYLE,
  TOOLTIP_STYLE,
} from "@/components/charts/chart-frame";
import type { ForecastUnit } from "@/lib/api";
import {
  formatForecastAxisValue,
  formatForecastValue,
  type ForecastChartPoint,
} from "@/lib/forecast";
import { formatLongDate } from "@/lib/format";
import { tickInterval } from "@/lib/charts";
import { NARROW_VIEWPORT, useMediaQuery } from "@/lib/use-media-query";

interface TooltipProps {
  active?: boolean;
  payload?: { payload: ForecastChartPoint }[];
}

function ForecastTooltip({
  active,
  payload,
  unit,
  measure,
}: TooltipProps & { unit: ForecastUnit; measure: string }) {
  if (!active || !payload?.length) return null;
  const point = payload[0].payload;

  return (
    <div className="rounded-md border border-line bg-surface px-3 py-2 text-[12px] shadow-sm">
      <p className="font-semibold text-ink">{formatLongDate(point.date)}</p>
      <dl className="mt-1.5 grid grid-cols-[auto_auto] gap-x-4 gap-y-0.5">
        <dt className="text-ink-muted">Predicted {measure}</dt>
        <dd className="tabular text-right font-medium text-ink">
          {formatForecastValue(unit, point.predictedValue)}
        </dd>
      </dl>
    </div>
  );
}

/**
 * The forecast as a single series against the day it is predicted for.
 *
 * ONE series, one axis, one colour. There is nothing to compare it against on
 * the same plot: the observed history is measured and these values are not, so
 * drawing them as one continuous line would let the eye read fourteen
 * predictions as a continuation of fact.
 *
 * The line is DASHED and every day carries a marker. Both are deliberate: the
 * dash is the visual cue that none of this happened, and at fourteen points a
 * marker per day is a readable value rather than the chart junk it would be
 * across a year of daily takings.
 */
export function ForecastChart({
  points,
  unit,
  measure,
}: {
  points: ForecastChartPoint[];
  unit: ForecastUnit;
  measure: string;
}) {
  const narrow = useMediaQuery(NARROW_VIEWPORT);
  const interval = tickInterval(points.length, narrow ? 5 : 14);

  return (
    <ChartFrame
      height={240}
      label={`Predicted daily ${measure} for the ${points.length}-day forecast period`}
    >
      {/* right margin leaves room for the final x tick, which is centred on
          the last point and would otherwise be clipped by the SVG edge */}
      <LineChart data={points} margin={{ top: 6, right: 24, bottom: 0, left: 0 }}>
        <CartesianGrid {...GRID_STYLE} vertical={false} />
        <XAxis dataKey="label" interval={interval} {...AXIS_STYLE} />
        <YAxis
          width={56}
          tickFormatter={(value: number) =>
            formatForecastAxisValue(unit, value)
          }
          allowDecimals={false}
          {...AXIS_STYLE}
        />
        <Tooltip
          {...TOOLTIP_STYLE}
          content={<ForecastTooltip unit={unit} measure={measure} />}
        />
        <Line
          type="monotone"
          dataKey="predictedValue"
          stroke="var(--color-chart-mark)"
          strokeWidth={2}
          strokeDasharray="5 4"
          dot={{ r: 2.5, strokeWidth: 0, fill: "var(--color-chart-mark)" }}
          activeDot={{ r: 4, strokeWidth: 0 }}
          isAnimationActive={false}
        />
      </LineChart>
    </ChartFrame>
  );
}
