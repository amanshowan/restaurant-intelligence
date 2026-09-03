import { Brand } from "./brand";
import { MobileNav } from "./mobile-nav";
import { NavLinks } from "./nav-links";

/**
 * The application frame: a persistent sidebar on wide viewports, a disclosure
 * drawer on narrow ones, and a single scrolling content column.
 *
 * A Server Component. Only the two pieces that need the current route or local
 * state — the link list and the mobile drawer — are client-side.
 */
export function AppShell({ children }: { children: React.ReactNode }) {
  return (
    <div className="min-h-dvh lg:grid lg:grid-cols-[15rem_minmax(0,1fr)]">
      {/* Desktop sidebar. Fixed so the sections stay reachable while a long
          table scrolls; hidden entirely below `lg`, where MobileNav takes over. */}
      <aside className="hidden border-r border-line bg-surface lg:flex lg:h-dvh lg:flex-col lg:sticky lg:top-0">
        <div className="flex h-16 items-center border-b border-line px-5">
          <Brand />
        </div>
        <div className="flex-1 overflow-y-auto px-3 py-4">
          <NavLinks />
        </div>
        <div className="border-t border-line px-5 py-3">
          <p className="text-[11px] leading-relaxed text-ink-subtle">
            Figures are inclusive Europe/London trading dates.
          </p>
        </div>
      </aside>

      <MobileNav />

      {/* min-w-0 stops a wide child (a future table or chart) from forcing the
          whole grid column wider than the viewport. */}
      <div className="flex min-w-0 flex-col">
        <main className="mx-auto w-full max-w-[1400px] flex-1 px-4 py-6 sm:px-6 lg:px-8 lg:py-8">
          {children}
        </main>
      </div>
    </div>
  );
}
