"use client";

import { ResponsiveContainer } from "recharts";

/**
 * A fixed-height, width-responsive box for a Recharts chart.
 *
 * The height is explicit and the container never shrinks below it, which is
 * what keeps the page from reflowing as data arrives, and what stops
 * ResponsiveContainer collapsing to zero height inside a flex parent — the
 * single most common way a Recharts chart renders as nothing at all.
 */
export function ChartFrame({
  height,
  label,
  children,
}: {
  height: number;
  /** Describes the chart for anyone who cannot see it. */
  label: string;
  children: React.ReactElement;
}) {
  return (
    <div style={{ height }} role="img" aria-label={label}>
      <ResponsiveContainer width="100%" height="100%">
        {children}
      </ResponsiveContainer>
    </div>
  );
}

/** Shared Recharts styling, so every chart on the page is drawn the same way. */
export const AXIS_STYLE = {
  tick: { fontSize: 11, fill: "var(--color-chart-axis)" },
  axisLine: false as const,
  tickLine: false as const,
};

export const GRID_STYLE = {
  stroke: "var(--color-chart-grid)",
  strokeDasharray: "0",
};

/** Tooltip chrome. Recharts styles its own wrapper, so this is passed through. */
export const TOOLTIP_STYLE = {
  contentStyle: {
    borderRadius: 6,
    border: "1px solid var(--color-line)",
    boxShadow: "0 2px 8px rgb(18 24 32 / 0.08)",
    padding: "8px 10px",
    fontSize: 12,
  },
  cursor: { fill: "var(--color-chart-grid)" },
};
