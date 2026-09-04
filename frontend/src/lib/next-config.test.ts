import { afterEach, describe, expect, it, vi } from "vitest";

import nextConfig, { resolveOutput } from "../../next.config";

/**
 * The build configuration, asserted directly.
 *
 * Lives under `src/` because that is what `vitest.config.ts` collects, and
 * imports the config from the project root. What it protects is a failure that
 * only appears AFTER a successful build, on a machine none of us is watching:
 * Vercel's adapter reads `.next/*.nft.json` trace manifests, standalone output
 * changes which of those are written, and on Next.js 16.3 the adapter then
 * dies on a missing `next-server.js.nft.json`. Nothing in a local build or in
 * `tsc` catches that, so the branch is pinned here instead.
 */

afterEach(() => {
  vi.unstubAllEnvs();
});

describe("resolveOutput", () => {
  it("emits a standalone server when not building on Vercel", () => {
    // The Docker production stage copies `.next/standalone`; without this the
    // image has no server to run.
    expect(resolveOutput(undefined)).toBe("standalone");
  });

  it("disables standalone output on Vercel", () => {
    expect(resolveOutput("1")).toBeUndefined();
  });

  it("treats any non-empty VERCEL value as Vercel", () => {
    // Vercel documents "1", but the flag is a presence signal, not a version.
    for (const value of ["1", "true", "yes"]) {
      expect(resolveOutput(value)).toBeUndefined();
    }
  });

  it("is not fooled by an empty or absent VERCEL", () => {
    expect(resolveOutput("")).toBe("standalone");
    expect(resolveOutput(undefined)).toBe("standalone");
  });

  it("keys on VERCEL alone, not on the environment being production", () => {
    // Our own production image builds with NODE_ENV=production and MUST still
    // get a standalone server. Stubbed rather than passed as a literal, so
    // this exercises the real `process.env` path.
    vi.stubEnv("NODE_ENV", "production");
    expect(resolveOutput()).toBe("standalone");
  });

  it("reads process.env by default", () => {
    vi.stubEnv("VERCEL", "1");
    expect(resolveOutput()).toBeUndefined();
  });
});

describe("the exported config", () => {
  it("carries the proxy body limit the monthly Square import needs", () => {
    // 10 MB is the Next default and truncates a real ~15 MB monthly export,
    // surfacing as a socket hang up rather than a documented error.
    expect(nextConfig.experimental?.proxyClientMaxBodySize).toBe("192mb");
  });

  it("still proxies /api to the upstream with the prefix stripped", async () => {
    const rewrites = await nextConfig.rewrites?.();

    expect(rewrites).toEqual([
      { source: "/api/:path*", destination: "http://api:8000/:path*" },
    ]);
  });

  it("resolves output through resolveOutput rather than hard-coding it", () => {
    // In the test process VERCEL is unset, so this is the Docker branch.
    expect(nextConfig.output).toBe(resolveOutput(undefined));
  });
});
