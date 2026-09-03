import { afterEach, describe, expect, it, vi } from "vitest";

import {
  FILE_SLOTS,
  MAX_FILE_BYTES,
  MAX_LABEL_LENGTH,
  MAX_REQUEST_BYTES,
  formatBytes,
  importErrorHeading,
  issueLabel,
  totalBytes,
  validateImportForm,
  wasReconciled,
} from "./imports";
import { buildSquareImportBody, importSquareExport } from "./api/endpoints";
import { ApiError } from "./api";
import type { ImportSummary } from "./api";

/** A stand-in upload of a given size; contents are never read client-side. */
function fakeFile(name: string, size = 1024): File {
  const file = new File(["x"], name, { type: "text/csv" });
  Object.defineProperty(file, "size", { value: size });
  return file;
}

function summary(overrides: Partial<ImportSummary> = {}): ImportSummary {
  return {
    batch_id: 1,
    status: "completed",
    label: "august-2026",
    period_start: "2026-08-01",
    period_end: "2026-08-31",
    orders_imported: 2717,
    order_items_imported: 7887,
    products_created: 141,
    products_reused: 0,
    rows_skipped: 57,
    issue_counts: { zero_value_transaction: 57, refund_channel_inherited: 2 },
    net_sales_pence: 4719408,
    reconciliation: {
      performed: true,
      matches: true,
      net_sales_pence_ours: 4719408,
      net_sales_pence_theirs: 4719408,
      line_totals_pence_ours: 4796139,
      line_totals_pence_theirs: 4796139,
      units_ours: 8752,
      units_theirs: 8752,
    },
    ...overrides,
  };
}

function stubFetch(body: unknown, status = 201) {
  const spy = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
    void input;
    void init;
    return Promise.resolve(
      new Response(JSON.stringify(body), {
        status,
        headers: { "Content-Type": "application/json" },
      }),
    );
  });
  vi.stubGlobal("fetch", spy);
  return spy;
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("buildSquareImportBody", () => {
  it("uses the field names the backend declares", () => {
    const form = buildSquareImportBody({
      transactions: fakeFile("tx.csv"),
      items: fakeFile("items.csv"),
      summary: fakeFile("summary.csv"),
      label: "august-2026",
    });

    expect(form.get("transactions")).toBeInstanceOf(File);
    expect(form.get("items")).toBeInstanceOf(File);
    expect(form.get("summary")).toBeInstanceOf(File);
    expect(form.get("label")).toBe("august-2026");
  });

  it("OMITS the summary part entirely when no summary is chosen", () => {
    // Not an empty part: the handler treats a part with no filename as no
    // file, and sending one anyway invites an empty summary to be spooled.
    for (const value of [null, undefined]) {
      const form = buildSquareImportBody({
        transactions: fakeFile("tx.csv"),
        items: fakeFile("items.csv"),
        summary: value,
      });
      expect(form.has("summary")).toBe(false);
    }
  });

  it("omits an absent or blank label rather than sending an empty string", () => {
    for (const label of [undefined, "", "   "]) {
      const form = buildSquareImportBody({
        transactions: fakeFile("tx.csv"),
        items: fakeFile("items.csv"),
        label,
      });
      expect(form.has("label")).toBe(false);
    }
  });

  it("trims a label", () => {
    const form = buildSquareImportBody({
      transactions: fakeFile("tx.csv"),
      items: fakeFile("items.csv"),
      label: "  august-2026  ",
    });
    expect(form.get("label")).toBe("august-2026");
  });
});

describe("importSquareExport", () => {
  it("POSTs multipart to the same-origin proxy without setting Content-Type", async () => {
    // The browser must generate Content-Type itself: it carries the boundary
    // token. Setting it by hand omits the boundary and the server cannot parse
    // a body that looks perfectly valid on the wire.
    const spy = stubFetch(summary());

    await importSquareExport({
      transactions: fakeFile("tx.csv"),
      items: fakeFile("items.csv"),
    });

    const [url, init] = spy.mock.calls[0];
    expect(url).toBe("/api/imports/square");
    expect(init?.method).toBe("POST");
    expect(init?.body).toBeInstanceOf(FormData);
    expect(
      Object.keys((init?.headers ?? {}) as Record<string, string>).map((k) =>
        k.toLowerCase(),
      ),
    ).not.toContain("content-type");
  });

  it("returns the parsed summary on 201", async () => {
    stubFetch(summary(), 201);

    const result = await importSquareExport({
      transactions: fakeFile("tx.csv"),
      items: fakeFile("items.csv"),
    });

    expect(result.batch_id).toBe(1);
    expect(result.status).toBe("completed");
    expect(result.net_sales_pence).toBe(4719408);
    expect(result.reconciliation.matches).toBe(true);
  });

  it("surfaces a duplicate import as the backend's own code", async () => {
    stubFetch(
      {
        detail: "transactions-2026-08.csv has already been imported",
        code: "duplicate_file",
      },
      409,
    );

    const error = await importSquareExport({
      transactions: fakeFile("tx.csv"),
      items: fakeFile("items.csv"),
    }).catch((caught: unknown) => caught);

    expect(error).toBeInstanceOf(ApiError);
    expect((error as ApiError).code).toBe("duplicate_file");
    expect((error as ApiError).status).toBe(409);
  });

  it("surfaces an invalid Square file as a 422 with its code", async () => {
    stubFetch(
      { detail: "not a UTF-16 tab-delimited export", code: "invalid_source_file" },
      422,
    );

    await expect(
      importSquareExport({
        transactions: fakeFile("tx.csv"),
        items: fakeFile("items.csv"),
      }),
    ).rejects.toMatchObject({ code: "invalid_source_file", status: 422 });
  });

  it("keeps per-field issues from a request-validation failure", async () => {
    stubFetch(
      {
        detail: "body.items: Field required",
        code: "validation_error",
        errors: [
          { location: "body.items", message: "Field required", type: "missing" },
        ],
      },
      422,
    );

    const error = (await importSquareExport({
      transactions: fakeFile("tx.csv"),
      items: fakeFile("items.csv"),
    }).catch((caught) => caught)) as ApiError;

    expect(error.issues).toHaveLength(1);
    expect(error.issues[0].location).toBe("body.items");
  });
});

