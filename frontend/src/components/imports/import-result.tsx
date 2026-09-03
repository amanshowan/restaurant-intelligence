"use client";

import Link from "next/link";

import type { ImportSummary } from "@/lib/api";
import { issueLabel, wasReconciled } from "@/lib/imports";
import {
  formatCount,
  formatDateRangeLabel,
  formatMoneyPence,
} from "@/lib/format";

/**
 * What a completed import actually did.
 *
 * Reports the backend's own figures. The reconciliation block appears ONLY
 * when a summary was supplied and the check therefore ran — claiming a match
 * that was never performed would be the single most misleading thing this
 * screen could do.
 */
export function ImportResult({
  summary,
  onImportAnother,
}: {
  summary: ImportSummary;
  onImportAnother: () => void;
}) {
  const reconciled = wasReconciled(summary);
  const { reconciliation } = summary;
  const issues = Object.entries(summary.issue_counts);

  return (
    <div className="flex flex-col gap-5">
      <div className="flex items-start gap-3 rounded-md border border-line bg-surface-muted p-3">
        <span
          aria-hidden
          className="mt-0.5 grid h-5 w-5 shrink-0 place-items-center rounded-full bg-positive text-[11px] font-bold text-white"
        >
          ✓
        </span>
        <div className="min-w-0">
          <h3 className="text-[13px] font-semibold text-ink">
            Import {summary.status}
          </h3>
          <p className="mt-0.5 text-[12px] text-ink-muted">
            Batch #{summary.batch_id}
            {summary.label ? ` · ${summary.label}` : ""}
            {summary.period_start && summary.period_end
              ? ` · ${formatDateRangeLabel(summary.period_start, summary.period_end)}`
              : ""}
          </p>
        </div>
      </div>

      <dl className="grid grid-cols-2 gap-x-6 gap-y-3 sm:grid-cols-3">
        <Figure label="Net sales" value={formatMoneyPence(summary.net_sales_pence)} />
        <Figure label="Orders imported" value={formatCount(summary.orders_imported)} />
        <Figure
          label="Order items"
          value={formatCount(summary.order_items_imported)}
        />
        <Figure
          label="Products created"
          value={formatCount(summary.products_created)}
          hint={`${formatCount(summary.products_reused)} reused`}
        />
        <Figure label="Rows skipped" value={formatCount(summary.rows_skipped)} />
        <Figure
          label="Period"
          value={
            summary.period_start && summary.period_end
              ? formatDateRangeLabel(summary.period_start, summary.period_end)
              : "—"
          }
          hint="derived from the file contents"
        />
      </dl>

      {/* --- reconciliation --- */}
      <section className="rounded-md border border-line p-3">
        <h3 className="text-[12px] font-semibold text-ink">Reconciliation</h3>
        {reconciled ? (
          <>
            <p className="mt-1 text-[11px] leading-relaxed text-ink-muted">
              Checked against the Items Summary you supplied. An import whose
              totals disagree with Square is rejected, not recorded.
            </p>
            <table className="mt-2.5 w-full text-[12px]">
              <thead>
                <tr className="border-b border-line text-left text-[11px] uppercase tracking-wider text-ink-subtle">
                  <th scope="col" className="pb-1.5 font-semibold">Measure</th>
                  <th scope="col" className="pb-1.5 text-right font-semibold">Imported</th>
                  <th scope="col" className="pb-1.5 text-right font-semibold">Square</th>
                  <th scope="col" className="pb-1.5 text-right font-semibold">Match</th>
                </tr>
              </thead>
              <tbody>
                <ReconRow
                  label="Net sales"
                  ours={formatMoneyPence(reconciliation.net_sales_pence_ours)}
                  theirs={formatMoneyPence(reconciliation.net_sales_pence_theirs)}
                  matches={
                    reconciliation.net_sales_pence_ours ===
                    reconciliation.net_sales_pence_theirs
                  }
                />
                <ReconRow
                  label="Line totals"
                  ours={formatMoneyPence(reconciliation.line_totals_pence_ours)}
                  theirs={formatMoneyPence(reconciliation.line_totals_pence_theirs)}
                  matches={
                    reconciliation.line_totals_pence_ours ===
                    reconciliation.line_totals_pence_theirs
                  }
                />
                <ReconRow
                  label="Units"
                  ours={formatCount(reconciliation.units_ours)}
                  theirs={formatCount(reconciliation.units_theirs)}
                  matches={reconciliation.units_ours === reconciliation.units_theirs}
                />
              </tbody>
            </table>
            <p className="mt-2 text-[12px]">
              <span className="font-medium text-ink">Overall: </span>
              <span
                className={
                  reconciliation.matches ? "text-positive" : "text-negative"
                }
              >
                {/* Word, not colour alone. */}
                {reconciliation.matches ? "Matched" : "Did not match"}
              </span>
            </p>
          </>
        ) : (
          <p className="mt-1 text-[11px] leading-relaxed text-ink-muted">
            <span className="font-medium text-ink">Not performed.</span> No Items
            Summary was supplied, so the import was not checked against Square&rsquo;s
            own totals. The data was still imported.
          </p>
        )}
      </section>

      {/* --- row-level outcomes --- */}
      {issues.length > 0 && (
        <section>
          <h3 className="text-[12px] font-semibold text-ink">Row outcomes</h3>
          <p className="mt-1 text-[11px] text-ink-muted">
            Counted, not silently dropped.
          </p>
          <ul className="mt-2 flex flex-col gap-1">
            {issues.map(([code, count]) => (
              <li
                key={code}
                className="flex items-baseline justify-between gap-4 border-b border-line pb-1 text-[12px] last:border-0"
              >
                <span className="text-ink-muted">{issueLabel(code)}</span>
                <span className="tabular font-medium text-ink">
                  {formatCount(count)}
                </span>
              </li>
            ))}
          </ul>
        </section>
      )}

      {/* --- what next --- */}
      <div className="flex flex-wrap items-center gap-2 border-t border-line pt-4">
        <p className="mr-auto max-w-md text-[11px] leading-relaxed text-ink-subtle">
          The analytics pages read the database on each visit, so this data is
          available now. Set their date range to{" "}
          {summary.period_start && summary.period_end
            ? formatDateRangeLabel(summary.period_start, summary.period_end)
            : "the imported period"}{" "}
          to see it — they open on the last complete calendar month, which may
          not include it.
        </p>
        <Link
          href="/"
          className="h-8 rounded-md bg-accent px-3 text-[12px] font-medium leading-8 text-white hover:opacity-90"
        >
          View Overview
        </Link>
        <Link
          href="/trading"
          className="h-8 rounded-md border border-line-strong bg-surface px-3 text-[12px] font-medium leading-8 text-ink hover:bg-surface-muted"
        >
          View Trading
        </Link>
        <button
          type="button"
          onClick={onImportAnother}
          className="h-8 rounded-md px-3 text-[12px] font-medium text-ink-muted hover:text-ink"
        >
          Import another
        </button>
      </div>
    </div>
  );
}

function ReconRow({
  label,
  ours,
  theirs,
  matches,
}: {
  label: string;
  ours: string;
  theirs: string;
  matches: boolean;
}) {
  return (
    <tr className="border-b border-line last:border-0">
      <th scope="row" className="py-1.5 text-left font-medium text-ink">
        {label}
      </th>
      <td className="tabular py-1.5 text-right text-ink">{ours}</td>
      <td className="tabular py-1.5 text-right text-ink-muted">{theirs}</td>
      <td className="py-1.5 text-right">
        <span className={matches ? "text-positive" : "text-negative"}>
          {matches ? "Yes" : "No"}
        </span>
      </td>
    </tr>
  );
}

function Figure({
  label,
  value,
  hint,
}: {
  label: string;
  value: string;
  hint?: string;
}) {
  return (
    <div className="min-w-0">
      <dt className="text-[11px] font-semibold uppercase tracking-wider text-ink-subtle">
        {label}
      </dt>
      <dd className="tabular mt-0.5 truncate text-[13px] font-semibold text-ink">
        {value}
      </dd>
      {hint && <dd className="text-[11px] text-ink-subtle">{hint}</dd>}
    </div>
  );
}
