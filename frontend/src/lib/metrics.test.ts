import { describe, expect, it } from "vitest";

import { discountRatePercent } from "./metrics";

describe("discountRatePercent", () => {
  it("expresses discounts as a share of gross sales", () => {
    expect(discountRatePercent(50, 1000)).toBe(5);
    expect(discountRatePercent(0, 1000)).toBe(0);
  });

  it("is undefined, not zero, when there is nothing to divide by", () => {
    // The distinction the whole nullable-ratio convention exists to preserve:
    // "nothing was discounted" and "there were no sales" are different facts.
    expect(discountRatePercent(0, 0)).toBe(null);
    expect(discountRatePercent(500, 0)).toBe(null);
  });

  it("is undefined when gross sales is negative", () => {
    // Reachable when a period's refunds outweigh its sales; a percentage of a
    // negative denominator would be actively misleading.
    expect(discountRatePercent(100, -500)).toBe(null);
  });
});
