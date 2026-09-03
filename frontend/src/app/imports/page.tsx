import type { Metadata } from "next";

import { ImportsDashboard } from "@/components/imports/imports-dashboard";

export const metadata: Metadata = { title: "Imports" };

export default function ImportsPage() {
  return <ImportsDashboard />;
}
