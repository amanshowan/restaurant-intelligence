import type { Metadata } from "next";

import { BasketsDashboard } from "@/components/baskets/baskets-dashboard";

export const metadata: Metadata = { title: "Basket Analysis" };

export default function BasketAnalysisPage() {
  return <BasketsDashboard />;
}
