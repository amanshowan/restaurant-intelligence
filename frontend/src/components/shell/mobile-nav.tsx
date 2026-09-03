"use client";

import { useState } from "react";
import { usePathname } from "next/navigation";

import { Brand } from "./brand";
import { NavLinks } from "./nav-links";

/**
 * The narrow-viewport navigation: a sticky bar with a disclosure button that
 * opens the same link list the sidebar shows.
 *
 * A drawer, not a bottom tab bar. Five sections is one too many to label
 * legibly across a phone, and the list will grow.
 */
export function MobileNav() {
  const [open, setOpen] = useState(false);
  const pathname = usePathname();

  // Close on navigation. Without this the panel stays open over the page it
  // just navigated to, which reads as a broken link.
  //
  // Adjusted DURING RENDER rather than in an effect. React restarts the render
  // immediately with the new state, before anything reaches the DOM, so there
  // is no flash of the open panel and no second commit. An effect would set
  // state after painting, which is the cascading render the compiler warns
  // about (https://react.dev/learn/you-might-not-need-an-effect).
  const [renderedPathname, setRenderedPathname] = useState(pathname);
  if (pathname !== renderedPathname) {
    setRenderedPathname(pathname);
    setOpen(false);
  }

  return (
    <div className="sticky top-0 z-20 border-b border-line bg-surface lg:hidden">
      <div className="flex h-14 items-center justify-between px-4">
        <Brand compact />
        <button
          type="button"
          onClick={() => setOpen((value) => !value)}
          // Names the relationship for assistive technology: this control owns
          // that panel, and here is its current state.
          aria-expanded={open}
          aria-controls="mobile-nav-panel"
          className="flex items-center gap-2 rounded-md border border-line px-3 py-1.5 text-sm font-medium text-ink-muted"
        >
          <svg
            aria-hidden
            viewBox="0 0 16 16"
            className="h-4 w-4"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.5"
            strokeLinecap="round"
          >
            {open ? (
              <path d="M4 4l8 8M12 4l-8 8" />
            ) : (
              <path d="M2 4h12M2 8h12M2 12h12" />
            )}
          </svg>
          {open ? "Close" : "Menu"}
        </button>
      </div>

      {/*
        Rendered only when open rather than hidden with CSS, so the links are
        not reachable by keyboard tabbing while the panel is closed.
      */}
      {open && (
        <div id="mobile-nav-panel" className="border-t border-line px-3 py-3">
          <NavLinks onNavigate={() => setOpen(false)} />
        </div>
      )}
    </div>
  );
}
