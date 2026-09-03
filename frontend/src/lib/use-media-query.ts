"use client";

import { useCallback, useSyncExternalStore } from "react";

/**
 * Whether a CSS media query currently matches.
 *
 * Used where a layout decision cannot be expressed in CSS — chart tick density,
 * for instance, is a prop on a component rather than a style on an element.
 *
 * `useSyncExternalStore` rather than `useState` + an effect: it subscribes to
 * the media query itself, and its third argument is the SERVER snapshot. That
 * matters because `window.matchMedia` does not exist during server rendering;
 * returning `false` there means the server and the first client render agree,
 * and the real value arrives on subscription without a hydration mismatch.
 */
export function useMediaQuery(query: string): boolean {
  const subscribe = useCallback(
    (onChange: () => void) => {
      const list = window.matchMedia(query);
      list.addEventListener("change", onChange);
      return () => list.removeEventListener("change", onChange);
    },
    [query],
  );

  return useSyncExternalStore(
    subscribe,
    () => window.matchMedia(query).matches,
    () => false,
  );
}

/** Roughly a phone. Matches Tailwind's `sm` breakpoint. */
export const NARROW_VIEWPORT = "(max-width: 639px)";
