"use client";

import {
  CartesianGrid,
  ReferenceLine,
  Scatter,
  ScatterChart,
  Tooltip,
  XAxis,
  YAxis,
  ZAxis,
} from "recharts";

import {
  AXIS_STYLE,
  ChartFrame,
  GRID_STYLE,
  TOOLTIP_STYLE,
} from "@/components/charts/chart-frame";
import { EmptyNote } from "@/components/empty-note";
import type { ProductPairsResponse } from "@/lib/api";
import { pairScatterPoints, type PairScatterPoint } from "@/lib/baskets";
import { formatCount, formatMultiplier, formatPercent } from "@/lib/format";

function ScatterTooltip({
  active,
  payload,
}: {
  active?: boolean;
  payload?: { payload: PairScatterPoint }[];
}) {
  if (!active || !payload?.length) return null;
  const point = payload[0].payload;

  return (
    <div className="max-w-[240px] rounded-md border border-line bg-surface px-3 py-2 text-[12px] shadow-sm">
      <p className="font-semibold text-ink">{point.labelA}</p>
      <p className="font-semibold text-ink">+ {point.labelB}</p>
      <dl className="mt-1.5 grid grid-cols-[auto_auto] gap-x-4 gap-y-0.5">
        <dt className="text-ink-muted">Pair orders</dt>
        <dd className="tabular text-right font-medium text-ink">
          {formatCount(point.pairOrders)}
        </dd>
        <dt className="text-ink-muted">Lift</dt>
        <dd className="tabular text-right font-medium text-ink">
          {formatMultiplier(point.lift)}
        </dd>
        <dt className="text-ink-muted">Support</dt>
        <dd className="tabular text-right font-medium text-ink">
          {formatPercent(point.supportPercent, 2)}
        </dd>
      </dl>
    </div>
  );
}

/**
 * Co-occurrence count against lift.
 *
 * The two axes together are the point. Lift alone rewards rarity — two items
 * bought together twice and never apart score enormously — so plotting it
 * against how often the pair was ACTUALLY observed separates associations that
 * are strong and real from those that are strong and thin. Points to the right
 * are well evidenced; points high up are unusually associated; the interesting
 * ones are both.
 *
 * One accent hue, no categorical colour: every point is the same kind of thing,
 * and the axes already carry both measures.
 */
export function PairScatter({ pairs }: { pairs: ProductPairsResponse }) {
  const points = pairScatterPoints(pairs);

  if (points.length === 0) {
    return <EmptyNote>No pair has a defined lift in this range.</EmptyNote>;
  }

  return (
    <div className="flex flex-col gap-2">
      <ChartFrame height={260} label="Pair order count against lift">
        <ScatterChart margin={{ top: 8, right: 20, bottom: 18, left: 0 }}>
          <CartesianGrid {...GRID_STYLE} />
          <XAxis
            type="number"
            dataKey="pairOrders"
            name="Pair orders"
            {...AXIS_STYLE}
            label={{
              value: "Pair orders",
              position: "insideBottom",
              offset: -12,
              style: { fontSize: 11, fill: "var(--color-chart-axis)" },
            }}
          />
          <YAxis
            type="number"
            dataKey="lift"
            name="Lift"
            width={46}
            tickFormatter={(value: number) => `${value.toFixed(1)}×`}
            {...AXIS_STYLE}
          />
          {/* Fixed point size: a third encoded measure would compete with the
              two the axes already carry. */}
          <ZAxis range={[36, 36]} />
          {/*
            Independence. Above this line the pair occurs more often than the
            two products' individual popularity predicts; below it, less.
          */}
          <ReferenceLine
            y={1}
            stroke="var(--color-line-strong)"
            strokeDasharray="3 3"
            label={{
              value: "independence (1.0×)",
              position: "insideTopRight",
              style: { fontSize: 10, fill: "var(--color-ink-subtle)" },
            }}
          />
          <Tooltip {...TOOLTIP_STYLE} cursor={{ strokeDasharray: "3 3" }} content={<ScatterTooltip />} />
          <Scatter
            data={points}
            fill="var(--color-chart-mark)"
            fillOpacity={0.55}
            isAnimationActive={false}
          />
        </ScatterChart>
      </ChartFrame>

      <p className="text-[11px] leading-relaxed text-ink-subtle">
        Each point is one unordered pair. Further right means the pairing was
        observed more often; higher means it occurs more than independence
        predicts. A high point on the far left is weak evidence, however large
        its lift.
      </p>
    </div>
  );
}
