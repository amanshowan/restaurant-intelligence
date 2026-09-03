"use client";

import { useRef, useState } from "react";

import { PageHeader } from "@/components/page-header";
import { SectionPanel } from "@/components/section-panel";
import {
  ApiError,
  importSquareExport,
  isBackendUnavailable,
  type ImportSummary,
} from "@/lib/api";
import {
  FILE_SLOTS,
  IMPORT_ERROR_GUIDANCE,
  MAX_LABEL_LENGTH,
  formatBytes,
  importErrorHeading,
  totalBytes,
  validateImportForm,
  type FileSlot as FileSlotName,
  type SelectedFiles,
} from "@/lib/imports";

import { FileSlot } from "./file-slot";
import { ImportResult } from "./import-result";

/**
 * The workflow's states.
 *
 * `uploading` is deliberately indeterminate. `fetch` reports no upload
 * progress without switching to XMLHttpRequest, and a fabricated percentage
 * that jumps to 90% and waits is worse than an honest "Importing…".
 */
type Phase = "editing" | "uploading" | "succeeded";

export function ImportsDashboard() {
  const [files, setFiles] = useState<SelectedFiles>({});
  const [label, setLabel] = useState("");
  const [phase, setPhase] = useState<Phase>("editing");
  const [result, setResult] = useState<ImportSummary | null>(null);
  const [error, setError] = useState<ApiError | null>(null);

  // Guards against a double submit that a disabled attribute alone would miss
  // — a second submit event can be dispatched before React has re-rendered.
  const inFlight = useRef(false);

  const validationError = validateImportForm(files, label);
  const uploading = phase === "uploading";
  const canSubmit = validationError === null && !uploading;

  function setSlot(slot: FileSlotName, file: File | undefined) {
    setFiles((current) => {
      const next = { ...current };
      if (file) next[slot] = file;
      else delete next[slot];
      return next;
    });
    // A new selection invalidates the previous attempt's outcome.
    setError(null);
  }

  async function submit() {
    if (inFlight.current) return;
    if (validationError !== null) return;
    if (!files.transactions || !files.items) return;

    inFlight.current = true;
    setPhase("uploading");
    setError(null);

    try {
      const summary = await importSquareExport({
        transactions: files.transactions,
        items: files.items,
        summary: files.summary ?? null,
        label,
      });
      setResult(summary);
      setPhase("succeeded");
    } catch (caught) {
      setError(
        caught instanceof ApiError
          ? caught
          : new ApiError({
              status: 0,
              code: "unexpected_error",
              detail: "Something went wrong starting the import.",
            }),
      );
      setPhase("editing");
    } finally {
      inFlight.current = false;
    }
  }

  function reset() {
    setFiles({});
    setLabel("");
    setResult(null);
    setError(null);
    setPhase("editing");
  }

  return (
    <>
      <PageHeader
        title="Imports"
        description="Upload a Square export set. The files are validated, ingested and reconciled against Square's own totals by the API — nothing is parsed in the browser."
      />

      <div className="flex max-w-3xl flex-col gap-4">
        {phase === "succeeded" && result ? (
          <SectionPanel
            title="Import complete"
            description="What the API recorded, and how it reconciled."
            hasData
          >
            <ImportResult summary={result} onImportAnother={reset} />
          </SectionPanel>
        ) : (
          <SectionPanel
            title="Square export set"
            description="Square exports three files. Two are required; the third turns on reconciliation."
            hasData
            busy={uploading}
          >
            <form
              onSubmit={(event) => {
                event.preventDefault();
                void submit();
              }}
              className="flex flex-col gap-4"
            >
              <p className="rounded-md border border-line bg-surface-muted px-3 py-2 text-[11px] leading-relaxed text-ink-muted">
                Square names its exports <code>.csv</code>, but they are UTF-16
                and tab-delimited. Upload them exactly as Square produced them —
                a file opened and re-saved in a spreadsheet is no longer in that
                format and will be rejected. Coverage dates are read from the
                file contents, never from the filename.
              </p>

              <fieldset disabled={uploading} className="flex flex-col gap-3">
                <legend className="sr-only">Square export files</legend>
                {FILE_SLOTS.map((definition) => (
                  <FileSlot
                    key={definition.slot}
                    definition={definition}
                    file={files[definition.slot]}
                    onSelect={(file) => setSlot(definition.slot, file)}
                    onClear={() => setSlot(definition.slot, undefined)}
                    disabled={uploading}
                  />
                ))}
              </fieldset>

              <div className="flex flex-col gap-1">
                <label
                  htmlFor="import-label"
                  className="text-[11px] font-semibold uppercase tracking-wider text-ink-subtle"
                >
                  Label <span className="font-normal normal-case">(optional)</span>
                </label>
                <input
                  id="import-label"
                  type="text"
                  value={label}
                  maxLength={MAX_LABEL_LENGTH}
                  disabled={uploading}
                  onChange={(event) => setLabel(event.target.value)}
                  placeholder="august-2026"
                  className="h-9 w-full max-w-xs rounded-md border border-line-strong bg-surface px-2.5 text-sm text-ink disabled:opacity-50"
                />
                <p className="text-[11px] text-ink-subtle">
                  A name for this batch, to identify it later.
                </p>
              </div>

              {error && <ImportError error={error} />}

              <div className="flex flex-wrap items-center gap-3 border-t border-line pt-4">
                <button
                  type="submit"
                  disabled={!canSubmit}
                  className="h-9 rounded-md bg-accent px-4 text-sm font-medium text-white hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-40"
                >
                  {uploading ? "Importing…" : "Import"}
                </button>

                {/* role="status" so the outcome of pressing Import is
                    announced, not only shown. */}
                <p role="status" className="text-[12px] text-ink-muted">
                  {uploading
                    ? "Uploading and reconciling. This can take a moment for a full month."
                    : (validationError ?? `${formatBytes(totalBytes(files))} ready to upload.`)}
                </p>
              </div>
            </form>
          </SectionPanel>
        )}
      </div>
    </>
  );
}

