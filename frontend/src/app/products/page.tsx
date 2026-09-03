import type { Metadata } from "next";

import { PageHeader } from "@/components/page-header";
import { PlaceholderPanel } from "@/components/placeholder-panel";

export const metadata: Metadata = { title: "Products" };

const ENDPOINTS = [
    "/analytics/products",
    "/analytics/products/{id}/trend",
    "/analytics/products/movers",
    "/analytics/menu/evidence",
] as const;

export default function ProductsPage() {
  return (
    <>
      <PageHeader
        title="Products"
        description="Performance, trends and period-on-period movement by menu item."
      />
      <PlaceholderPanel href="/products" endpoints={ENDPOINTS} />
    </>
  );
}
