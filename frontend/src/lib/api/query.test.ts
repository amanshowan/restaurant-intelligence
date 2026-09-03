import { describe, expect, it } from "vitest";

import { buildQuery, withQuery } from "./query";

describe("buildQuery", () => {
  it("serialises plain values", () => {
    expect(buildQuery({ start_date: "2026-08-01", limit: 10 })).toBe(
      "start_date=2026-08-01&limit=10",
    );
  });

  it("repeats the key for array values", () => {
    // FastAPI reads `kind: list[ProductKind]` from REPEATED keys. A
    // comma-joined value arrives as one string and is rejected as an invalid
    // enum member, so this is the behaviour the product and basket endpoints
    // depend on.
    expect(buildQuery({ kind: ["menu_item", "custom_amount"] })).toBe(
      "kind=menu_item&kind=custom_amount",
    );
  });

  it("never comma-joins an array", () => {
    expect(buildQuery({ kind: ["menu_item", "custom_amount"] })).not.toContain(
      "%2C",
    );
  });

  it("omits null and undefined rather than sending them as strings", () => {
    expect(
      buildQuery({ limit: null, sort: undefined, granularity: "day" }),
    ).toBe("granularity=day");
  });

  it("omits an empty array entirely", () => {
    // An unset filter must not become `?kind=`, which FastAPI would try to
    // validate as an empty enum value.
    expect(buildQuery({ kind: [], granularity: "day" })).toBe(
      "granularity=day",
    );
  });

  it("keeps zero and false, which are meaningful values", () => {
    expect(buildQuery({ min_pair_orders: 0, flag: false })).toBe(
      "min_pair_orders=0&flag=false",
    );
  });

  it("percent-encodes values", () => {
    expect(buildQuery({ name: "Flat White" })).toBe("name=Flat+White");
    expect(buildQuery({ name: "Tea & Cake" })).toBe("name=Tea+%26+Cake");
  });

  it("preserves insertion order so URLs are stable", () => {
    expect(buildQuery({ b: 1, a: 2 })).toBe("b=1&a=2");
  });

  it("returns an empty string for no parameters", () => {
    expect(buildQuery({})).toBe("");
  });
});

describe("withQuery", () => {
  it("appends a query string", () => {
    expect(withQuery("/analytics/overview", { start_date: "2026-08-01" })).toBe(
      "/analytics/overview?start_date=2026-08-01",
    );
  });

  it("leaves the path untouched when there is nothing to append", () => {
    // No trailing "?" — it would be harmless but it is noise in a network log.
    expect(withQuery("/health", {})).toBe("/health");
    expect(withQuery("/health", { limit: undefined })).toBe("/health");
  });
});
