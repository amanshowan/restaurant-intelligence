// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { AskResponse, EvidenceBundle } from "@/lib/api";

import { AskDashboard } from "./ask-dashboard";

/**
 * What this page must never do is a property of the RENDERED page: a forecast
 * shown as a record, an internal field shown to a user, a stale answer left
 * under a new question, or a second request fired while one is in flight.
 * Those claims live in JSX and in a hook, so they are tested against a DOM.
 *
 * EVERY RESPONSE HERE IS INVENTED. Nothing calls the real backend and nothing
 * calls a model provider — the fetch is stubbed, so the suite is deterministic
 * and costs nothing to run in CI. Assertions check that the page renders what
 * the API SAID, never that the API says anything in particular.
 */

const PERIOD = { start_date: "2026-08-01", end_date: "2026-08-31", days: 31 };

function measuredBundle(overrides: Partial<EvidenceBundle> = {}): EvidenceBundle {
  return {
    operation: "overview",
    status: "ok",
    parameters: { start_date: "2026-08-01", end_date: "2026-08-31" },
    period: PERIOD,
    comparison_period: null,
    rows: [],
    totals: { net_sales_pence: 4719408 },
    field_provenance: { net_sales_pence: "measured" },
    units: { net_sales_pence: "pence" },
    limits: null,
    forecast: null,
    product_resolution: null,
    warnings: [],
    ...overrides,
  };
}

function forecastBundle(): EvidenceBundle {
  return measuredBundle({
    operation: "forecast",
    period: null,
    parameters: { operation: "forecast", horizon_days: 14 },
    rows: [{ date: "2026-09-01", predicted_value: 130552 }],
    totals: {},
    field_provenance: { predicted_value: "forecast" },
    units: { predicted_value: "pence" },
    limits: {
      returned_rows: 14,
      applied_limit: 14,
      maximum_rows: 14,
      available_rows: 14,
      truncated: false,
    },
    forecast: {
      method: "ridge_holiday",
      trained_through: "2026-08-31",
      forecast_start: "2026-09-01",
      forecast_end: "2026-09-14",
      horizon_days: 14,
      unit: "pence",
      historical_wape_percent: 12.690493,
      historical_mae: 17969.85,
      backtest_folds: 17,
      backtest_horizon_days: 14,
    },
  });
}

function answer(overrides: Partial<AskResponse> = {}): AskResponse {
  return {
    question: "How did we perform last month?",
    status: "answered",
    answer: "Net sales were £47,194.08, up 4.79% on July.",
    steps: [
      {
        operation: "overview",
        purpose: "Headline KPIs for August versus July.",
        evidence_status: "ok",
      },
    ],
    evidence: [measuredBundle()],
    candidates: [],
    contains_forecast: false,
    warnings: [],
    model: "claude-opus-5",
    usage: { input_tokens: 12886, output_tokens: 397 },
    ...overrides,
  };
}

/** Resolves every ask request with `body`, after an optional delay. */
function stubAsk(body: unknown, { status = 200, delayMs = 0 } = {}) {
  // The parameters are declared even though they are unused: without them the
  // spy's call tuples are typed empty, and `calls[0][1].body` stops compiling.
  const spy = vi.fn(
    (input: RequestInfo | URL, init?: RequestInit) =>
      new Promise<Response>((resolve) => {
        void input;
        void init;
        const respond = () =>
          resolve(
            new Response(JSON.stringify(body), {
              status,
              headers: { "Content-Type": "application/json" },
            }),
          );
        if (delayMs > 0) setTimeout(respond, delayMs);
        else respond();
      }),
  );
  vi.stubGlobal("fetch", spy);
  return spy;
}

/** Stubs a sequence of responses, one per call, so ordering can be tested. */
function stubAskSequence(bodies: { body: unknown; delayMs: number }[]) {
  let call = 0;
  const spy = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
    void input;
    void init;
    const { body, delayMs } = bodies[Math.min(call++, bodies.length - 1)];
    return new Promise<Response>((resolve) =>
      setTimeout(
        () =>
          resolve(
            new Response(JSON.stringify(body), {
              status: 200,
              headers: { "Content-Type": "application/json" },
            }),
          ),
        delayMs,
      ),
    );
  });
  vi.stubGlobal("fetch", spy);
  return spy;
}

