import type { Metadata } from "next";

import { AskDashboard } from "@/components/ask/ask-dashboard";

export const metadata: Metadata = { title: "Ask" };

/**
 * The Ask page.
 *
 * A thin Server Component around a client dashboard, like every other section:
 * the question is posted from the BROWSER so it travels through the
 * same-origin `/api` rewrite. That is what keeps the model provider's key on
 * the server — the browser calls this application and nothing else.
 */
export default function AskPage() {
  return <AskDashboard />;
}
