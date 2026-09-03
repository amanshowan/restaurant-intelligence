import type { Metadata } from "next";

import { ForecastDashboard } from "@/components/forecast/forecast-dashboard";

export const metadata: Metadata = { title: "Forecast" };

/**
 * The Forecast page.
 *
 * A thin Server Component around a client dashboard, like Trading and
 * Products: the prediction is fetched in the BROWSER so it travels through the
 * same-origin `/api` rewrite, and so the measure and horizon controls work
 * without a server round trip.
 */
export default function ForecastPage() {
  return <ForecastDashboard />;
}
