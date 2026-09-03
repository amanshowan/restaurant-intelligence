import type { Metadata } from "next";

import { AppShell } from "@/components/shell/app-shell";
import "./globals.css";

export const metadata: Metadata = {
  title: {
    default: "Restaurant Intelligence",
    template: "%s · Restaurant Intelligence",
  },
  description:
    "Revenue, timing, product and basket analytics for independent " +
    "hospitality businesses running Square.",
};

// Typed explicitly rather than with Next's generated `LayoutProps<"/">`
// global: that type only exists once `next typegen` has written .next/types,
// so depending on it makes `tsc --noEmit` fail in a clean checkout. This
// layout takes no route params, so the generated type buys nothing here.
export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en-GB" className="h-full">
      <body className="min-h-full">
        <AppShell>{children}</AppShell>
      </body>
    </html>
  );
}
