/**
 * A short line explaining why a section has nothing to show.
 *
 * An empty result is a legitimate answer — a closed period, a threshold no pair
 * meets — and saying so plainly is better than an empty box the reader has to
 * interpret as either "no data" or "still loading".
 */
export function EmptyNote({ children }: { children: React.ReactNode }) {
  return (
    <p className="py-6 text-center text-[12px] text-ink-muted">{children}</p>
  );
}
