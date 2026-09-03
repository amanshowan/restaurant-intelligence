/**
 * Where the browser sends API requests.
 *
 * `/api` — same origin, always. The Next.js server rewrites `/api/*` onto the
 * FastAPI service (see next.config.ts), so the browser never makes a
 * cross-origin request and the backend needs no CORS policy.
 *
 * `NEXT_PUBLIC_*` variables are INLINED INTO THE CLIENT BUNDLE at build time,
 * so anything named that way is public by definition. This one holds a path and
 * nothing else. The upstream address — `http://api:8000`, a Docker service name
 * that resolves only inside the Compose network — is deliberately NOT exposed
 * this way: it is read server-side from `API_UPSTREAM_URL` and never reaches
 * the browser, where it would be both a leak and unresolvable.
 */
export const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? "/api";
