"use client";

import { useId, useRef } from "react";

import { formatBytes, type SlotDefinition } from "@/lib/imports";

/**
 * One file slot: what it is, whether it is required, and what is chosen.
 *
 * A native `<input type="file">` behind a label rather than a drag-and-drop
 * surface. It is keyboard reachable, works on a phone, opens the platform file
 * picker everyone already knows, and needs no drag-state handling to get right.
 * The input itself is visually hidden but never `display: none`, which would
 * take it out of the tab order.
 */
export function FileSlot({
  definition,
  file,
  onSelect,
  onClear,
  disabled,
}: {
  definition: SlotDefinition;
  file: File | undefined;
  onSelect: (file: File) => void;
  onClear: () => void;
  disabled: boolean;
}) {
  const inputId = useId();
  const inputRef = useRef<HTMLInputElement>(null);

  return (
    <div className="rounded-md border border-line bg-surface-muted p-3">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <label
            htmlFor={inputId}
            className="text-[12px] font-semibold text-ink"
          >
            {definition.label}
          </label>
          <span
            className={`ml-2 text-[10px] font-medium uppercase tracking-wider ${
              definition.required ? "text-accent" : "text-ink-subtle"
            }`}
          >
            {definition.required ? "Required" : "Optional"}
          </span>
          <p className="mt-1 max-w-md text-[11px] leading-relaxed text-ink-muted">
            {definition.description}
          </p>
        </div>

        <div className="flex shrink-0 items-center gap-2">
          <button
            type="button"
            onClick={() => inputRef.current?.click()}
            disabled={disabled}
            className="h-8 rounded-md border border-line-strong bg-surface px-3 text-[12px] font-medium text-ink hover:bg-surface-muted disabled:cursor-not-allowed disabled:opacity-50"
          >
            {file ? "Replace" : "Choose file"}
          </button>
          {file && (
            <button
              type="button"
              onClick={onClear}
              disabled={disabled}
              className="h-8 rounded-md px-2 text-[12px] font-medium text-ink-muted hover:text-ink disabled:cursor-not-allowed disabled:opacity-50"
            >
              Remove
            </button>
          )}
        </div>
      </div>

      <input
        id={inputId}
        ref={inputRef}
        type="file"
        // Square names its exports .csv even though they are UTF-16 and
        // tab-delimited. A hint only — the server decides what is valid.
        accept=".csv,text/csv"
        disabled={disabled}
        onChange={(event) => {
          const chosen = event.target.files?.[0];
          if (chosen) onSelect(chosen);
          // Reset, so choosing the SAME file again after removing it still
          // fires a change event.
          event.target.value = "";
        }}
        className="sr-only"
      />

      <div className="mt-2 min-h-[20px]">
        {file ? (
          <p className="flex flex-wrap items-baseline gap-x-2 text-[12px]">
            {/* break-all: export filenames are long and unbroken, and would
                otherwise push the panel wider than the viewport. */}
            <span className="break-all font-medium text-ink">{file.name}</span>
            <span className="tabular text-[11px] text-ink-subtle">
              {formatBytes(file.size)}
            </span>
          </p>
        ) : (
          <p className="text-[11px] text-ink-subtle">
            {definition.required ? "No file chosen yet." : "Not supplied."}
          </p>
        )}
      </div>
    </div>
  );
}
