"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { ApiError } from "./api";

export interface AnalyticsResource<T> {
  /** The most recent successful response, kept while a newer one is in flight. */
  data: T | null;
  /** The failure of the most recent settled request, or null. */
  error: ApiError | null;
  /** True while the result on screen is not the one the inputs now describe. */
  busy: boolean;
  /** Re-run the current request without changing its inputs. */
  retry: () => void;
}

/**
 * One analytics request, with cancellation and stale-response protection.
 *
 * Each call owns its own request, so a page that needs four endpoints starts
 * four of them in the same render and they resolve independently — parallel by
 * construction, with no orchestration layer and no client-state library. It
 * also means a control that only affects one section (the daily/weekly toggle)
 * re-fetches only that section, because only that section's `key` changed.
 *
 * `key` — not the fetcher — decides when to re-fetch. A fetcher closure is a
 * new function on every render, so depending on it would re-request forever;
 * it is held in a ref and read when the effect actually fires.
 *
 * WHY LOADING IS DERIVED
 * `busy` compares the key of the settled result against the key the inputs now
 * describe. Storing it as state would mean calling setState synchronously
 * inside the effect — a cascading render, and a second source of truth that
 * can disagree with the data beside it.
 */
export function useAnalyticsResource<T>(
  key: string,
  fetcher: (signal: AbortSignal) => Promise<T>,
  { enabled = true }: { enabled?: boolean } = {},
): AnalyticsResource<T> {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [settledKey, setSettledKey] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);

  const fetcherRef = useRef(fetcher);

  // Kept current in an effect rather than assigned during render: a ref write
  // in the render body is a side effect, and React may render without
  // committing. Declared BEFORE the fetching effect below, because effects run
  // in declaration order — so by the time the fetch fires for a new key, the
  // ref already holds the closure that goes with it.
  useEffect(() => {
    fetcherRef.current = fetcher;
  });

  const requestKey = `${key}|${attempt}`;

  useEffect(() => {
    if (!enabled) return;

    // Aborted on cleanup, so a slow response for an abandoned range cannot
    // land after a newer one and overwrite it.
    const controller = new AbortController();

    // Every setState below runs in an async callback, after the effect body
    // has returned — never synchronously within it.
    fetcherRef
      .current(controller.signal)
      .then((result) => {
        setData(result);
        setError(null);
        setSettledKey(requestKey);
      })
      .catch((caught: unknown) => {
        if (controller.signal.aborted) return;
        setError(
          caught instanceof ApiError
            ? caught
            : new ApiError({
                status: 0,
                code: "unexpected_error",
                detail: "Something went wrong loading this data.",
              }),
        );
        setSettledKey(requestKey);
      });

    return () => controller.abort();
  }, [requestKey, enabled]);

  const retry = useCallback(() => setAttempt((value) => value + 1), []);

  return {
    data,
    error,
    busy: enabled && settledKey !== requestKey,
    retry,
  };
}