function ask(text: string) {
  fireEvent.change(screen.getByLabelText(/ask a question about your trading/i), {
    target: { value: text },
  });
  fireEvent.click(screen.getByRole("button", { name: "Ask" }));
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

describe("asking a question", () => {
  it("sends nothing until a question is submitted", () => {
    const spy = stubAsk(answer());

    render(<AskDashboard />);

    expect(spy).not.toHaveBeenCalled();
  });

  it("posts the typed question to the same-origin backend path", async () => {
    const spy = stubAsk(answer());

    render(<AskDashboard />);
    ask("How did we perform last month?");

    await screen.findByText(/net sales were/i);
    const [url, init] = spy.mock.calls[0];
    expect(String(url)).toBe("/api/analytics/ask");
    expect(init?.method).toBe("POST");
    expect(JSON.parse(String(init?.body))).toEqual({
      question: "How did we perform last month?",
    });
  });

  it("never contacts a model provider from the browser", async () => {
    const spy = stubAsk(answer());

    render(<AskDashboard />);
    ask("How did we perform last month?");
    await screen.findByText(/net sales were/i);

    for (const [url] of spy.mock.calls) {
      expect(String(url).startsWith("/api/")).toBe(true);
      expect(String(url)).not.toMatch(/anthropic|api\.openai|https?:/i);
    }
  });

  it("submits an example chip directly", async () => {
    const spy = stubAsk(answer());

    render(<AskDashboard />);
    fireEvent.click(screen.getByRole("button", { name: "What are our busiest days?" }));

    await screen.findByText(/net sales were/i);
    expect(JSON.parse(String(spy.mock.calls[0][1]?.body))).toEqual({
      question: "What are our busiest days?",
    });
  });

  it("submits on Enter, which the hint promises", async () => {
    const spy = stubAsk(answer());

    render(<AskDashboard />);
    const field = screen.getByLabelText(/ask a question about your trading/i);
    fireEvent.change(field, { target: { value: "How did we perform last month?" } });
    fireEvent.keyDown(field, { key: "Enter" });

    await screen.findByText(/net sales were/i);
    expect(JSON.parse(String(spy.mock.calls[0][1]?.body))).toEqual({
      question: "How did we perform last month?",
    });
  });

  it("does not submit on Shift+Enter, which inserts a newline instead", () => {
    const spy = stubAsk(answer());

    render(<AskDashboard />);
    const field = screen.getByLabelText(/ask a question about your trading/i);
    fireEvent.change(field, { target: { value: "Two lines" } });
    fireEvent.keyDown(field, { key: "Enter", shiftKey: true });

    expect(spy).not.toHaveBeenCalled();
  });

  it("ignores Enter while a request is already in flight", async () => {
    const spy = stubAsk(answer(), { delayMs: 50 });

    render(<AskDashboard />);
    const field = screen.getByLabelText(/ask a question about your trading/i);
    fireEvent.change(field, { target: { value: "How did we perform last month?" } });
    fireEvent.keyDown(field, { key: "Enter" });
    fireEvent.keyDown(field, { key: "Enter" });

    await screen.findByText(/net sales were/i);
    expect(spy).toHaveBeenCalledTimes(1);
  });

  it("refuses an empty question without sending anything", () => {
    const spy = stubAsk(answer());

    render(<AskDashboard />);
    fireEvent.click(screen.getByRole("button", { name: "Ask" }));

    expect(screen.getByText("Type a question first.")).toBeTruthy();
    expect(spy).not.toHaveBeenCalled();
  });
});

describe("a measured answer", () => {
  it("shows the question, the prose and the operations used", async () => {
    stubAsk(answer());

    render(<AskDashboard />);
    ask("How did we perform last month?");

    await screen.findByText(/net sales were £47,194.08/i);
    expect(screen.getByText(/answered using headline figures/i)).toBeTruthy();
  });

  it("does not announce predictions when there are none", async () => {
    stubAsk(answer());

    render(<AskDashboard />);
    ask("How did we perform last month?");
    await screen.findByText(/net sales were/i);

    expect(screen.queryByText(/this answer includes predictions/i)).toBeNull();
    expect(screen.getByText("Measured")).toBeTruthy();
  });

  it("renders bold and bullet lists rather than raw asterisks", async () => {
    stubAsk(
      answer({
        answer: "Busiest days:\n\n- **Sunday** — £91,621.40\n- **Saturday** — £90,479.53",
      }),
    );

    render(<AskDashboard />);
    ask("What are our busiest days?");

    await screen.findByText("Sunday");
    expect(screen.getAllByRole("listitem").some((item) =>
      item.textContent?.includes("£91,621.40"),
    )).toBe(true);
    expect(screen.queryByText(/\*\*Sunday\*\*/)).toBeNull();
  });
});

describe("a forecast answer", () => {
  it("labels the answer as containing predictions", async () => {
    stubAsk(
      answer({
        question: "What does the next two weeks look like?",
        answer: "The model projects £21,173.86 over the fortnight.",
        steps: [
          { operation: "forecast", purpose: "Next 14 days.", evidence_status: "ok" },
        ],
        evidence: [forecastBundle()],
        contains_forecast: true,
      }),
    );

    render(<AskDashboard />);
    ask("What does the next two weeks look like?");

    await screen.findByText(/this answer includes predictions/i);
    expect(screen.getByText(/not a record of trade/i)).toBeTruthy();
    expect(screen.getByText("Prediction")).toBeTruthy();
  });

  it("marks the forecast from the EVIDENCE even if the prose reads as fact", async () => {
    // The flag is derived server-side from the evidence, not from wording, so
    // a badly-worded answer is still labelled.
    stubAsk(
      answer({
        answer: "Sales were £21,173.86 over the next fortnight.",
        evidence: [forecastBundle()],
        contains_forecast: true,
      }),
    );

    render(<AskDashboard />);
    ask("What does the next two weeks look like?");

    await screen.findByText(/this answer includes predictions/i);
  });

  it("states the last real day and calls WAPE past error, not accuracy", async () => {
    stubAsk(
      answer({ evidence: [forecastBundle()], contains_forecast: true }),
    );

    render(<AskDashboard />);
    ask("What does the next two weeks look like?");

    await screen.findByText(/this answer includes predictions/i);
    expect(screen.getByText(/real data ends 31 Aug 2026/i)).toBeTruthy();
    expect(screen.getByText(/typical error 12.7% on days the model had never seen/i)).toBeTruthy();
    expect(screen.getByText(/past error, not a confidence level/i)).toBeTruthy();
    expect(screen.queryByText(/accurate/i)).toBeNull();
  });
});

describe("evidence and provenance", () => {
  it("summarises each operation with its period and record count", async () => {
    stubAsk(
      answer({
        evidence: [
          measuredBundle({
            operation: "product_movers",
            comparison_period: {
              start_date: "2026-07-01",
              end_date: "2026-07-31",
              days: 31,
            },
            limits: {
              returned_rows: 25,
              applied_limit: 25,
              maximum_rows: 50,
              available_rows: 140,
              truncated: true,
            },
          }),
        ],
      }),
    );

    render(<AskDashboard />);
    ask("Which products are declining?");

    await screen.findByText("What this answer is based on");
    expect(screen.getByText("Product movement")).toBeTruthy();
    expect(screen.getByText("1 Aug 2026 – 31 Aug 2026")).toBeTruthy();
    expect(screen.getByText("25 records of 140")).toBeTruthy();
    // Dates are formatted, never shown as raw ISO strings.
    expect(screen.getByText("1 Jul 2026 – 31 Jul 2026")).toBeTruthy();
    expect(screen.queryByText(/2026-07-01/)).toBeNull();
  });

  it("preserves the backend's warnings", async () => {
    stubAsk(
      answer({
        warnings: [
          "Truncated: 25 of 140 qualifying rows are included.",
          "Truncated: 25 of 140 qualifying rows are included.",
          "Movement is measured, not judged.",
        ],
      }),
    );

    render(<AskDashboard />);
    ask("Which products are declining?");

    await screen.findByText("Worth knowing");
    // Repeated warnings are shown once, not twice.
    expect(screen.getAllByText(/truncated: 25 of 140/i)).toHaveLength(1);
    expect(screen.getByText(/measured, not judged/i)).toBeTruthy();
  });

  it("names the resolved product rather than the raw id", async () => {
    stubAsk(
      answer({
        evidence: [
          measuredBundle({
            operation: "product_attachments",
            product_resolution: {
              requested_name: "The Big Breakfast",
              requested_variation: "Regular",
              requested_product_id: null,
              resolved: {
                product_id: 25,
                name: "The Big Breakfast",
                variation: "Regular",
                kind: "menu_item",
              },
              candidates: [],
            },
          }),
        ],
      }),
    );

    render(<AskDashboard />);
    ask("What goes with The Big Breakfast?");

    await screen.findByText("What this answer is based on");
    expect(screen.getByText("The Big Breakfast (Regular)")).toBeTruthy();
  });
});

describe("nothing internal is rendered", () => {
  it("shows no prompts, schemas, keys, SQL or raw evidence JSON", async () => {
    stubAsk(
      answer({
        evidence: [forecastBundle(), measuredBundle()],
        contains_forecast: true,
        warnings: ["Truncated: 3 of 9 rows."],
      }),
    );

    render(<AskDashboard />);
    ask("What does the next two weeks look like?");
    await screen.findByText("What this answer is based on");

    const page = document.body.textContent ?? "";
    for (const forbidden of [
      "sk-ant",
      "ANTHROPIC_API_KEY",
      "system prompt",
      "SELECT ",
      "json_schema",
      "field_provenance",
      "net_sales_pence",
      "predicted_value",
      "Traceback",
      "postgresql://",
    ]) {
      expect(page).not.toContain(forbidden);
    }
  });

  it("does not show the planner's internal purpose text as a finding", async () => {
    stubAsk(
      answer({
        steps: [
          {
            operation: "overview",
            purpose: "INTERNAL-PLANNER-NOTE-42",
            evidence_status: "ok",
          },
        ],
      }),
    );

    render(<AskDashboard />);
    ask("How did we perform last month?");
    await screen.findByText(/net sales were/i);

    expect(document.body.textContent).not.toContain("INTERNAL-PLANNER-NOTE-42");
  });
});

describe("loading and duplicate submission", () => {
  it("shows a waiting state naming the question", async () => {
    stubAsk(answer(), { delayMs: 50 });

    render(<AskDashboard />);
    ask("How did we perform last month?");

    expect(screen.getByText("Working on it")).toBeTruthy();
    // Scoped to the waiting panel: the textarea holds the same text, and the
    // quotes around it are separate text nodes.
    const waiting = screen.getByText("Working on it").closest("section");
    expect(waiting?.textContent).toContain("How did we perform last month?");
    await screen.findByText(/net sales were/i);
    expect(screen.queryByText("Working on it")).toBeNull();
  });

  it("disables the submit button and the chips while a request is active", async () => {
    stubAsk(answer(), { delayMs: 50 });

    render(<AskDashboard />);
    ask("How did we perform last month?");

    const submit = screen.getByRole("button", { name: "Thinking…" });
    expect((submit as HTMLButtonElement).disabled).toBe(true);
    expect(
      (screen.getByRole("button", {
        name: "What are our busiest days?",
      }) as HTMLButtonElement).disabled,
    ).toBe(true);

    await screen.findByText(/net sales were/i);
  });

  it("ignores a second submit while one is in flight", async () => {
    const spy = stubAsk(answer(), { delayMs: 50 });

    render(<AskDashboard />);
    ask("How did we perform last month?");
    fireEvent.click(screen.getByRole("button", { name: "Thinking…" }));
    fireEvent.click(screen.getByRole("button", { name: "Thinking…" }));

    await screen.findByText(/net sales were/i);
    expect(spy).toHaveBeenCalledTimes(1);
  });

  it("hides the previous answer while a new question is being answered", async () => {
    stubAskSequence([
      { body: answer({ answer: "FIRST ANSWER" }), delayMs: 0 },
      { body: answer({ answer: "SECOND ANSWER" }), delayMs: 50 },
    ]);

    render(<AskDashboard />);
    ask("First question?");
    await screen.findByText("FIRST ANSWER");

    ask("Second question?");
    // The old answer must not sit beneath the new question.
    expect(screen.queryByText("FIRST ANSWER")).toBeNull();
    expect(screen.getByText("Working on it")).toBeTruthy();

    await screen.findByText("SECOND ANSWER");
  });
});

describe("cancellation and stale responses", () => {
  /**
   * Note on what CAN happen here. Duplicate-submit prevention means the UI
   * cannot start a second question while one is in flight, so two overlapping
   * ask requests are not reachable through the form. Stale protection is
   * therefore defence in depth, and it is tested as what it actually is: the
   * request carries an abort signal, abandoning it aborts, and a response that
   * arrives after that is not rendered.
   */
  it("gives every request an abort signal", async () => {
    const spy = stubAsk(answer());

    render(<AskDashboard />);
    ask("How did we perform last month?");
    await screen.findByText(/net sales were/i);

    expect(spy.mock.calls[0][1]?.signal).toBeInstanceOf(AbortSignal);
    expect((spy.mock.calls[0][1]?.signal as AbortSignal).aborted).toBe(false);
  });

  it("aborts the request in flight when the page is left", async () => {
    const spy = stubAsk(answer(), { delayMs: 200 });

    const { unmount } = render(<AskDashboard />);
    ask("How did we perform last month?");
    const signal = spy.mock.calls[0][1]?.signal as AbortSignal;
    expect(signal.aborted).toBe(false);

    unmount();
    expect(signal.aborted).toBe(true);
  });

  it("renders nothing from a response that lands after its request was abandoned", async () => {
    const spy = stubAsk(answer({ answer: "ABANDONED ANSWER" }), { delayMs: 60 });

    const { unmount } = render(<AskDashboard />);
    ask("How did we perform last month?");
    unmount();

    // Let the abandoned response settle, then confirm nothing rendered it and
    // no unhandled state update was attempted.
    await new Promise((resolve) => setTimeout(resolve, 120));
    expect(document.body.textContent).not.toContain("ABANDONED ANSWER");
    expect(spy).toHaveBeenCalledTimes(1);
  });

  it("keeps the newest answer when the same question is asked twice", async () => {
    stubAskSequence([
      { body: answer({ answer: "FIRST ANSWER" }), delayMs: 10 },
      { body: answer({ answer: "SECOND ANSWER" }), delayMs: 10 },
    ]);

    render(<AskDashboard />);
    ask("How did we perform last month?");
    await screen.findByText("FIRST ANSWER");

    // Same text: the submission counter, not the question, keys the request,
    // so asking again genuinely re-runs it rather than being deduplicated.
    fireEvent.click(screen.getByRole("button", { name: "Ask" }));
    await screen.findByText("SECOND ANSWER");
    expect(screen.queryByText("FIRST ANSWER")).toBeNull();
  });
});

describe("failure states", () => {
  const failures = [
    {
      code: "llm_not_configured",
      status: 503,
      heading: /ai answers are not switched on/i,
      retryable: false,
    },
    {
      code: "llm_timeout",
      status: 504,
      heading: /the model took too long/i,
      retryable: true,
    },
    {
      code: "llm_unavailable",
      status: 503,
      heading: /the model provider is unavailable/i,
      retryable: true,
    },
    {
      code: "llm_refused",
      status: 502,
      heading: /the model declined to answer/i,
      retryable: true,
    },
    {
      code: "llm_invalid_response",
      status: 502,
      heading: /could not be turned into an analysis/i,
      retryable: true,
    },
  ];

  for (const failure of failures) {
    it(`explains ${failure.code} in its own terms`, async () => {
      stubAsk(
        { detail: "backend explanation", code: failure.code },
        { status: failure.status },
      );

      render(<AskDashboard />);
      ask("How did we perform last month?");

      await screen.findByText(failure.heading);
      const alert = screen.getByRole("alert");
      expect(within(alert).getByText(new RegExp(failure.code))).toBeTruthy();
      expect(
        within(alert).queryByRole("button", { name: /try again/i }) !== null,
      ).toBe(failure.retryable);
    });
  }

  it("offers no retry when the feature is simply switched off", async () => {
    stubAsk(
      { detail: "ANTHROPIC_API_KEY is not set.", code: "llm_not_configured" },
      { status: 503 },
    );

    render(<AskDashboard />);
    ask("How did we perform last month?");

    await screen.findByText(/ai answers are not switched on/i);
    expect(screen.getByText(/every other page works as normal/i)).toBeTruthy();
    expect(screen.queryByRole("button", { name: /try again/i })).toBeNull();
  });

  it("distinguishes an unreachable backend from a rejected question", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn((input: RequestInfo | URL) => {
        void input;
        return Promise.reject(new TypeError("network down"));
      }),
    );

    render(<AskDashboard />);
    ask("How did we perform last month?");

    await screen.findByText(/cannot reach the api/i);
  });

  it("retries the same question when asked to", async () => {
    const spy = stubAsk({ detail: "down", code: "llm_unavailable" }, { status: 503 });

    render(<AskDashboard />);
    ask("How did we perform last month?");
    await screen.findByText(/the model provider is unavailable/i);

    fireEvent.click(screen.getByRole("button", { name: /try again/i }));
    await waitFor(() => expect(spy).toHaveBeenCalledTimes(2));
    expect(JSON.parse(String(spy.mock.calls[1][1]?.body))).toEqual({
      question: "How did we perform last month?",
    });
  });
});