describe("validateImportForm", () => {
  const both = {
    transactions: fakeFile("tx.csv"),
    items: fakeFile("items.csv"),
  };

  it("accepts the two required files with no summary and no label", () => {
    expect(validateImportForm(both, "")).toBeNull();
  });

  it("requires each mandatory file in the order an operator would fix them", () => {
    expect(validateImportForm({}, "")).toMatch(/transactions/i);
    expect(
      validateImportForm({ transactions: fakeFile("tx.csv") }, ""),
    ).toMatch(/items detail/i);
  });

  it("does not require the optional summary", () => {
    expect(validateImportForm(both, "")).toBeNull();
    expect(
      validateImportForm({ ...both, summary: fakeFile("s.csv") }, ""),
    ).toBeNull();
  });

  it("rejects a file above the server's per-file ceiling", () => {
    expect(
      validateImportForm(
        { ...both, transactions: fakeFile("tx.csv", MAX_FILE_BYTES + 1) },
        "",
      ),
    ).toMatch(/larger than/i);
  });

  it("rejects an empty file", () => {
    expect(
      validateImportForm({ ...both, items: fakeFile("items.csv", 0) }, ""),
    ).toMatch(/empty/i);
  });

  it("rejects a set above the whole-request ceiling", () => {
    // Each file is UNDER the 64 MB per-file limit, so only the combined
    // ceiling can reject this set — which is the rule under test.
    const each = 60 * 1024 * 1024;
    expect(each).toBeLessThan(MAX_FILE_BYTES);
    expect(each * 3).toBeGreaterThan(MAX_REQUEST_BYTES);

    expect(
      validateImportForm(
        {
          transactions: fakeFile("a.csv", each),
          items: fakeFile("b.csv", each),
          summary: fakeFile("c.csv", each),
        },
        "",
      ),
    ).toMatch(/limit for one import/i);
  });

  it("rejects a label longer than the column that stores it", () => {
    expect(validateImportForm(both, "x".repeat(MAX_LABEL_LENGTH + 1))).toMatch(
      /characters or fewer/i,
    );
    expect(validateImportForm(both, "x".repeat(MAX_LABEL_LENGTH))).toBeNull();
  });

  it("does not attempt to judge the file's contents", () => {
    // Square's format is asserted by the backend. A .txt named file with the
    // right bytes is valid; a .csv re-saved by a spreadsheet is not, and the
    // browser cannot tell either way.
    expect(validateImportForm({ ...both, items: fakeFile("anything.txt") }, "")).toBeNull();
  });
});

describe("totalBytes and formatBytes", () => {
  it("sums every selected slot", () => {
    expect(
      totalBytes({
        transactions: fakeFile("a", 1000),
        items: fakeFile("b", 2000),
        summary: fakeFile("c", 500),
      }),
    ).toBe(3500);
    expect(totalBytes({})).toBe(0);
  });

  it("formats a size readably", () => {
    expect(formatBytes(512)).toBe("512 B");
    expect(formatBytes(2048)).toBe("2.0 kB");
    expect(formatBytes(10 * 1024 * 1024)).toBe("10.0 MB");
  });
});

describe("wasReconciled", () => {
  it("is true only when a summary was supplied and the check ran", () => {
    expect(wasReconciled(summary())).toBe(true);
  });

  it("is FALSE when no summary was supplied, whatever `matches` says", () => {
    // The most misleading thing this screen could do is report a match from a
    // check that never happened. `matches` defaults true on the wire.
    const withoutSummary = summary({
      reconciliation: {
        performed: false,
        matches: true,
        net_sales_pence_ours: 0,
        net_sales_pence_theirs: 0,
        line_totals_pence_ours: 0,
        line_totals_pence_theirs: 0,
        units_ours: 0,
        units_theirs: 0,
      },
    });
    expect(wasReconciled(withoutSummary)).toBe(false);
  });
});

describe("error wording", () => {
  it("names the known failures in an operator's terms", () => {
    expect(importErrorHeading("duplicate_file")).toMatch(/already been imported/i);
    expect(importErrorHeading("invalid_source_file")).toMatch(/valid Square export/i);
    expect(importErrorHeading("reconciliation_failed")).toMatch(/reconcile/i);
  });

  it("falls back for a code it has not been taught", () => {
    expect(importErrorHeading("some_new_code")).toBe("The import failed");
  });
});

describe("issueLabel", () => {
  it("phrases the known row outcomes", () => {
    expect(issueLabel("zero_value_transaction")).toBe(
      "Zero-value transactions skipped",
    );
    expect(issueLabel("refund_channel_inherited")).toMatch(/channel was inherited/i);
  });

  it("shows an unknown code rather than hiding it", () => {
    // A row outcome the UI has not been taught about is still a fact.
    expect(issueLabel("some_new_outcome")).toBe("Some new outcome");
  });
});

describe("FILE_SLOTS", () => {
  it("declares two required files and one optional", () => {
    expect(FILE_SLOTS.filter((s) => s.required).map((s) => s.slot)).toEqual([
      "transactions",
      "items",
    ]);
    expect(FILE_SLOTS.filter((s) => !s.required).map((s) => s.slot)).toEqual([
      "summary",
    ]);
  });
});
