"use client";

import {
  FORECAST_TARGETS,
  HORIZON_OPTIONS,
  clampHorizon,
  horizonLabel,
} from "@/lib/forecast";
import type { ForecastTarget } from "@/lib/api";

/**
 * What to forecast, and how far ahead.
 *
 * The horizon is a SELECT over the fourteen legal values rather than a number
 * input or a slider. Two reasons, both about correctness rather than taste:
 *
 *   * an out-of-range horizon cannot be expressed. A `type="number"` field
 *     with min and max still lets a keyboard produce 99 and a paste produce
 *     "-3", and the only thing standing between that and a 422 is validation
 *     the control should not need;
 *   * one change is one request. A slider fires on every step of a drag, so
 *     dragging 1 -> 14 would start fourteen requests to show one answer.
 */
export function ForecastControls({
  target,
  onTargetChange,
  horizonDays,
  onHorizonChange,
  busy = false,
}: {
  target: ForecastTarget;
  onTargetChange: (next: ForecastTarget) => void;
  horizonDays: number;
  onHorizonChange: (next: number) => void;
  busy?: boolean;
}) {
  return (
    <div className="flex flex-col gap-1.5">
      <div className="flex flex-wrap items-end gap-3">
        <div className="flex min-w-0 flex-col gap-1">
          <span
            id="forecast-target-label"
            className="text-[11px] font-semibold uppercase tracking-wider text-ink-subtle"
          >
            Measure
          </span>
          <div
            role="group"
            aria-labelledby="forecast-target-label"
            className="flex flex-wrap rounded-md border border-line-strong p-0.5"
          >
            {FORECAST_TARGETS.map((option) => (
              <button
                key={option.value}
                type="button"
                onClick={() => onTargetChange(option.value)}
                aria-pressed={target === option.value}
                className={`rounded px-2.5 py-1 text-[12px] font-medium transition-colors ${
                  target === option.value
                    ? "bg-accent-soft text-accent"
                    : "text-ink-muted hover:text-ink"
                }`}
              >
                {option.label}
              </button>
            ))}
          </div>
        </div>

        <div className="flex flex-col gap-1">
          <label
            htmlFor="forecast-horizon"
            className="text-[11px] font-semibold uppercase tracking-wider text-ink-subtle"
          >
            Horizon
          </label>
          <select
            id="forecast-horizon"
            value={horizonDays}
            onChange={(event) =>
              // Clamped rather than trusted. The options below cannot produce
              // anything out of range, so this only ever guards a value that
              // arrived some other way.
              onHorizonChange(clampHorizon(Number(event.target.value)))
            }
            className="tabular h-9 rounded-md border border-line-strong bg-surface px-2.5 text-sm text-ink"
          >
            {HORIZON_OPTIONS.map((days) => (
              <option key={days} value={days}>
                {horizonLabel(days)}
              </option>
            ))}
          </select>
        </div>
      </div>

      {/* Fixed-height status line, always reserved, so starting a request does
          not move the controls. Matches DateRangeControl on the other pages. */}
      <p className="h-4 text-[12px] leading-4 text-ink-subtle">
        {busy ? "Updating…" : ""}
      </p>
    </div>
  );
}
