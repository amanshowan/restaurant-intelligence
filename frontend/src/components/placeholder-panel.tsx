import { NAV_ITEMS } from "./shell/nav-items";

/**
 * The body of a section that has no view yet.
 *
 * States plainly that the analytics exist in the API and only the view is
 * missing, and names the endpoints — which is more useful to a reviewer than a
 * decorative "coming soon" panel, and honest about what is and is not built.
 */
export function PlaceholderPanel({
  href,
  endpoints,
}: {
  href: string;
  endpoints: readonly string[];
}) {
  const item = NAV_ITEMS.find((entry) => entry.href === href);

  return (
    <section className="rounded-lg border border-line bg-surface p-6">
      <h2 className="text-sm font-semibold text-ink">Not built yet</h2>
      <p className="mt-2 max-w-2xl text-sm leading-relaxed text-ink-muted">
        {item?.description}. The data behind this section is already served by
        the API and covered by tests; only the view is outstanding.
      </p>

      <h3 className="mt-5 text-[11px] font-semibold uppercase tracking-wider text-ink-subtle">
        Endpoints this section will read
      </h3>
      <ul className="mt-2 flex flex-col gap-1">
        {endpoints.map((endpoint) => (
          <li
            key={endpoint}
            className="font-mono text-[12px] text-ink-muted"
          >
            {endpoint}
          </li>
        ))}
      </ul>
    </section>
  );
}
