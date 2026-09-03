import type { Metadata } from "next";

import { PageHeader } from "@/components/page-header";
import { PlaceholderPanel } from "@/components/placeholder-panel";

export const metadata: Metadata = { title: "Imports" };

const ENDPOINTS = [
    "/imports/square",
] as const;

export default function ImportsPage() {
  return (
    <>
      <PageHeader
        title="Imports"
        description="Uploading Square exports and reviewing reconciliation against Square's own totals."
      />
      <PlaceholderPanel href="/imports" endpoints={ENDPOINTS} />
    </>
  );
}
