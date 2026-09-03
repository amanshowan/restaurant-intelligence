"use client";

import { useCallback, useState } from "react";

import { ErrorPanel } from "@/components/error-panel";
import { PageHeader } from "@/components/page-header";
import { SectionPanel } from "@/components/section-panel";
import { StatCard } from "@/components/stat-card";
import { getForecast, type ForecastResponse, type ForecastTarget } from "@/lib/api";
import {
  DEFAULT_HORIZON_DAYS,
  DEFAULT_TARGET,
  forecastChartPoints,
  forecastTotal,
  formatForecastValue,
  horizonLabel,
  targetOption,
} from "@/lib/forecast";
import { formatDateRangeLabel, formatIsoDate } from "@/lib/format";
import { useAnalyticsResource } from "@/lib/use-analytics-resource";

import { ForecastAccuracy } from "./forecast-accuracy";
import { ForecastChart } from "./forecast-chart";
import { ForecastControls } from "./forecast-controls";
import { ForecastTable } from "./forecast-table";

/** The backend's code for "there is not enough history to forecast from". */
const INSUFFICIENT_HISTORY = "insufficient_history";

/**
 * The Forecast page.
 *
 * ONE request for the whole page, re-issued when the measure or the horizon
 * changes and at no other time. The endpoint returns the entire horizon from a
 * single recursive pass, so there is nothing to fetch per point — and fetching
 * per point would be wrong as well as slow, since day 8 is predicted from
 * day 1's prediction.
 *
 * The page states in three places that these are predictions: a banner under
 * the header, the "Predicted" label on every figure, and a section devoted to
 * the error this method has actually made. That is not over-labelling. Every
 * other page in this dashboard reports what happened, and a chart that looks
 * like those and means something different is the failure mode worth spending
 * screen space on.
 */
