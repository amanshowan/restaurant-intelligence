import type { Metadata } from "next";

import { PageHeader } from "@/components/page-header";
import { PlaceholderPanel } from "@/components/placeholder-panel";

export const metadata: Metadata = { title: "Basket Analysis" };

const ENDPOINTS = [
    "/analytics/baskets/pairs",
    "/analytics/products/{id}/attachments",
] as const;

export default function BasketAnalysisPage() {
  return (
    <>
      <PageHeader
        title="Basket Analysis"
        description="Which products are bought together, with support, confidence and lift."
      />
      <PlaceholderPanel href="/baskets" endpoints={ENDPOINTS} />
    </>
  );
}
