/**
 * The dashboard's sections, in one place so the desktop sidebar and the mobile
 * drawer cannot drift apart.
 *
 * Only Overview is implemented. The rest are declared now because the shape of
 * the product is part of what this commit establishes — a reviewer should be
 * able to see where the M3/M4 analytics already sitting in the API will land.
 */
export interface NavItem {
  href: string;
  label: string;
  /** Shown under the label in the mobile drawer, and as the link's title. */
  description: string;
  /** False until the section has real content. Rendered as a subdued marker. */
  implemented: boolean;
}

export const NAV_ITEMS: readonly NavItem[] = [
  {
    href: "/",
    label: "Overview",
    description: "Headline trading figures for a date range",
    implemented: true,
  },
  {
    href: "/trading",
    label: "Trading",
    description: "Revenue over time, weekday and hourly patterns",
    implemented: false,
  },
  {
    href: "/products",
    label: "Products",
    description: "Performance, trends and movement by menu item",
    implemented: false,
  },
  {
    href: "/baskets",
    label: "Basket Analysis",
    description: "What sells alongside what",
    implemented: false,
  },
  {
    href: "/imports",
    label: "Imports",
    description: "Square export uploads and reconciliation",
    implemented: false,
  },
];
