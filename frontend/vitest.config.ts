import { fileURLToPath } from "node:url";

import { defineConfig } from "vitest/config";

/**
 * Tests cover `src/lib` — formatting, date-range rules, query serialisation and
 * the API client. Those are where a mistake produces a WRONG NUMBER or a
 * silently malformed request, which is the failure mode worth spending tests
 * on. Component rendering is left to the type checker and to looking at it.
 *
 * `environment: "node"` because nothing under test touches the DOM; the client
 * uses `fetch`, which Node provides and each test stubs.
 */
export default defineConfig({
  resolve: {
    // Mirrors the `@/*` path alias in tsconfig.json. Vitest does not read
    // tsconfig paths on its own, so without this every `@/lib/...` import in a
    // test fails to resolve.
    alias: {
      "@": fileURLToPath(new URL("./src", import.meta.url)),
    },
  },
  test: {
    environment: "node",
    include: ["src/**/*.test.ts"],
  },
});
