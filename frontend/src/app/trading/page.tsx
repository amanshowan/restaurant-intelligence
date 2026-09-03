import type { Metadata } from "next";

import { PageHeader } from "@/components/page-header";
import { PlaceholderPanel } from "@/components/placeholder-panel";

export const metadata: Metadata = { title: "Trading" };

const ENDPOINTS = [
    "/analytics/revenue",
    "/analytics/day-of-week",
    "/analytics/peak-hours",
    "/analytics/channels",
] as const;

export default function TradingPage() {
  return (
    <>
      <PageHeader
        title="Trading"
        description="Revenue over time, weekday patterns and the hourly trading profile."
      />
      <PlaceholderPanel href="/trading" endpoints={ENDPOINTS} />
    </>
  );
}
