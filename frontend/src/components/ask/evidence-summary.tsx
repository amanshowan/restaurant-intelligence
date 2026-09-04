import type { EvidenceBundle } from "@/lib/api";
import {
  comparisonPeriodLabel,
  describeWape,
  isForecastBundle,
  operationLabel,
  periodLabel,
  productLabel,
  recordsLabel,
  trainedThroughLabel,
} from "@/lib/ask";

/**
 * What was actually measured to produce the answer.
 *
 * This is the page's accountability surface: an answer a reader cannot check
 * is an answer they have to take on trust, and the whole architecture exists
 * so they do not have to. It is deliberately a SUMMARY rather than the raw
 * bundle — the executor's rows, totals, field provenance and parameters are
 * its own measurement shape, and dumping them would be showing internals, not
 * evidence. What a reader needs is which operation ran, over what period, on
 * how many records, and whether anything was left out.
 *
 * A forecast bundle is marked, dated and given its measured error, because it
 * is the one kind of evidence that is not a record of anything.
 */
export function EvidenceSummary({ evidence }: { evidence: EvidenceBundle[] }) {
  if (evidence.length === 0) return null;

  return (
    <section className="rounded-lg border border-line bg-surface">
      <header className="border-b border-line px-4 py-3">
        <h2 className="text-[13px] font-semibold tracking-tight text-ink">
          What this answer is based on
        </h2>
        <p className="mt-1 max-w-2xl text-[12px] leading-relaxed text-ink-muted">
          The analytics that ran, and what they covered. Every figure above
          comes from these — the answer was written from this evidence and
          nothing else.
        </p>
      </header>

      <ul className="divide-y divide-line">
        {evidence.map((bundle, index) => (
          <EvidenceRow key={`${bundle.operation}-${index}`} bundle={bundle} />
        ))}
      </ul>
    </section>
  );
}

function EvidenceRow({ bundle }: { bundle: EvidenceBundle }) {
  const forecast = bundle.forecast;
  const period = periodLabel(bundle);
  const records = recordsLabel(bundle);
  const comparison = comparisonPeriodLabel(bundle);
  const resolved = bundle.product_resolution?.resolved ?? null;

  return (
    <li className="px-4 py-3">
      <div className="flex flex-wrap items-center gap-x-2.5 gap-y-1.5">
        <span className="text-[13px] font-medium text-ink">
          {operationLabel(bundle.operation)}
        </span>

        {isForecastBundle(bundle) ? (
          <span className="rounded-full bg-accent-soft px-2 py-0.5 text-[11px] font-semibold text-accent">
            Prediction
          </span>
        ) : (
          <span className="rounded-full bg-surface-muted px-2 py-0.5 text-[11px] font-medium text-ink-muted">
            Measured
          </span>
        )}

        {bundle.status !== "ok" && (
          <span className="rounded-full bg-surface-muted px-2 py-0.5 text-[11px] font-medium text-ink-muted">
            {bundle.status === "unknown_product"
              ? "Product not found"
              : bundle.status === "ambiguous_product"
                ? "Product ambiguous"
                : "Not enough history"}
          </span>
        )}
      </div>

      <dl className="mt-1.5 flex flex-wrap gap-x-5 gap-y-1 text-[12px] text-ink-muted">
        {period && (
          <div className="flex gap-1.5">
            <dt className="text-ink-subtle">
              {forecast ? "Predicting" : "Period"}
            </dt>
            <dd>{period}</dd>
          </div>
        )}
        {comparison && (
          <div className="flex gap-1.5">
            <dt className="text-ink-subtle">Compared with</dt>
            <dd>{comparison}</dd>
          </div>
        )}
        {records && (
          <div className="flex gap-1.5">
            <dt className="text-ink-subtle">Records</dt>
            <dd>{records}</dd>
          </div>
        )}
        {resolved && (
          <div className="flex gap-1.5">
            <dt className="text-ink-subtle">Product</dt>
            <dd>{productLabel(resolved)}</dd>
          </div>
        )}
      </dl>

      {forecast && (
        <p className="mt-1.5 text-[12px] leading-relaxed text-ink-muted">
          Real data ends {trainedThroughLabel(forecast)}; everything after it is
          model output. {describeWape(forecast)}
        </p>
      )}
    </li>
  );
}
