/**
 * The HTTP layer. Every call to the backend goes through `apiFetch`, so error
 * handling, envelope parsing and URL construction exist once rather than in
 * each component.
 *
 * Intended for the BROWSER: `API_BASE_URL` is the relative path `/api`, which
 * only resolves against a page origin. Fetching from a Server Component would
 * need the absolute upstream instead, and would bypass the rewrite; nothing
 * does that today, and the Overview page fetches client-side deliberately so
 * that the same-origin proxy is the path actually exercised.
 */

import { API_BASE_URL } from "./config";
import { withQuery, type QueryParams } from "./query";
import type { ApiErrorBody, ApiValidationIssue } from "./types";

/** A failed API call, in one shape regardless of how it failed. */
export class ApiError extends Error {
  /** HTTP status, or 0 when the request never got a response at all. */
  readonly status: number;
  /** The backend's stable machine-readable code, e.g. "invalid_date_range". */
  readonly code: string;
  /** The human-readable explanation. Safe to show a user: the backend's
   *  handlers carry no stack trace, no SQL and no source-row content. */
  readonly detail: string;
  /** Populated only for 422 request-validation failures. */
  readonly issues: ApiValidationIssue[];

  constructor(init: {
    status: number;
    code: string;
    detail: string;
    issues?: ApiValidationIssue[];
  }) {
    super(init.detail);
    this.name = "ApiError";
    this.status = init.status;
    this.code = init.code;
    this.detail = init.detail;
    this.issues = init.issues ?? [];
  }
}

/** Codes this client raises itself, for failures the backend never sees. */
export const CLIENT_ERROR_CODES = {
  /** The request never reached a server: backend down, DNS, connection reset. */
  NETWORK_UNAVAILABLE: "network_unavailable",
  /** A response arrived but was not the JSON envelope the API documents. */
  MALFORMED_RESPONSE: "malformed_response",
} as const;

/**
 * True when the error means "the backend could not be reached", as opposed to
 * "the backend answered and said no". The distinction matters: one is worth a
 * retry, the other is a message about the request, and telling an operator
 * their request was rejected while the service is simply down sends them
 * looking in the wrong place.
 *
 * Keyed on the ENVELOPE, not on the status code. The backend answers every
 * error it handles in the documented `{detail, code}` shape
 * (backend/app/api/errors.py), so a response that is not that shape did not
 * come from those handlers at all.
 *
 * This matters because of how the same-origin proxy fails. When the upstream
 * is unreachable, the Next.js rewrite does NOT return a gateway status: it
 * returns a plain-text `HTTP 500 Internal Server Error`, which is
 * indistinguishable by status from the backend itself throwing. The absence of
 * the envelope is the only reliable signal, and it is a sound one.
 */
export function isBackendUnavailable(error: unknown): boolean {
  if (!(error instanceof ApiError)) return false;
  return (
    error.code === CLIENT_ERROR_CODES.NETWORK_UNAVAILABLE ||
    error.code === CLIENT_ERROR_CODES.MALFORMED_RESPONSE
  );
}

/**
 * Narrows an unknown JSON body to the documented error envelope.
 *
 * Exported for its tests, and because the envelope is the one part of the
 * contract worth pinning down independently of a live server.
 */
export function parseErrorBody(body: unknown, status: number): ApiError {
  const envelope = body as Partial<ApiErrorBody> | null | undefined;

  const hasEnvelope =
    typeof envelope === "object" &&
    envelope !== null &&
    typeof envelope.detail === "string" &&
    typeof envelope.code === "string";

  if (!hasEnvelope) {
    // A proxy, a gateway or an unhandled framework error can return HTML or an
    // empty body. Reporting the status is more use than reporting nothing.
    return new ApiError({
      status,
      code: CLIENT_ERROR_CODES.MALFORMED_RESPONSE,
      detail:
        `The API did not return a readable response (HTTP ${status}). ` +
        "The backend may be starting up or unavailable — check " +
        "`docker compose ps`.",
    });
  }

  const issues = Array.isArray(envelope.errors)
    ? envelope.errors.filter(
        (issue): issue is ApiValidationIssue =>
          typeof issue === "object" && issue !== null && "message" in issue,
      )
    : [];

  return new ApiError({
    status,
    code: envelope.code as string,
    detail: envelope.detail as string,
    issues,
  });
}

export interface ApiFetchOptions {
  query?: QueryParams;
  signal?: AbortSignal;
}

/**
 * Fetches `path` (relative to the API base) and returns the parsed JSON body.
 *
 * Throws `ApiError` for every failure mode — non-2xx, unreachable backend,
 * unparseable body — so a caller has exactly one type to catch. An aborted
 * request rethrows the `AbortError` untouched, because a cancelled request is
 * not a failure and must not be rendered as one.
 */
export async function apiFetch<T>(
  path: string,
  options: ApiFetchOptions = {},
): Promise<T> {
  const url = `${API_BASE_URL}${withQuery(path, options.query ?? {})}`;

  let response: Response;
  try {
    response = await fetch(url, {
      signal: options.signal,
      headers: { Accept: "application/json" },
      // The dashboard reads live figures; a cached response would show stale
      // takings after an import with no indication that it had.
      cache: "no-store",
    });
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") throw error;
    throw new ApiError({
      status: 0,
      code: CLIENT_ERROR_CODES.NETWORK_UNAVAILABLE,
      detail:
        "Could not reach the API. Check that the backend is running " +
        "(`docker compose ps`).",
    });
  }

  // Parsed before the status is checked: the error envelope is JSON too, and
  // it carries the `code` that makes the failure actionable.
  let body: unknown = null;
  const text = await response.text();
  if (text) {
    try {
      body = JSON.parse(text);
    } catch {
      body = null;
    }
  }

  if (!response.ok) throw parseErrorBody(body, response.status);

  if (body === null) {
    throw new ApiError({
      status: response.status,
      code: CLIENT_ERROR_CODES.MALFORMED_RESPONSE,
      detail: "The API returned an empty body where JSON was expected.",
    });
  }

  return body as T;
}
