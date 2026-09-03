/**
 * Query-string construction for the API.
 *
 * Small on purpose, but the one rule it encodes is not cosmetic. Several
 * backend endpoints take `kind` as `list[ProductKind]`, which FastAPI reads as
 * a REPEATED key:
 *
 *     ?kind=menu_item&kind=custom_amount        parsed as two values
 *     ?kind=menu_item,custom_amount             parsed as ONE value, then
 *                                               rejected as an invalid enum
 *
 * Getting that wrong produces a 422 rather than a wrong number, so it fails
 * loudly — but it fails at the point the product and basket endpoints are wired
 * up, which is a later commit. Encoding the rule here means those endpoints
 * inherit correct behaviour instead of rediscovering it.
 */

export type QueryValue =
  | string
  | number
  | boolean
  | null
  | undefined
  | readonly (string | number)[];

export type QueryParams = Record<string, QueryValue>;

/**
 * Serialises `params` into a query string WITHOUT a leading `?`.
 *
 *   - `null` and `undefined` are omitted, so an optional filter left unset is
 *     absent rather than sent as the string "undefined".
 *   - Arrays become repeated keys; an empty array is omitted entirely.
 *   - Key order follows insertion order, which keeps URLs stable and makes
 *     them comparable in tests and in a browser network panel.
 */
export function buildQuery(params: QueryParams): string {
  const search = new URLSearchParams();

  for (const [key, value] of Object.entries(params)) {
    if (value === null || value === undefined) continue;

    if (Array.isArray(value)) {
      for (const item of value) {
        if (item === null || item === undefined) continue;
        search.append(key, String(item));
      }
      continue;
    }

    search.append(key, String(value));
  }

  return search.toString();
}

/** `path` with a query string appended, or unchanged when there is nothing to add. */
export function withQuery(path: string, params: QueryParams): string {
  const query = buildQuery(params);
  return query ? `${path}?${query}` : path;
}
