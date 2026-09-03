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

  experimental: {
    /**
     * How much request body the rewrite below will carry.
     *
     * Next.js buffers a proxied request body and DEFAULTS TO 10 MB. Past that
     * it logs "Request body exceeded 10MB … Only the first 10MB will be
     * available unless configured" and drops the rest, and the upstream then
     * sees a truncated multipart body and closes the socket — surfacing as
     * `Failed to proxy … socket hang up / ECONNRESET`. A real month of Square
     * exports is around 15 MB (UTF-16 doubles the byte size of plain ASCII),
     * so every genuine monthly import hit this.
     *
     * WHY THIS IS DELIBERATELY LARGER THAN THE BACKEND ACCEPTS
     * FastAPI remains the authority on upload size: 64 MB per file and 160 MB
     * per request (MAX_FILE_BYTES / MAX_REQUEST_BYTES in
     * backend/app/api/imports.py), and it answers an oversized upload with a
     * structured 413 the UI can explain. This proxy limit sits ABOVE that
     * ceiling so the proxy never becomes the thing that rejects an upload:
     * a request at the backend's 160 MB limit is larger than 160 MB on the
     * wire once multipart boundaries, part headers and filenames are added,
     * and a proxy limit set exactly at 160 MB would truncate a request the
     * backend would have accepted — failing it as an unexplained connection
     * reset instead of a documented error. 192 MB leaves ~20% headroom for
     * that overhead and keeps every size decision in one place.
     *
     * Renaming note: this option is `proxyClientMaxBodySize`, not
     * `middlewareClientMaxBodySize`. Next 16 deprecated the latter — it warns
     * on use, and setting both throws — and the runtime error message still
     * links to the old name.
     */
    proxyClientMaxBodySize: "192mb",
  },

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
