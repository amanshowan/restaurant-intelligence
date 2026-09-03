"use client";

import {
  Bar,
  BarChart,
  CartesianGrid,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { SectionPanel } from "@/components/section-panel";
import type { AnalyticsResource } from "@/lib/use-analytics-resource";
import type { DayOfWeekResponse, WeekdayTotals } from "@/lib/api";
import { orderedWeekdays } from "@/lib/charts";
import {
  formatAxisMoney,
  formatCount,
  formatMoneyPence,
} from "@/lib/format";

import {
  AXIS_STYLE,
  ChartFrame,
  GRID_STYLE,
  TOOLTIP_STYLE,
} from "@/components/charts/chart-frame";
import { EmptyNote } from "@/components/empty-note";

function WeekdayTooltip({
  active,
  payload,
}: {
  active?: boolean;
  payload?: { payload: WeekdayTotals }[];
}) {
  if (!active || !payload?.length) return null;
  const day = payload[0].payload;

  return (
    <div className="rounded-md border border-line bg-surface px-3 py-2 text-[12px] shadow-sm">
      <p className="font-semibold text-ink">{day.weekday}</p>
      <dl className="mt-1.5 grid grid-cols-[auto_auto] gap-x-4 gap-y-0.5">
        <dt className="text-ink-muted">Net sales</dt>
        <dd className="tabular text-right font-medium text-ink">
          {formatMoneyPence(day.net_sales_pence)}
        </dd>
        <dt className="text-ink-muted">Payment orders</dt>
        <dd className="tabular text-right font-medium text-ink">
          {formatCount(day.payment_order_count)}
        </dd>
        <dt className="text-ink-muted">Average order</dt>
        <dd className="tabular text-right font-medium text-ink">
          {formatMoneyPence(day.average_order_value_pence)}
        </dd>
      </dl>
    </div>
  );
}

export function DayOfWeekSection({
  resource,
}: {
  resource: AnalyticsResource<DayOfWeekResponse>;
}) {
  const { data, error, busy, retry } = resource;
  const weekdays = data ? orderedWeekdays(data) : [];
  const traded = weekdays.some((day) => day.payment_order_count !== 0);

  return (
    <SectionPanel
      title="Day of the week"
      description="Every occurrence of each weekday in the range, summed — all the Mondays together, not one row per date."
      error={error}
      onRetry={retry}
      busy={busy}
      hasData={data !== null}
    >
      {weekdays.length === 0 ? (
        <EmptyNote>No weekday data for this range.</EmptyNote>
      ) : (
        <div className="flex flex-col gap-4">
          {/*
            Horizontal bars: seven weekday names read far better down the left
            edge than rotated under a vertical axis. One measure, one colour —
            the weekday is already named on the axis, so colouring each bar
            differently would spend the only free channel restating it.
          */}
          <ChartFrame height={200} label="Net sales by day of the week">
            <BarChart
              data={weekdays}
              layout="vertical"
              margin={{ top: 4, right: 12, bottom: 0, left: 0 }}
            >
              <CartesianGrid {...GRID_STYLE} horizontal={false} />
              <XAxis type="number" tickFormatter={formatAxisMoney} {...AXIS_STYLE} />
              <YAxis
                type="category"
                dataKey="weekday"
                width={82}
                {...AXIS_STYLE}
              />
              <Tooltip {...TOOLTIP_STYLE} content={<WeekdayTooltip />} />
              <Bar
                dataKey="net_sales_pence"
                fill="var(--color-chart-mark)"
                radius={[0, 3, 3, 0]}
                barSize={16}
                isAnimationActive={false}
              />
            </BarChart>
          </ChartFrame>

          {/* The chart shows the shape; the table carries the figures. Both,
              because reading a value off a bar is guesswork. */}
          <div className="overflow-x-auto">
            <table className="w-full min-w-[380px] text-[12px]">
              <thead>
                <tr className="border-b border-line text-left text-[11px] uppercase tracking-wider text-ink-subtle">
                  <th scope="col" className="pb-1.5 font-semibold">Day</th>
                  <th scope="col" className="pb-1.5 text-right font-semibold">Net sales</th>
                  <th scope="col" className="pb-1.5 text-right font-semibold">Orders</th>
                  <th scope="col" className="pb-1.5 text-right font-semibold">Avg order</th>
                </tr>
              </thead>
              <tbody>
                {weekdays.map((day) => (
                  <tr key={day.iso_weekday} className="border-b border-line last:border-0">
                    <th scope="row" className="py-1.5 text-left font-medium text-ink">
                      {day.weekday}
                    </th>
                    <td className="tabular py-1.5 text-right text-ink">
                      {formatMoneyPence(day.net_sales_pence)}
                    </td>
                    <td className="tabular py-1.5 text-right text-ink-muted">
                      {formatCount(day.payment_order_count)}
                    </td>
                    <td className="tabular py-1.5 text-right text-ink-muted">
                      {formatMoneyPence(day.average_order_value_pence)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {!traded && <EmptyNote>No payment orders on any weekday in this range.</EmptyNote>}
        </div>
      )}
    </SectionPanel>
  );
}
