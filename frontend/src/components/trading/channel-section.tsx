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
import type { ChannelMixEntry, ChannelMixResponse } from "@/lib/api";
import { channelLabel } from "@/lib/charts";
import {
  formatAxisMoney,
  formatCount,
  formatMoneyPence,
  formatPercent,
} from "@/lib/format";

import {
  AXIS_STYLE,
  ChartFrame,
  GRID_STYLE,
  TOOLTIP_STYLE,
} from "@/components/charts/chart-frame";
import { EmptyNote } from "@/components/empty-note";

type ChannelRow = ChannelMixEntry & { label: string };

function ChannelTooltip({
  active,
  payload,
}: {
  active?: boolean;
  payload?: { payload: ChannelRow }[];
}) {
  if (!active || !payload?.length) return null;
  const row = payload[0].payload;

  return (
    <div className="rounded-md border border-line bg-surface px-3 py-2 text-[12px] shadow-sm">
      <p className="font-semibold text-ink">{row.label}</p>
      <dl className="mt-1.5 grid grid-cols-[auto_auto] gap-x-4 gap-y-0.5">
        <dt className="text-ink-muted">Net sales</dt>
        <dd className="tabular text-right font-medium text-ink">
          {formatMoneyPence(row.net_sales_pence)}
        </dd>
        <dt className="text-ink-muted">Share of sales</dt>
        <dd className="tabular text-right font-medium text-ink">
          {formatPercent(row.share_of_net_sales_percent)}
        </dd>
        <dt className="text-ink-muted">Payment orders</dt>
        <dd className="tabular text-right font-medium text-ink">
          {formatCount(row.payment_order_count)}
        </dd>
      </dl>
    </div>
  );
}

export function ChannelSection({
  resource,
}: {
  resource: AnalyticsResource<ChannelMixResponse>;
}) {
  const { data, error, busy, retry } = resource;
  const rows: ChannelRow[] = (data?.channels ?? []).map((channel) => ({
    ...channel,
    label: channelLabel(channel.channel),
  }));

  return (
    <SectionPanel
      title="Channel mix"
      description="How orders reached the business. Online, mixed and unknown are kept distinct — each records a different fact about the order's origin."
      error={error}
      onRetry={retry}
      busy={busy}
      hasData={data !== null}
    >
      {rows.length === 0 ? (
        <EmptyNote>No channels traded in this range.</EmptyNote>
      ) : (
        <div className="flex flex-col gap-4">
          {/*
            Bars, not a donut. The mix is heavily skewed — the smallest channels
            are a fraction of a percent — and as pie slices those are invisible
            slivers that can only be read from the legend. Bar length stays
            readable at any share, and the table below carries the exact
            figures a donut would have hidden.
          */}
          <ChartFrame height={Math.max(140, rows.length * 34 + 40)} label="Net sales by channel">
            <BarChart
              data={rows}
              layout="vertical"
              margin={{ top: 4, right: 12, bottom: 0, left: 0 }}
            >
              <CartesianGrid {...GRID_STYLE} horizontal={false} />
              <XAxis type="number" tickFormatter={formatAxisMoney} {...AXIS_STYLE} />
              <YAxis type="category" dataKey="label" width={82} {...AXIS_STYLE} />
              <Tooltip {...TOOLTIP_STYLE} content={<ChannelTooltip />} />
              <Bar
                dataKey="net_sales_pence"
                fill="var(--color-chart-mark)"
                radius={[0, 3, 3, 0]}
                barSize={16}
                isAnimationActive={false}
              />
            </BarChart>
          </ChartFrame>

          <div className="overflow-x-auto">
            <table className="w-full min-w-[440px] text-[12px]">
              <thead>
                <tr className="border-b border-line text-left text-[11px] uppercase tracking-wider text-ink-subtle">
                  <th scope="col" className="pb-1.5 font-semibold">Channel</th>
                  <th scope="col" className="pb-1.5 text-right font-semibold">Net sales</th>
                  <th scope="col" className="pb-1.5 text-right font-semibold">Share</th>
                  <th scope="col" className="pb-1.5 text-right font-semibold">Orders</th>
                  <th scope="col" className="pb-1.5 text-right font-semibold">Avg order</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((row) => (
                  <tr key={row.channel} className="border-b border-line last:border-0">
                    <th scope="row" className="py-1.5 text-left font-medium text-ink">
                      {row.label}
                    </th>
                    <td className="tabular py-1.5 text-right text-ink">
                      {formatMoneyPence(row.net_sales_pence)}
                    </td>
                    {/* A null share is UNDEFINED, not zero — an em dash, never "0.0%". */}
                    <td className="tabular py-1.5 text-right text-ink-muted">
                      {formatPercent(row.share_of_net_sales_percent, 2)}
                    </td>
                    <td className="tabular py-1.5 text-right text-ink-muted">
                      {formatCount(row.payment_order_count)}
                    </td>
                    <td className="tabular py-1.5 text-right text-ink-muted">
                      {formatMoneyPence(row.average_order_value_pence)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <p className="text-[11px] leading-relaxed text-ink-subtle">
            Shares are rounded to two decimal places and are not adjusted to
            total exactly 100%.
          </p>
        </div>
      )}
    </SectionPanel>
  );
}
