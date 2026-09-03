/**
 * Client-side rules for the Square import form.
 *
 * Deliberately shallow. The backend asserts Square's actual format — UTF-16,
 * tab-delimited, the exact column set — derives the coverage period from the
 * file contents, and reconciles the result against Square's own totals. None
 * of that is repeated here: a second implementation in TypeScript could only
 * disagree with the one that actually writes the data.
 *
 * What this covers is what the browser can know without opening a file: is a
 * required slot filled, is the file plausibly within the size the server will
 * accept, is the label within the column it is stored in. Everything else is
 * the server's answer to give.
 */

import type { ImportSummary } from "./api";

/** Mirrors MAX_FILE_BYTES in backend/app/api/imports.py. */
export const MAX_FILE_BYTES = 64 * 1024 * 1024;
/** Mirrors MAX_REQUEST_BYTES — the ceiling across all files in one request. */
export const MAX_REQUEST_BYTES = 160 * 1024 * 1024;
/** Mirrors MAX_LABEL_LENGTH; `import_batches.label` is bounded in the schema. */
export const MAX_LABEL_LENGTH = 255;

export type FileSlot = "transactions" | "items" | "summary";

export interface SlotDefinition {
  slot: FileSlot;
  label: string;
  required: boolean;
  description: string;
}

/**
 * The three parts of one logical Square import.
 *
 * Square exports these separately and they are only meaningful together: the
 * transactions file carries the money, the items file the lines, and the
 * summary exists purely so the import can be checked against Square's own
 * arithmetic.
 */
export const FILE_SLOTS: readonly SlotDefinition[] = [
  {
    slot: "transactions",
    label: "Transactions",
    required: true,
    description: "Order-level export. Carries the money and the payment events.",
  },
  {
    slot: "items",
    label: "Items Detail",
    required: true,
    description: "Line-level export. Carries what was actually sold.",
  },
  {
    slot: "summary",
    label: "Items Summary",
    required: false,
    description:
      "Optional. Used only to reconcile the import against Square's own totals — supplying it turns the check on.",
  },
];

export type SelectedFiles = Partial<Record<FileSlot, File>>;

/**
 * Why the form cannot be submitted, or null when it can.
 *
 * One message at a time, in the order an operator would fix them, rather than
 * a list that mostly repeats "choose a file".
 */
export function validateImportForm(
  files: SelectedFiles,
  label: string,
): string | null {
  if (!files.transactions) return "Choose a Transactions export.";
  if (!files.items) return "Choose an Items Detail export.";

  for (const definition of FILE_SLOTS) {
    const file = files[definition.slot];
    if (file && file.size > MAX_FILE_BYTES) {
      return `${definition.label} is larger than the ${formatBytes(MAX_FILE_BYTES)} limit for a single file.`;
    }
    if (file && file.size === 0) {
      return `${definition.label} is empty.`;
    }
  }

  if (totalBytes(files) > MAX_REQUEST_BYTES) {
    return `The selected files total more than the ${formatBytes(MAX_REQUEST_BYTES)} limit for one import.`;
  }

  if (label.trim().length > MAX_LABEL_LENGTH) {
    return `The label must be ${MAX_LABEL_LENGTH} characters or fewer.`;
  }

  return null;
}

export function totalBytes(files: SelectedFiles): number {
  return FILE_SLOTS.reduce(
    (total, definition) => total + (files[definition.slot]?.size ?? 0),
    0,
  );
}

/** A byte count as a short human string: `10.4 MB`. */
export function formatBytes(bytes: number): string {
  if (!Number.isFinite(bytes) || bytes < 0) return "—";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} kB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

/**
 * Operator-facing wording for the failures the import endpoint actually
 * returns.
 *
 * The backend's own `detail` is shown alongside — it is written for a human and
 * carries no stack trace, SQL or row content — but the heading names the
 * situation in the terms an operator thinks in.
 */
export const IMPORT_ERROR_HEADINGS: Record<string, string> = {
  duplicate_file: "These files have already been imported",
  conflicting_order: "An order conflicts with one already stored",
  invalid_source_file: "That is not a valid Square export",
  reconciliation_failed: "The totals did not reconcile with Square",
  import_failed: "The import could not be completed",
  invalid_request: "The request was rejected",
  validation_error: "A required file was missing",
  internal_error: "The server could not complete the import",
};

/** What an operator can usefully DO about each failure. */
export const IMPORT_ERROR_GUIDANCE: Record<string, string> = {
  duplicate_file:
    "Every uploaded file is checksummed, so the same export cannot be counted twice. Nothing was written. Choose a different period's files, or re-export from Square if the data has changed.",
  conflicting_order:
    "An order in these files differs from the version already stored, so the whole import was rolled back rather than leaving data that matches no source file.",
  invalid_source_file:
    "Square names its exports .csv, but they are UTF-16 and tab-delimited. A file re-saved through a spreadsheet is no longer in that format — export it again from Square without opening it.",
  reconciliation_failed:
    "The imported totals did not match the Items Summary, so nothing was written. Check that all three files cover the same period and came from the same export.",
  validation_error:
    "Both the Transactions and Items Detail exports are required.",
};

export function importErrorHeading(code: string): string {
  return IMPORT_ERROR_HEADINGS[code] ?? "The import failed";
}

/**
 * Whether the result may be described as reconciled.
 *
 * `performed` is false when no Items Summary was supplied, and `matches` is
 * then meaningless — reading it as a pass would claim a check that never ran.
 */
export function wasReconciled(summary: ImportSummary): boolean {
  return summary.reconciliation.performed;
}

/** Row-level outcome codes as readable phrases. */
export const ISSUE_LABELS: Record<string, string> = {
  zero_value_transaction: "Zero-value transactions skipped",
  refund_channel_inherited: "Refunds whose channel was inherited",
  unparsable_row: "Rows that could not be parsed",
  missing_transaction: "Item rows with no matching transaction",
};

export function issueLabel(code: string): string {
  return (
    ISSUE_LABELS[code] ??
    // An unknown code is shown as-is rather than hidden: a new row outcome the
    // UI has not been taught about is still a fact about the import.
    code.replace(/_/g, " ").replace(/^./, (c) => c.toUpperCase())
  );
}
