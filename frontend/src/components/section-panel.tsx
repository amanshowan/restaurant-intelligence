import type { ApiError } from "@/lib/api";

import { ErrorPanel } from "./error-panel";

/**
 * One titled section of a dashboard, and the states it can be in.
 *
 * Sections fail INDEPENDENTLY. The four analytics endpoints behind Trading are
 * separate reads with nothing in common but a date range, so one of them
 * failing is no reason to blank the three that worked — a heatmap is still
 * worth reading when the channel query fell over. The page collapses to a
 * single message only when everything failed, which is what an unreachable
 * backend looks like and where four identical panels would be noise.
 *
 * The body stays mounted while a refresh is in flight and is dimmed instead,
 * so changing the date range does not collapse the page to skeletons and
 * reflow everything below.
 */
export function SectionPanel({
  title,
  description,
  error,
  onRetry,
  busy = false,
  hasData,
  actions,
  children,
}: {
  title: string;
  description?: string;
  error?: ApiError | null;
  onRetry?: () => void;
  busy?: boolean;
  /** False before the first successful response, when there is nothing to dim. */
  hasData: boolean;
  actions?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <section className="rounded-lg border border-line bg-surface">
      <header className="flex flex-col gap-3 border-b border-line px-4 py-3.5 sm:flex-row sm:items-start sm:justify-between sm:gap-6">
        <div className="min-w-0">
          <h2 className="text-[13px] font-semibold tracking-tight text-ink">
            {title}
          </h2>
          {description && (
            <p className="mt-1 max-w-2xl text-[12px] leading-relaxed text-ink-muted">
              {description}
            </p>
          )}
        </div>
        <div className="flex shrink-0 items-center gap-3">
          {/* Reserved whether or not it is visible, so starting a request does
              not shift the header. */}
          <span
            className={`text-[12px] text-ink-subtle transition-opacity ${
              busy ? "opacity-100" : "opacity-0"
            }`}
            aria-hidden={!busy}
          >
            Updating…
          </span>
          {actions}
        </div>
      </header>

      <div className="p-4">
        {error && !hasData ? (
          <ErrorPanel error={error} onRetry={onRetry} />
        ) : (
          <>
            {/* A section that failed but still holds its last good data says
                so, rather than showing figures that are quietly out of date. */}
            {error && hasData && (
              <p
                role="alert"
                className="mb-3 rounded-md border border-line bg-surface-muted px-3 py-2 text-[12px] text-ink-muted"
              >
                Showing the last figures that loaded — this section could not be
                refreshed ({error.code}).{" "}
                {onRetry && (
                  <button
                    type="button"
                    onClick={onRetry}
                    className="font-medium text-accent underline underline-offset-2"
                  >
                    Try again
                  </button>
                )}
              </p>
            )}
            <div
              className={`transition-opacity ${busy && hasData ? "opacity-50" : "opacity-100"}`}
            >
              {children}
            </div>
          </>
        )}
      </div>
    </section>
  );
}
