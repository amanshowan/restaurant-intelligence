/**
 * The dashboard's sections, in one place so the desktop sidebar and the mobile
 * drawer cannot drift apart.
 *
 * Every section listed here is built and reads live data. There is no
 * "coming soon" state left to model, so the flag that carried one has gone
 * rather than sitting at `true` on every row.
 */
export interface NavItem {
  href: string;
  label: string;
  /** Shown under the label in the mobile drawer, and as the link's title. */
  description: string;
}

export const NAV_ITEMS: readonly NavItem[] = [
  {
    href: "/",
    label: "Overview",
    description: "Headline trading figures for a date range",
  },
  {
    href: "/trading",
    label: "Trading",
    description: "Revenue over time, weekday and hourly patterns",
  },
  {
    href: "/products",
    label: "Products",
    description: "Performance, trends and movement by menu item",
  },
  {
    href: "/baskets",
    label: "Basket Analysis",
    description: "What sells alongside what",
  },
  {
    href: "/forecast",
    label: "Forecast",
    description: "Predicted daily trading for the next 1-14 days",
  },
  {
    href: "/ask",
    label: "Ask",
    description: "Questions about your trading, answered from measured evidence",
  },
  {
    href: "/imports",
    label: "Imports",
    description: "Square export uploads and reconciliation",
  },
];
