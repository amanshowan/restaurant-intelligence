/**
 * One figure, with its label and a line of context.
 *
 * `value === null` means "not known yet" and renders a placeholder bar of the
 * same height as the text it replaces. That is the whole reason the loading
 * state is a property of this component rather than a separate skeleton
 * component: a card that changes height when its number arrives moves every
 * card below it.
 */
export function StatCard({
  label,
  value,
  hint,
  emphasis = "primary",
  stale = false,
}: {
  label: string;
  value: string | null;
  hint?: string;
  /** Primary figures carry larger type. Secondary ones support them. */
  emphasis?: "primary" | "secondary";
  /** True while a newer request is in flight and this value is the old one. */
  stale?: boolean;
}) {
  const valueClass =
    emphasis === "primary"
      ? "text-[26px] leading-8"
      : "text-[19px] leading-8";

  return (
    <div className="rounded-lg border border-line bg-surface px-4 py-3.5">
      <p className="text-[11px] font-semibold uppercase tracking-wider text-ink-subtle">
        {label}
      </p>

      <div className="mt-1.5 flex h-8 items-center">
        {value === null ? (
          <span
            // Announced as busy so a screen reader is not told the value is an
            // empty string.
            aria-hidden
            className="h-5 w-28 animate-pulse rounded bg-line"
          />
        ) : (
          <span
            className={`tabular font-semibold tracking-tight text-ink transition-opacity ${valueClass} ${
              stale ? "opacity-40" : "opacity-100"
            }`}
          >
            {value}
          </span>
        )}
      </div>

      {/* Reserved whether or not a hint is present, so cards in a row line up. */}
      <p className="mt-0.5 h-4 text-[12px] leading-4 text-ink-subtle">
        {value === null ? "" : hint}
      </p>
    </div>
  );
}
