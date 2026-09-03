import { describe, expect, it } from "vitest";

import {
  NOT_APPLICABLE,
  formatAxisMoney,
  formatCount,
  formatDateRangeLabel,
  formatIsoDate,
  formatMoneyPence,
  formatPercent,
} from "./format";

describe("formatMoneyPence", () => {
  it("renders integer pence as GBP with thousands separators", () => {
    expect(formatMoneyPence(1234567)).toBe("£12,345.67");
    expect(formatMoneyPence(100)).toBe("£1.00");
    expect(formatMoneyPence(0)).toBe("£0.00");
  });

  it("pads the minor units so pence are never truncated", () => {
    // 1205 pence is £12.05, not £12.5 — the bug this test exists to catch.
    expect(formatMoneyPence(1205)).toBe("£12.05");
    expect(formatMoneyPence(1250)).toBe("£12.50");
    expect(formatMoneyPence(5)).toBe("£0.05");
  });

  it("puts the sign outside the currency symbol", () => {
    // A period whose refunds outweigh its sales is a real, reachable state.
    expect(formatMoneyPence(-1234)).toBe("-£12.34");
    expect(formatMoneyPence(-5)).toBe("-£0.05");
  });

  it("stays exact at magnitudes a float would round", () => {
    expect(formatMoneyPence(999999999)).toBe("£9,999,999.99");
  });

  it("degrades rather than rendering NaN", () => {
    expect(formatMoneyPence(Number.NaN)).toBe(NOT_APPLICABLE);
    expect(formatMoneyPence(Number.POSITIVE_INFINITY)).toBe(NOT_APPLICABLE);
  });
});

describe("formatCount", () => {
  it("groups thousands", () => {
    expect(formatCount(2715)).toBe("2,715");
    expect(formatCount(0)).toBe("0");
    expect(formatCount(999)).toBe("999");
  });
});

describe("formatPercent", () => {
  it("formats a ratio to one decimal place by default", () => {
    expect(formatPercent(12.34)).toBe("12.3%");
    expect(formatPercent(0)).toBe("0.0%");
  });

  it("renders an undefined ratio as a dash, never as zero", () => {
    // The backend returns null when the denominator is zero. Showing "0.0%"
    // would assert a fact the data does not support.
    expect(formatPercent(null)).toBe(NOT_APPLICABLE);
    expect(formatPercent(undefined)).toBe(NOT_APPLICABLE);
  });

  it("honours a requested precision", () => {
    expect(formatPercent(12.345, 2)).toBe("12.35%");
    expect(formatPercent(12.345, 0)).toBe("12%");
  });
});

describe("formatIsoDate", () => {
  it("formats an ISO calendar date without shifting it", () => {
    // Formatted as UTC on purpose: through a local timezone west of Greenwich
    // this would render as 31 Jul.
    expect(formatIsoDate("2026-08-01")).toBe("1 Aug 2026");
    expect(formatIsoDate("2026-12-31")).toBe("31 Dec 2026");
  });

  it("returns the input unchanged when it is not a date", () => {
    expect(formatIsoDate("not-a-date")).toBe("not-a-date");
  });
});

describe("formatDateRangeLabel", () => {
  it("joins the two endpoints", () => {
    expect(formatDateRangeLabel("2026-08-01", "2026-08-31")).toBe(
      "1 Aug 2026 – 31 Aug 2026",
    );
  });

  it("collapses a single-day range to one date", () => {
    expect(formatDateRangeLabel("2026-08-01", "2026-08-01")).toBe("1 Aug 2026");
  });
});

describe("formatAxisMoney", () => {
  it("shows exact pounds below a thousand", () => {
    expect(formatAxisMoney(55000)).toBe("£550");
    expect(formatAxisMoney(0)).toBe("£0");
  });

  it("keeps a decimal in the thousands so two ticks cannot share a label", () => {
    // The bug this exists for: rounding to whole thousands rendered £1,650 and
    // £2,100 both as "£2k", putting two different ticks under one label.
    expect(formatAxisMoney(170000)).toBe("£1.7k");
    expect(formatAxisMoney(210000)).toBe("£2.1k");
    expect(formatAxisMoney(170000)).not.toBe(formatAxisMoney(210000));
  });

  it("drops a trailing .0", () => {
    expect(formatAxisMoney(200000)).toBe("£2k");
  });

  it("rounds to whole thousands once the axis is large", () => {
    expect(formatAxisMoney(4719408)).toBe("£47k");
  });

  it("puts the sign outside the symbol, like formatMoneyPence", () => {
    expect(formatAxisMoney(-170000)).toBe("-£1.7k");
    expect(formatAxisMoney(-55000)).toBe("-£550");
  });
});
