"use client";

import type { DateRange } from "@/lib/date-range";

/**
 * The date scope for a page.
 *
 * Native `<input type="date">` rather than a custom picker: it is keyboard
 * accessible, localised and touch-friendly for free, and it emits exactly the
 * ISO `yyyy-mm-dd` the API takes, so no parsing sits between the control and
 * the request. A bespoke calendar would be a lot of code to arrive back here.
 */
export function DateRangeControl({
  value,
  onChange,
  error,
  busy = false,
}: {
  value: DateRange;
  onChange: (next: DateRange) => void;
  /** Why the current range cannot be requested, if it cannot. */
  error?: string | null;
  busy?: boolean;
}) {
  const invalid = Boolean(error);

  const inputClass = [
    "tabular h-9 rounded-md border bg-surface px-2.5 text-sm text-ink",
    invalid ? "border-negative" : "border-line-strong",
  ].join(" ");

  return (
    <div className="flex flex-col gap-1.5">
      <div className="flex flex-wrap items-end gap-3">
        <div className="flex flex-col gap-1">
          <label
            htmlFor="range-start"
            className="text-[11px] font-semibold uppercase tracking-wider text-ink-subtle"
          >
            From
          </label>
          <input
            id="range-start"
            type="date"
            className={inputClass}
            value={value.startDate}
            aria-invalid={invalid}
            aria-describedby={invalid ? "range-error" : undefined}
            onChange={(event) =>
              onChange({ ...value, startDate: event.target.value })
            }
          />
        </div>

        <div className="flex flex-col gap-1">
          <label
            htmlFor="range-end"
            className="text-[11px] font-semibold uppercase tracking-wider text-ink-subtle"
          >
            To
          </label>
          <input
            id="range-end"
            type="date"
            className={inputClass}
            value={value.endDate}
            aria-invalid={invalid}
            aria-describedby={invalid ? "range-error" : undefined}
            onChange={(event) =>
              onChange({ ...value, endDate: event.target.value })
            }
          />
        </div>

      </div>

      {/*
        One status line, of a fixed height that is always reserved. A slot that
        appears only when occupied moves everything below it every time a
        request starts. Kept out of the input row because at phone widths the
        two date fields already fill it, and a third item wraps onto a line of
        its own.

        role="alert" only while there IS an error, so a validation message is
        announced the moment it appears — while "Updating…" is not read out on
        every keystroke.
      */}
      <p
        id="range-error"
        role={error ? "alert" : undefined}
        className={`h-4 text-[12px] leading-4 ${
          error ? "text-negative" : "text-ink-subtle"
        }`}
      >
        {error ?? (busy ? "Updating…" : "")}
      </p>
    </div>
  );
}
