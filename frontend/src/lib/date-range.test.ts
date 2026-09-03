import { describe, expect, it } from "vitest";

import {
  MAX_RANGE_DAYS,
  addDays,
  businessToday,
  defaultDateRange,
  isValidIsoDate,
  rangeLengthDays,
  validateDateRange,
} from "./date-range";

describe("isValidIsoDate", () => {
  it("accepts a real calendar day", () => {
    expect(isValidIsoDate("2026-08-01")).toBe(true);
    expect(isValidIsoDate("2024-02-29")).toBe(true); // leap year
  });

  it("rejects a day that does not exist", () => {
    // These parse in JavaScript and roll forward silently, which is exactly
    // why the round-trip check is there.
    expect(isValidIsoDate("2026-02-30")).toBe(false);
    expect(isValidIsoDate("2026-13-01")).toBe(false);
    expect(isValidIsoDate("2025-02-29")).toBe(false); // not a leap year
  });

  it("rejects anything that is not yyyy-mm-dd", () => {
    expect(isValidIsoDate("")).toBe(false);
    expect(isValidIsoDate("01/08/2026")).toBe(false);
    expect(isValidIsoDate("2026-8-1")).toBe(false);
  });
});

describe("rangeLengthDays", () => {
  it("counts inclusively, matching the API's window", () => {
    expect(
      rangeLengthDays({ startDate: "2026-08-01", endDate: "2026-08-01" }),
    ).toBe(1);
    expect(
      rangeLengthDays({ startDate: "2026-08-01", endDate: "2026-08-31" }),
    ).toBe(31);
  });

  it("is unaffected by a British Summer Time boundary", () => {
    // The clocks go back on 25 October 2026. Counting in UTC milliseconds
    // keeps October 31 days rather than 31 days and an hour.
    expect(
      rangeLengthDays({ startDate: "2026-10-01", endDate: "2026-10-31" }),
    ).toBe(31);
  });

  it("returns null when an endpoint is not a date", () => {
    expect(rangeLengthDays({ startDate: "nope", endDate: "2026-08-31" })).toBe(
      null,
    );
  });
});

describe("validateDateRange", () => {
  it("accepts a well-formed range", () => {
    expect(
      validateDateRange({ startDate: "2026-08-01", endDate: "2026-08-31" }),
    ).toBe(null);
  });

  it("accepts a single-day range", () => {
    expect(
      validateDateRange({ startDate: "2026-08-01", endDate: "2026-08-01" }),
    ).toBe(null);
  });

  it("rejects a reversed range", () => {
    expect(
      validateDateRange({ startDate: "2026-08-31", endDate: "2026-08-01" }),
    ).toMatch(/must not be before/i);
  });

  it("rejects a range longer than the API's maximum", () => {
    // MAX_RANGE_DAYS mirrors backend/app/analytics/windows.py. Catching it
    // here saves a round trip that could only return 400.
    const start = "2026-01-01";
    const tooLong = addDays(start, MAX_RANGE_DAYS); // one past the limit
    expect(
      validateDateRange({ startDate: start, endDate: tooLong }),
    ).toMatch(/exceeds the maximum/i);

    const atLimit = addDays(start, MAX_RANGE_DAYS - 1);
    expect(validateDateRange({ startDate: start, endDate: atLimit })).toBe(null);
  });

  it("names the field that is malformed", () => {
    expect(
      validateDateRange({ startDate: "2026-02-30", endDate: "2026-08-31" }),
    ).toMatch(/start date/i);
    expect(
      validateDateRange({ startDate: "2026-08-01", endDate: "" }),
    ).toMatch(/end date/i);
  });
});

describe("businessToday", () => {
  it("reports the date in Europe/London, not the host's zone", () => {
    // 23:30 UTC on 31 July is already 1 August in London (BST, UTC+1). A
    // dashboard that used UTC would open on the wrong trading day for half
    // an hour every night in summer.
    expect(businessToday(new Date("2026-07-31T23:30:00Z"))).toBe("2026-08-01");
    // In winter London is UTC, so the same instant stays on the 31st.
    expect(businessToday(new Date("2026-12-31T23:30:00Z"))).toBe("2026-12-31");
  });
});

describe("defaultDateRange", () => {
  it("is the last COMPLETE calendar month", () => {
    expect(defaultDateRange(new Date("2026-09-03T10:00:00Z"))).toEqual({
      startDate: "2026-08-01",
      endDate: "2026-08-31",
    });
  });

  it("does not change during the month it reports", () => {
    // The whole point of a complete month: the range is the same on the 1st
    // and on the 30th, so figures do not drift under the operator.
    //
    // Both instants are chosen to be unambiguously inside September in
    // LONDON. 2026-09-30T23:00:00Z would not be: London is on BST that day,
    // so 23:00 UTC is already 1 October locally and the answer correctly
    // becomes September itself.
    const first = defaultDateRange(new Date("2026-09-01T00:30:00Z"));
    const last = defaultDateRange(new Date("2026-09-30T12:00:00Z"));
    expect(first).toEqual(last);
    expect(first).toEqual({ startDate: "2026-08-01", endDate: "2026-08-31" });
  });

  it("follows the business timezone across a late-evening boundary", () => {
    // 23:00 UTC on 30 September is 1 October in London, so the last complete
    // month rolls over an hour before it would in UTC. This is the behaviour
    // that keeps the dashboard on the same trading day as the till.
    expect(defaultDateRange(new Date("2026-09-30T23:00:00Z"))).toEqual({
      startDate: "2026-09-01",
      endDate: "2026-09-30",
    });
  });

  it("rolls back across a year boundary", () => {
    expect(defaultDateRange(new Date("2026-01-15T12:00:00Z"))).toEqual({
      startDate: "2025-12-01",
      endDate: "2025-12-31",
    });
  });

  it("gets February right in a leap year", () => {
    expect(defaultDateRange(new Date("2024-03-10T12:00:00Z"))).toEqual({
      startDate: "2024-02-01",
      endDate: "2024-02-29",
    });
  });

  it("always produces a range the API will accept", () => {
    for (const iso of [
      "2026-01-01T00:00:00Z",
      "2026-03-29T02:30:00Z", // the BST transition
      "2026-09-03T10:00:00Z",
      "2026-12-31T23:59:00Z",
    ]) {
      expect(validateDateRange(defaultDateRange(new Date(iso)))).toBe(null);
    }
  });
});
