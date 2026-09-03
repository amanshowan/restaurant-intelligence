"use client";

import type { ForecastResponse } from "@/lib/api";
import {
  formatDailyError,
  formatWapePercent,
  historicalErrorContext,
  methodLabel,
} from "@/lib/forecast";

/**
 * What this method got wrong, on days it had never seen.
 *
 * The one section on the page a reader is most likely to misread, so the
 * wording is fixed here rather than left to a caller:
 *
 *   * WAPE is labelled "Historical WAPE" and described as ERROR. It is never
 *     inverted — nothing on this page computes `100 - wape`, because
 *     "87.31% accurate" is a claim about the predictions on screen and the
 *     backtest measures something else entirely;
 *   * MAE is given in the unit the business thinks in, per day, because
 *     "17,970" means nothing and "£179.70 per day" is a figure a manager can
 *     weigh against a decision;
 *   * the sentence beneath says how many unseen days those numbers came from,
 *     so the percentage cannot float free of its evidence;
 *   * no interval is shown, and the reason is stated rather than left as an
 *     absence a reader might fill in for themselves.
 */
export function ForecastAccuracy({ data }: { data: ForecastResponse }) {
  return (
    <div className="flex flex-col gap-4">
      <dl className="grid grid-cols-1 gap-4 sm:grid-cols-3">
        <Metric
          label="Historical WAPE"
          value={formatWapePercent(data.historical_wape_percent)}
          hint="Total absolute error as a share of the trade that happened"
        />
        <Metric
          label="Typical daily error"
          value={formatDailyError(data.unit, data.historical_mae)}
          hint="Mean absolute error over the same backtest"
        />
        <Metric
          label="Method"
          value={methodLabel(data.method)}
          hint={`Reported by the API as “${data.method}”`}
          small
        />
      </dl>

      <p className="text-[12px] leading-relaxed text-ink-muted">
        {historicalErrorContext(data)}
      </p>

      <div className="rounded-md border border-line bg-surface-muted px-3 py-2.5 text-[12px] leading-relaxed text-ink-muted">
        <p>
          These are <strong className="font-semibold text-ink">error</strong>{" "}
          measures, not confidence levels. They say how wrong this method has
          been on past days it was not trained on. Subtracting the WAPE from
          100 would not turn it into a measure of how right the predictions
          above are: that is a different claim, about different days, and
          nothing here has measured it.
        </p>
        <p className="mt-2">
          No prediction intervals are shown. Producing one would mean validating
          that it actually contains the outcome as often as it claims, which has
          not been done — and an unchecked range invites more confidence than an
          honest number.
        </p>
      </div>
    </div>
  );
}

function Metric({
  label,
  value,
  hint,
  small = false,
}: {
  label: string;
  value: string;
  hint: string;
  small?: boolean;
}) {
  return (
    <div className="rounded-lg border border-line bg-surface px-4 py-3.5">
      <dt className="text-[11px] font-semibold uppercase tracking-wider text-ink-subtle">
        {label}
      </dt>
      <dd
        className={`tabular mt-1.5 font-semibold tracking-tight text-ink ${
          small ? "text-[13px] leading-5" : "text-[22px] leading-7"
        }`}
      >
        {value}
      </dd>
      <dd className="mt-1 text-[12px] leading-4 text-ink-subtle">{hint}</dd>
    </div>
  );
}
