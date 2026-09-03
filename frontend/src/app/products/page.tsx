import type { Metadata } from "next";

import { ProductsDashboard } from "@/components/products/products-dashboard";

export const metadata: Metadata = { title: "Products" };

export default function ProductsPage() {
  return <ProductsDashboard />;
}
