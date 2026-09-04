import { ApiError, isBackendUnavailable, type ResolvedProduct } from "@/lib/api";
import { productLabel } from "@/lib/ask";

/**
 * The states this page can be in that are not an answer.
 *
 * Every one of them is a legitimate outcome rather than a fault, and each gets
 * its own words. The generic "the API rejected this request" panel used
 * elsewhere is wrong here: a café owner whose AI feature is switched off, and
 * one whose provider is briefly overloaded, need to do different things, and
 * neither has made a mistake.
 */

/** Backend codes from app/api/errors.py, mapped to what a person should do. */
const FAILURES: Record<
  string,
  { title: string; advice: string; retryable: boolean }
> = {
  llm_not_configured: {
    title: "AI answers are not switched on",
    advice:
      "This deployment has no model provider configured, so questions cannot " +
      "be answered. Every other page works as normal — the dashboards, the " +
      "product analysis and the forecast all read the same data directly.",
    retryable: false,
  },
  llm_timeout: {
    title: "The model took too long",
    advice:
      "The request was abandoned rather than left hanging. Asking again " +
      "usually works; a shorter, more specific question is quicker.",
    retryable: true,
  },
  llm_unavailable: {
    title: "The model provider is unavailable",
    advice:
      "The provider could not be reached, or is rate-limiting requests. " +
      "Nothing is wrong with your data — this is worth retrying in a moment.",
    retryable: true,
  },
  llm_refused: {
    title: "The model declined to answer",
    advice:
      "The provider's own safety systems stopped this one. Rephrasing the " +
      "question as a straightforward business query usually resolves it.",
    retryable: true,
  },
  llm_invalid_response: {
    title: "The question could not be turned into an analysis",
    advice:
      "The model did not produce a valid plan for this question, so nothing " +
      "was run. Try asking it more directly — for example, name the period " +
      "or the product you mean.",
    retryable: true,
  },
  invalid_question: {
    title: "That question cannot be sent",
    advice: "Questions need to be between a few characters and 1,000 long.",
    retryable: false,
  },
};

export function AskFailure({
  error,
  onRetry,
}: {
  error: ApiError;
  onRetry: () => void;
}) {
  const unreachable = isBackendUnavailable(error);
  const known = FAILURES[error.code];

  const title = unreachable
    ? "Cannot reach the API"
    : (known?.title ?? "That question could not be answered");
  const advice = unreachable
    ? "The dashboard could not reach its own backend. Check that it is running."
    : (known?.advice ?? error.detail);
  const retryable = unreachable || (known?.retryable ?? true);

  return (
    <section
      role="alert"
      aria-live="assertive"
      className="rounded-lg border border-line bg-surface p-5"
    >
      <h2 className="text-sm font-semibold text-ink">{title}</h2>
      <p className="mt-1.5 max-w-2xl text-sm leading-relaxed text-ink-muted">
        {advice}
      </p>

      {/* The backend's own explanation, shown beneath ours when it adds
          something. Its error handlers carry no stack trace, no SQL, no
          provider message and no prompt — see backend/app/api/errors.py — so
          it is safe to surface as written. */}
      {known && error.detail && error.detail !== advice && (
        <p className="mt-2 max-w-2xl text-[12px] leading-relaxed text-ink-subtle">
          {error.detail}
        </p>
      )}

      {retryable && (
        <button
          type="button"
          onClick={onRetry}
          className="mt-4 h-9 rounded-md border border-line-strong bg-surface px-3.5 text-sm font-medium text-ink hover:bg-surface-muted"
        >
          Try again
        </button>
      )}

      <p className="mt-3 font-mono text-[11px] text-ink-subtle">
        {error.code}
        {error.status > 0 ? ` · HTTP ${error.status}` : ""}
      </p>
    </section>
  );
}

/**
 * A product name that matched several menu items.
 *
 * The candidates are offered as buttons because the fix is one click: ask
 * again naming the variation. The backend deliberately refuses to choose, and
 * this is what that refusal looks like to a person — a question, not an error.
 */
export function ClarificationPanel({
  answer,
  candidates,
  onChoose,
}: {
  answer: string;
  candidates: ResolvedProduct[];
  onChoose: (product: ResolvedProduct) => void;
}) {
  return (
    <section
      aria-live="polite"
      className="rounded-lg border border-line bg-surface p-5"
    >
      <h2 className="text-sm font-semibold text-ink">Which one did you mean?</h2>
      <p className="mt-1.5 max-w-2xl text-sm leading-relaxed text-ink-muted">
        {answer}
      </p>

      {candidates.length > 0 && (
        <ul className="mt-3.5 flex flex-wrap gap-2">
          {candidates.map((candidate) => (
            <li key={candidate.product_id}>
              <button
                type="button"
                onClick={() => onChoose(candidate)}
                className="rounded-full border border-line-strong bg-surface px-3 py-1.5 text-[12px] font-medium text-ink hover:bg-surface-muted"
              >
                {productLabel(candidate)}
              </button>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

/**
 * A question no available operation can answer.
 *
 * Reported plainly, with the backend's own reason. Saying "I cannot" is a
 * correct outcome here — the alternative, running a loosely related operation
 * so that something comes back, produces a confident answer to a question
 * nobody asked.
 */
export function UnsupportedPanel({ answer }: { answer: string }) {
  return (
    <section
      aria-live="polite"
      className="rounded-lg border border-line bg-surface p-5"
    >
      <h2 className="text-sm font-semibold text-ink">
        That cannot be answered from this data
      </h2>
      <p className="mt-1.5 max-w-2xl text-sm leading-relaxed text-ink-muted">
        {answer}
      </p>
      <p className="mt-3 max-w-2xl text-[12px] leading-relaxed text-ink-subtle">
        No analysis was run and nothing was guessed. This system holds what was
        sold and when — not costs, margins, staffing or anything outside the
        till.
      </p>
    </section>
  );
}
