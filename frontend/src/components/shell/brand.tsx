/** The product mark. Text, not a logo image — there is no brand to render. */
export function Brand({ compact = false }: { compact?: boolean }) {
  return (
    <div className="flex items-center gap-2.5">
      <span
        aria-hidden
        className="grid h-7 w-7 shrink-0 place-items-center rounded bg-accent text-[11px] font-bold tracking-tight text-white"
      >
        RI
      </span>
      <span className="flex flex-col leading-tight">
        <span className="text-[13px] font-semibold tracking-tight text-ink">
          Restaurant Intelligence
        </span>
        {!compact && (
          <span className="text-[11px] text-ink-subtle">Square analytics</span>
        )}
      </span>
    </div>
  );
}
