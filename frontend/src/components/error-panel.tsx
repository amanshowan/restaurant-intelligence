import { ApiError, isBackendUnavailable } from "@/lib/api";

/**
 * A failed request, explained.
 *
 * The backend returns one error envelope for every failure, carrying a
 * human-readable `detail` and a stable `code` (backend/app/api/errors.py), and
 * those handlers are careful to include no stack trace, no SQL and no source
 * row content — so `detail` can be shown to a user as it stands. The `code` is
 * shown too: it is the thing worth quoting in a bug report.
 */
export function ErrorPanel({
  error,
  onRetry,
}: {
  error: ApiError;
  onRetry?: () => void;
}) {
  const unreachable = isBackendUnavailable(error);

  return (
    <section
      role="alert"
      className="rounded-lg border border-line bg-surface p-6"
    >
      <div className="flex items-start gap-3">
        <span
          aria-hidden
          className="mt-0.5 grid h-5 w-5 shrink-0 place-items-center rounded-full bg-negative text-[11px] font-bold text-white"
        >
          !
        </span>
        <div className="min-w-0">
          <h2 className="text-sm font-semibold text-ink">
            {unreachable ? "Cannot reach the API" : "The API rejected this request"}
          </h2>
          <p className="mt-1.5 max-w-2xl text-sm leading-relaxed text-ink-muted">
            {error.detail}
          </p>

          {error.issues.length > 0 && (
            <ul className="mt-3 flex flex-col gap-1">
              {error.issues.map((issue, index) => (
                <li
                  key={`${issue.location}-${index}`}
                  className="font-mono text-[12px] text-ink-muted"
                >
                  {issue.location}: {issue.message}
                </li>
              ))}
            </ul>
          )}

          <p className="mt-3 font-mono text-[11px] text-ink-subtle">
            {error.code}
            {error.status > 0 ? ` · HTTP ${error.status}` : ""}
          </p>

          {onRetry && (
            <button
              type="button"
              onClick={onRetry}
              className="mt-4 h-9 rounded-md border border-line-strong bg-surface px-3.5 text-sm font-medium text-ink hover:bg-surface-muted"
            >
              Try again
            </button>
          )}
        </div>
      </div>
    </section>
  );
}