export function ForecastDashboard() {
  const [target, setTarget] = useState<ForecastTarget>(DEFAULT_TARGET);
  const [horizonDays, setHorizonDays] = useState(DEFAULT_HORIZON_DAYS);

  // TWO options, deliberately. `selected` is what the control says; `shown` is
  // what the DATA on screen actually is. They differ for as long as a target
  // switch is in flight, because the hook keeps the previous response visible
  // while the new one loads — and labelling last request's order counts
  // "Predicted net sales" would be exactly the kind of confident wrongness
  // this page exists to avoid. Every caption, heading and unit below is taken
  // from the response, so the words and the numbers can never disagree.
  const selected = targetOption(target);

  // The key carries both inputs, so changing either issues exactly one new
  // request and the previous one is aborted by the hook.
  const forecast = useAnalyticsResource<ForecastResponse>(
    `forecast|${target}|${horizonDays}`,
    useCallback(
      (signal) => getForecast(target, horizonDays, { signal }),
      [target, horizonDays],
    ),
  );

  const { data, error, busy, retry } = forecast;
  const shown = data ? targetOption(data.target) : selected;
  const points = data ? forecastChartPoints(data) : [];

  // Not enough imported history is not a broken request, and the generic
  // "the API rejected this" framing would send a reader looking for a fault
  // that is not there. It is answered on its own terms.
  const insufficientHistory =
    error !== null && error.code === INSUFFICIENT_HISTORY;

  return (
    <>
      <PageHeader
        title="Forecast"
        description="Predicted daily trading for the days after the last imported one, from a model whose error has been measured on days it never saw."
        actions={
          <ForecastControls
            target={target}
            onTargetChange={setTarget}
            horizonDays={horizonDays}
            onHorizonChange={setHorizonDays}
            busy={busy}
          />
        }
      />

      <p className="mb-5 rounded-md border border-line bg-accent-soft px-3.5 py-2.5 text-[12px] leading-relaxed text-ink">
        <strong className="font-semibold">
          These are predictions, not recorded trade.
        </strong>{" "}
        {data
          ? `Every figure on this page is model output for days that have not happened. The last day of real data behind it is ${formatIsoDate(
              data.trained_through,
            )}.`
          : "Every figure on this page is model output for days that have not happened."}
      </p>

      {insufficientHistory && error ? (
        <section className="rounded-lg border border-line bg-surface p-6">
          <h2 className="text-sm font-semibold text-ink">
            Not enough history to forecast
          </h2>
          <p className="mt-1.5 max-w-2xl text-sm leading-relaxed text-ink-muted">
            {error.detail}
          </p>
          <p className="mt-3 max-w-2xl text-[12px] leading-relaxed text-ink-subtle">
            The model needs a long enough run of daily observations to establish
            the weekly cycle and to be backtested against days it did not train
            on. Import more Square exports and this page will fill in.
          </p>
          <button
            type="button"
            onClick={retry}
            className="mt-4 h-9 rounded-md border border-line-strong bg-surface px-3.5 text-sm font-medium text-ink hover:bg-surface-muted"
          >
            Try again
          </button>
        </section>
      ) : error && !data ? (
        <ErrorPanel error={error} onRetry={retry} />
      ) : (
        <div className="flex flex-col gap-4">
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
            <StatCard
              label="Trained through"
              value={data ? formatIsoDate(data.trained_through) : null}
              hint="Last day of observed data"
              emphasis="secondary"
              stale={busy}
            />
            <StatCard
              label="Forecast period"
              value={
                data
                  ? formatDateRangeLabel(data.forecast_start, data.forecast_end)
                  : null
              }
              hint={data ? horizonLabel(data.horizon_days) : undefined}
              emphasis="secondary"
              stale={busy}
            />
            <StatCard
              label={`Predicted ${shown.measure}`}
              value={
                data
                  ? formatForecastValue(data.unit, forecastTotal(data))
                  : null
              }
              hint={
                data
                  ? data.horizon_days === 1
                    ? "The single day predicted below"
                    : `Sum of the ${horizonLabel(data.horizon_days)} predicted below`
                  : undefined
              }
              stale={busy}
            />
          </div>

          <SectionPanel
            title={`Predicted daily ${shown.measure}`}
            description="One point per predicted day. The line is dashed because none of it has happened: it is what the model expects, not what was taken."
            error={error}
            onRetry={retry}
            busy={busy}
            hasData={data !== null}
          >
            {data && points.length > 0 ? (
              <ForecastChart
                points={points}
                unit={data.unit}
                measure={shown.measure}
              />
            ) : (
              <div className="h-[240px]" aria-hidden />
            )}
          </SectionPanel>

          <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
            <SectionPanel
              title="Day by day"
              description="The same predictions as exact figures, with the weekday that mostly explains them."
              error={error}
              onRetry={retry}
              busy={busy}
              hasData={data !== null}
            >
              {data && points.length > 0 ? (
                <ForecastTable
                  points={points}
                  unit={data.unit}
                  measure={shown.measure}
                />
              ) : (
                <div className="h-[240px]" aria-hidden />
              )}
            </SectionPanel>

            <SectionPanel
              title="Historical error of this method"
              description="Measured by rolling-origin backtesting: each fold trains only on the past and is scored only on days after it."
              error={error}
              onRetry={retry}
              busy={busy}
              hasData={data !== null}
            >
              {data ? (
                <ForecastAccuracy data={data} />
              ) : (
                <div className="h-[240px]" aria-hidden />
              )}
            </SectionPanel>
          </div>

          <p className="mt-1 text-[12px] leading-relaxed text-ink-subtle">
            The forecast always begins the day after the latest imported one, so
            it moves as data is imported rather than tracking today&rsquo;s
            date. Counts are floored at zero because a negative number of orders
            is not something anyone can act on; net sales is not floored, since
            a day whose refunds outweigh its sales genuinely takes less than
            nothing.
          </p>
        </div>
      )}
    </>
  );
}
