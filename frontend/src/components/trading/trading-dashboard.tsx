"use client";

import { useCallback, useState } from "react";

import { DateRangeControl } from "@/components/date-range-control";
import { ErrorPanel } from "@/components/error-panel";
import { PageHeader } from "@/components/page-header";
import {
  getChannels,
  getDayOfWeek,
  getPeakHours,
  getRevenue,
  type ChannelMixResponse,
  type DayOfWeekResponse,
  type Granularity,
  type PeakHoursResponse,
  type RevenueResponse,
} from "@/lib/api";
import { useAnalyticsResource } from "@/lib/use-analytics-resource";
import {
  defaultDateRange,
  validateDateRange,
  type DateRange,
} from "@/lib/date-range";
import { formatDateRangeLabel } from "@/lib/format";

import { ChannelSection } from "./channel-section";
import { DayOfWeekSection } from "./day-of-week-section";
import { PeakHoursSection } from "./peak-hours-section";
import { RevenueSection } from "./revenue-section";

export function TradingDashboard() {
  // One range drives every section. Same control and the same defaulting rule
  // as Overview, so moving between the pages does not change how dates behave.
  const [range, setRange] = useState<DateRange>(() => defaultDateRange());
  const [granularity, setGranularity] = useState<Granularity>("day");

  const validationError = validateDateRange(range);
  const enabled = validationError === null;

  const rangeKey = `${range.startDate}|${range.endDate}`;

  // Four independent requests, started in the same render and resolving on
  // their own. Only the revenue key carries the granularity, so switching
  // daily/weekly re-fetches that section alone rather than the whole page.
  const revenue = useAnalyticsResource<RevenueResponse>(
    `revenue|${rangeKey}|${granularity}`,
    useCallback(
      (signal) => getRevenue(range, granularity, { signal }),
      [range, granularity],
    ),
    { enabled },
  );

  const dayOfWeek = useAnalyticsResource<DayOfWeekResponse>(
    `day-of-week|${rangeKey}`,
    useCallback((signal) => getDayOfWeek(range, { signal }), [range]),
    { enabled },
  );

  const peakHours = useAnalyticsResource<PeakHoursResponse>(
    `peak-hours|${rangeKey}`,
    useCallback((signal) => getPeakHours(range, { signal }), [range]),
    { enabled },
  );

  const channels = useAnalyticsResource<ChannelMixResponse>(
    `channels|${rangeKey}`,
    useCallback((signal) => getChannels(range, { signal }), [range]),
    { enabled },
  );

  const resources = [revenue, dayOfWeek, peakHours, channels];
  const busy = resources.some((resource) => resource.busy);
  const loadedSomething = resources.some((resource) => resource.data !== null);

  // Every section failed with nothing to show. In practice this is an
  // unreachable backend, where four identical panels would say one thing four
  // times — so it collapses to a single message. Any lesser failure stays
  // inside the section it belongs to.
  const totalFailure =
    !loadedSomething && resources.every((resource) => resource.error !== null);

  const retryAll = useCallback(() => {
    for (const resource of resources) resource.retry();
    // resources is rebuilt each render from stable retry callbacks.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [revenue.retry, dayOfWeek.retry, peakHours.retry, channels.retry]);

  return (
    <>
      <PageHeader
        title="Trading"
        description="Revenue over time, weekday patterns, the hourly trading profile and channel mix — for one inclusive Europe/London date range."
        actions={
          <DateRangeControl
            value={range}
            onChange={setRange}
            error={validationError}
            busy={busy}
          />
        }
      />

      {totalFailure ? (
        <ErrorPanel error={revenue.error!} onRetry={retryAll} />
      ) : (
        <>
          <h2 className="mb-3 text-[13px] font-semibold text-ink">
            {formatDateRangeLabel(range.startDate, range.endDate)}
          </h2>

          <div className="flex flex-col gap-4">
            <RevenueSection
              resource={revenue}
              granularity={granularity}
              onGranularityChange={setGranularity}
            />

            {/* Weekday and channel sit side by side on wide viewports: both are
                short, and pairing them keeps the heatmap above the fold. */}
            <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
              <DayOfWeekSection resource={dayOfWeek} />
              <ChannelSection resource={channels} />
            </div>

            <PeakHoursSection resource={peakHours} />
          </div>

          <p className="mt-5 text-[12px] leading-relaxed text-ink-subtle">
            Dates are inclusive local calendar days. Refunds reduce net sales
            but are not counted as payment orders, and every figure here is
            computed by the API rather than derived in the browser.
          </p>
        </>
      )}
    </>
  );
}
