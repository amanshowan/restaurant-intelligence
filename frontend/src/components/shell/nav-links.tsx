"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import { NAV_ITEMS } from "./nav-items";

/**
 * The navigation list, shared by the desktop sidebar and the mobile drawer.
 *
 * A Client Component only because the current route decides which link is
 * marked current; everything around it stays a Server Component.
 */
export function NavLinks({ onNavigate }: { onNavigate?: () => void }) {
  const pathname = usePathname();

  return (
    <nav aria-label="Sections" className="flex flex-col gap-0.5">
      {NAV_ITEMS.map((item) => {
        // Exact match only. A prefix match would light up Overview ("/") on
        // every page.
        const current = pathname === item.href;

        return (
          <Link
            key={item.href}
            href={item.href}
            onClick={onNavigate}
            title={item.description}
            // aria-current is what tells a screen reader which section is open.
            // The colour change alone communicates nothing to one.
            aria-current={current ? "page" : undefined}
            className={[
              "flex items-center justify-between gap-3 rounded-md px-3 py-2",
              "text-sm transition-colors",
              current
                ? "bg-accent-soft font-semibold text-accent"
                : "text-ink-muted hover:bg-surface-muted hover:text-ink",
            ].join(" ")}
          >
            <span>{item.label}</span>
            {!item.implemented && (
              <span className="text-[10px] font-medium uppercase tracking-wider text-ink-subtle">
                Soon
              </span>
            )}
          </Link>
        );
      })}
    </nav>
  );
}
