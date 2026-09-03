import { afterEach, describe, expect, it, vi } from "vitest";

import {
  ApiError,
  CLIENT_ERROR_CODES,
  apiFetch,
  isBackendUnavailable,
  parseErrorBody,
} from "./client";

/** Installs a stub `fetch` and returns the spy, so calls can be asserted. */
function stubFetch(implementation: (url: string) => Promise<Response> | Response) {
  const spy = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
    void init;
    return Promise.resolve(implementation(String(input)));
  });
  vi.stubGlobal("fetch", spy);
  return spy;
}

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("parseErrorBody", () => {
  it("reads the documented envelope", () => {
    const error = parseErrorBody(
      { detail: "end_date must not be before start_date", code: "invalid_date_range" },
      400,
    );

    expect(error).toBeInstanceOf(ApiError);
    expect(error.status).toBe(400);
    expect(error.code).toBe("invalid_date_range");
    expect(error.detail).toBe("end_date must not be before start_date");
    expect(error.issues).toEqual([]);
    // Inherits from Error, so `message` works for anything that logs it.
    expect(error.message).toBe("end_date must not be before start_date");
  });

  it("keeps the per-field issues from a 422", () => {
    const error = parseErrorBody(
      {
        detail: "query.start_date: Field required",
        code: "validation_error",
        errors: [
          {
            location: "query.start_date",
            message: "Field required",
            type: "missing",
          },
        ],
      },
      422,
    );

    expect(error.code).toBe("validation_error");
    expect(error.issues).toHaveLength(1);
    expect(error.issues[0].location).toBe("query.start_date");
  });

  it("tolerates a null errors field", () => {
    const error = parseErrorBody(
      { detail: "nope", code: "some_code", errors: null },
      400,
    );
    expect(error.issues).toEqual([]);
  });

  it("falls back when the body is not the envelope", () => {
    // A gateway or an unhandled framework error can return HTML, or nothing.
    for (const body of [null, "<html>502 Bad Gateway</html>", {}, { detail: 1 }]) {
      const error = parseErrorBody(body, 502);
      expect(error.code).toBe(CLIENT_ERROR_CODES.MALFORMED_RESPONSE);
      expect(error.status).toBe(502);
      expect(error.detail).toContain("502");
    }
  });
});

describe("apiFetch", () => {
  it("prefixes the same-origin API base and appends the query", async () => {
    const spy = stubFetch(() => jsonResponse({ status: "ok" }));

    await apiFetch("/health", { query: { verbose: true } });

    // Same-origin and relative: never an absolute cross-origin URL, and never
    // the Docker-internal hostname.
    expect(spy.mock.calls[0][0]).toBe("/api/health?verbose=true");
  });

  it("returns the parsed body on success", async () => {
    stubFetch(() => jsonResponse({ status: "ready", database: "ok" }));

    await expect(apiFetch("/health/ready")).resolves.toEqual({
      status: "ready",
      database: "ok",
    });
  });

  it("throws ApiError carrying the backend's code on a 4xx", async () => {
    stubFetch(() =>
      jsonResponse({ detail: "bad range", code: "invalid_date_range" }, 400),
    );

    await expect(apiFetch("/analytics/overview")).rejects.toMatchObject({
      code: "invalid_date_range",
      status: 400,
      detail: "bad range",
    });
  });

  it("reports an unreachable backend distinctly from a rejected request", async () => {
    stubFetch(() => {
      throw new TypeError("Failed to fetch");
    });

    const error = await apiFetch("/health").catch((caught: unknown) => caught);

    expect(error).toBeInstanceOf(ApiError);
    expect((error as ApiError).code).toBe(CLIENT_ERROR_CODES.NETWORK_UNAVAILABLE);
    expect((error as ApiError).status).toBe(0);
    expect(isBackendUnavailable(error)).toBe(true);
  });

  it("rethrows an abort untouched, because a cancelled request is not a failure", async () => {
    const controller = new AbortController();
    stubFetch(() => {
      throw new DOMException("The operation was aborted.", "AbortError");
    });

    const error = await apiFetch("/health", {
      signal: controller.signal,
    }).catch((caught: unknown) => caught);

    expect(error).toBeInstanceOf(DOMException);
    expect(error).not.toBeInstanceOf(ApiError);
  });

  it("rejects an empty body where JSON was expected", async () => {
    stubFetch(() => new Response("", { status: 200 }));

    await expect(apiFetch("/health")).rejects.toMatchObject({
      code: CLIENT_ERROR_CODES.MALFORMED_RESPONSE,
    });
  });

  it("does not cache, so figures cannot go stale after an import", async () => {
    const spy = stubFetch(() => jsonResponse({ status: "ok" }));

    await apiFetch("/health");

    expect(spy.mock.calls[0][1]).toMatchObject({ cache: "no-store" });
  });
});

describe("isBackendUnavailable", () => {
  it("classifies the proxy's own failure as unreachable", async () => {
    // The behaviour this exists for, verified against the real stack: with the
    // API container stopped, the Next.js rewrite answers with a PLAIN-TEXT
    // `HTTP 500 Internal Server Error` — not a 502 or 504. Keying on the
    // status would report "the API rejected this request" while the service is
    // simply down. The absence of the JSON envelope is what identifies it.
    stubFetch(() => new Response("Internal Server Error", { status: 500 }));

    const error = await apiFetch("/analytics/overview").catch(
      (caught: unknown) => caught,
    );

    expect((error as ApiError).code).toBe(
      CLIENT_ERROR_CODES.MALFORMED_RESPONSE,
    );
    expect(isBackendUnavailable(error)).toBe(true);
  });

  it("treats any non-envelope response as unreachable", () => {
    for (const status of [500, 502, 503, 504]) {
      expect(
        isBackendUnavailable(
          new ApiError({
            status,
            code: CLIENT_ERROR_CODES.MALFORMED_RESPONSE,
            detail: "",
          }),
        ),
      ).toBe(true);
    }
  });

  it("does not treat a rejected request as unreachable", () => {
    // These carry the envelope, so the backend demonstrably answered — even
    // the 503 from /health/ready, which is a considered response, not silence.
    expect(
      isBackendUnavailable(
        new ApiError({ status: 400, code: "invalid_date_range", detail: "" }),
      ),
    ).toBe(false);
    expect(
      isBackendUnavailable(
        new ApiError({ status: 503, code: "not_ready", detail: "" }),
      ),
    ).toBe(false);
    expect(isBackendUnavailable(new Error("something else"))).toBe(false);
  });
});