describe("clarification and unsupported answers", () => {
  it("asks which product was meant and offers the candidates", async () => {
    stubAsk(
      answer({
        status: "clarification_needed",
        answer: '"Caffe Latte" matches more than one item on the menu.',
        candidates: [
          { product_id: 4, name: "Caffe Latte", variation: "Large", kind: "menu_item" },
          { product_id: 5, name: "Caffe Latte", variation: "Regular", kind: "menu_item" },
        ],
        evidence: [],
      }),
    );

    render(<AskDashboard />);
    ask("How is the latte doing?");

    await screen.findByText("Which one did you mean?");
    expect(screen.getByRole("button", { name: "Caffe Latte (Large)" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Caffe Latte (Regular)" })).toBeTruthy();
  });

  it("re-asks naming the chosen variation", async () => {
    const spy = stubAsk(
      answer({
        status: "clarification_needed",
        answer: "Ambiguous.",
        candidates: [
          { product_id: 4, name: "Caffe Latte", variation: "Large", kind: "menu_item" },
        ],
        evidence: [],
      }),
    );

    render(<AskDashboard />);
    ask("How is the latte doing?");
    await screen.findByText("Which one did you mean?");

    fireEvent.click(screen.getByRole("button", { name: "Caffe Latte (Large)" }));

    await waitFor(() => expect(spy).toHaveBeenCalledTimes(2));
    expect(JSON.parse(String(spy.mock.calls[1][1]?.body)).question).toBe(
      "How is the latte doing? Specifically, Caffe Latte (Large).",
    );
  });

  it("reports an unanswerable question without inventing an analysis", async () => {
    stubAsk(
      answer({
        status: "unsupported",
        answer: "This system holds no cost data, so margin cannot be computed.",
        steps: [],
        evidence: [],
      }),
    );

    render(<AskDashboard />);
    ask("What is our profit margin?");

    await screen.findByText(/cannot be answered from this data/i);
    expect(screen.getByText(/no cost data/i)).toBeTruthy();
    expect(screen.queryByText("What this answer is based on")).toBeNull();
    expect(screen.getByText(/no analysis was run and nothing was guessed/i)).toBeTruthy();
  });
});

describe("accessibility", () => {
  it("labels the question field and describes how to submit", () => {
    stubAsk(answer());

    render(<AskDashboard />);
    const field = screen.getByLabelText(/ask a question about your trading/i);

    expect(field.tagName).toBe("TEXTAREA");
    const described = field.getAttribute("aria-describedby") ?? "";
    expect(described.length).toBeGreaterThan(0);
    expect(document.getElementById(described.split(" ")[0])?.textContent).toMatch(
      /enter to send/i,
    );
  });

  it("marks the result area as a live region and as busy while waiting", async () => {
    stubAsk(answer(), { delayMs: 50 });

    render(<AskDashboard />);
    ask("How did we perform last month?");

    const live = document.querySelector('[aria-live="polite"][aria-busy="true"]');
    expect(live).not.toBeNull();

    await screen.findByText(/net sales were/i);
    expect(
      document.querySelector('[aria-live="polite"][aria-busy="false"]'),
    ).not.toBeNull();
  });

  it("announces a failure assertively and marks the field invalid on a local problem", () => {
    stubAsk(answer());

    render(<AskDashboard />);
    fireEvent.click(screen.getByRole("button", { name: "Ask" }));

    const field = screen.getByLabelText(/ask a question about your trading/i);
    expect(field.getAttribute("aria-invalid")).toBe("true");
    expect(screen.getByRole("alert").textContent).toMatch(/type a question first/i);
  });

  it("keeps the question field focusable while a request is in flight", async () => {
    // Read-only rather than disabled: disabling a focused field moves focus to
    // the body and drops a screen-reader user out of the form.
    stubAsk(answer(), { delayMs: 50 });

    render(<AskDashboard />);
    ask("How did we perform last month?");

    const field = screen.getByLabelText(
      /ask a question about your trading/i,
    ) as HTMLTextAreaElement;
    expect(field.disabled).toBe(false);
    expect(field.readOnly).toBe(true);

    await screen.findByText(/net sales were/i);
  });
});
