import { OverviewDashboard } from "@/components/overview/overview-dashboard";

/**
 * The Overview page.
 *
 * A thin Server Component around a client dashboard. The figures are fetched in
 * the BROWSER, deliberately: that is the path that exercises the same-origin
 * `/api` rewrite, and it is what makes the date control interactive without a
 * round trip through a server render.
 */
export default function OverviewPage() {
  return <OverviewDashboard />;
}
