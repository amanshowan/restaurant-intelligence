import type { Metadata } from "next";

import { TradingDashboard } from "@/components/trading/trading-dashboard";

export const metadata: Metadata = { title: "Trading" };

/**
 * The Trading page.
 *
 * A thin Server Component around a client dashboard, for the same reason as
 * Overview: the figures are fetched in the BROWSER so they travel through the
 * same-origin `/api` rewrite, and so the date range and the daily/weekly
 * toggle are interactive without a server round trip.
 */
export default function TradingPage() {
  return <TradingDashboard />;
}
