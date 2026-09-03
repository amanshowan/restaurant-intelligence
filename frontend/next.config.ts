import type { NextConfig } from "next";

/**
 * The upstream FastAPI service. SERVER-ONLY — this file runs in the Next.js
 * server process, never in the browser.
 *
 * `http://api:8000` is a Docker Compose service name, resolvable only on the
 * Compose network. It is read from the environment rather than hard-coded so
 * the same image works against a differently-addressed backend, and it is
 * deliberately not a `NEXT_PUBLIC_*` variable: that would inline it into the
 * client bundle, where it is simultaneously a leak of internal topology and an
 * address no browser can resolve.
 */
const API_UPSTREAM_URL = process.env.API_UPSTREAM_URL ?? "http://api:8000";

const nextConfig: NextConfig = {
  /**
   * Traces the exact files the server needs into `.next/standalone`, so the
   * production stage of the Dockerfile can copy a self-contained server
   * without the source or the dev dependencies. Has no effect on `next dev`.
   */
  output: "standalone",

  /**
   * Same-origin API proxy.
   *
   *   browser → localhost:3000/api/analytics/overview
   *           → (this rewrite, server-side)
   *           → http://api:8000/analytics/overview
   *
   * Chosen over adding `CORSMiddleware` to FastAPI. A rewrite means the browser
   * only ever talks to its own origin, so there is no preflight, no
   * `Access-Control-Allow-Origin` list to keep in step with every environment,
   * and no origin-allowing configuration that could be got wrong in a way that
   * matters. It also keeps the backend unaware that a browser exists, which is
   * the property that lets the API stay a plain HTTP service.
   *
   * The `/api` prefix is stripped: the backend's routes are `/analytics/...`
   * and `/health`, and it should not have to know it is being proxied.
   *
   * Rewrites are read from this config when the server boots, so
   * `API_UPSTREAM_URL` is a runtime value for `next dev` and `next start`.
   * NOTE: `next build` also writes them into `routes-manifest.json`, so a
   * standalone production image bakes in whatever was set at build time. That
   * is fine for a target fixed at deploy time; a per-environment upstream would
   * want this reimplemented as a Route Handler, which reads the environment on
   * each request.
   */
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: `${API_UPSTREAM_URL}/:path*`,
      },
    ];
  },
};

export default nextConfig;