/**
 * A failed import, in the operator's terms.
 *
 * The heading names the situation; the backend's own `detail` is shown beneath
 * because it is written for a human and carries no internals; the guidance says
 * what to do about it. The stable `code` is kept visible — it is the thing
 * worth quoting.
 */
function ImportError({ error }: { error: ApiError }) {
  const unreachable = isBackendUnavailable(error);
  const heading = unreachable
    ? "Cannot reach the API"
    : importErrorHeading(error.code);
  const guidance = IMPORT_ERROR_GUIDANCE[error.code];

  return (
    <div
      role="alert"
      className="rounded-md border border-line bg-surface p-3"
    >
      <div className="flex items-start gap-3">
        <span
          aria-hidden
          className="mt-0.5 grid h-5 w-5 shrink-0 place-items-center rounded-full bg-negative text-[11px] font-bold text-white"
        >
          !
        </span>
        <div className="min-w-0">
          <h3 className="text-[13px] font-semibold text-ink">{heading}</h3>
          <p className="mt-1 text-[12px] leading-relaxed text-ink-muted">
            {error.detail}
          </p>
          {guidance && (
            <p className="mt-2 text-[11px] leading-relaxed text-ink-subtle">
              {guidance}
            </p>
          )}
          {error.issues.length > 0 && (
            <ul className="mt-2 flex flex-col gap-1">
              {error.issues.map((issue, index) => (
                <li
                  key={`${issue.location}-${index}`}
                  className="font-mono text-[11px] text-ink-muted"
                >
                  {issue.location}: {issue.message}
                </li>
              ))}
            </ul>
          )}
          <p className="mt-2 font-mono text-[11px] text-ink-subtle">
            {error.code}
            {error.status > 0 ? ` · HTTP ${error.status}` : ""}
          </p>
        </div>
      </div>
    </div>
  );
}
