"use client";

import type { ForecastUnit } from "@/lib/api";
import { formatForecastValue, type ForecastChartPoint } from "@/lib/forecast";
import { formatLongDate } from "@/lib/format";

/**
 * The same fourteen numbers, readable one at a time.
 *
 * The chart shows the shape; a rota or an order is written against a
 * particular Tuesday, and reading an exact figure off a line is guesswork. The
 * weekday is spelled out because the model's dominant signal is day of week,
 * so it is the column that explains the shape.
 */
export function ForecastTable({
  points,
  unit,
  measure,
}: {
  points: ForecastChartPoint[];
  unit: ForecastUnit;
  measure: string;
}) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[280px] border-collapse text-[12px]">
        <caption className="sr-only">
          Predicted daily {measure}, one row per forecast day
        </caption>
        <thead>
          <tr className="border-b border-line">
            <th
              scope="col"
              className="pb-1.5 text-left text-[11px] font-semibold uppercase tracking-wider text-ink-subtle"
            >
              Day
            </th>
            <th
              scope="col"
              className="pb-1.5 text-right text-[11px] font-semibold uppercase tracking-wider text-ink-subtle"
            >
              Predicted {measure}
            </th>
          </tr>
        </thead>
        <tbody>
          {points.map((point) => (
            <tr key={point.date} className="border-b border-line last:border-0">
              <th
                scope="row"
                className="py-1.5 text-left font-normal text-ink-muted"
              >
                {formatLongDate(point.date)}
              </th>
              <td className="tabular py-1.5 text-right font-medium text-ink">
                {formatForecastValue(unit, point.predictedValue)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
