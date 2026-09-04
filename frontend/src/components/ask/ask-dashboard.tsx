"use client";

import { useCallback, useState } from "react";

import { PageHeader } from "@/components/page-header";
import { askQuestion, type AskResponse, type ResolvedProduct } from "@/lib/api";
import { distinctWarnings, operationLabel, questionProblem } from "@/lib/ask";
import { useAnalyticsResource } from "@/lib/use-analytics-resource";

import { AnswerBody } from "./answer-body";
import { AskFailure, ClarificationPanel, UnsupportedPanel } from "./ask-states";
import { EvidenceSummary } from "./evidence-summary";
import { QuestionForm } from "./question-form";

/**
 * The Ask page.
 *
 * SINGLE-TURN, DELIBERATELY. `/analytics/ask` has no conversation semantics —
 * no thread id, no history parameter — so each question is answered on its own
 * evidence with no knowledge of the last. The page says so rather than
 * implying otherwise: a transcript would look like memory the system does not
 * have, and a follow-up like "and the month before?" would silently be
 * answered as if asked cold.
 *
 * REQUEST HANDLING reuses `useAnalyticsResource`, the same hook behind every
 * other dashboard. It is keyed here on a submission counter rather than on
 * filter inputs, which is the whole adaptation needed: submitting increments
 * the key, the hook aborts whatever was in flight and starts the new request,
 * and a late response from an abandoned question cannot land because its
 * controller was aborted. Cancellation and stale-response protection therefore
 * come from code that already has tests, rather than from a second
 * implementation written for this page.
 *
 * A previous answer is NOT shown while a new question is in flight, though the
 * hook would keep it. Elsewhere that behaviour is right — dimmed figures for
 * an old date range are still those figures. Here the heading above would say
 * one question and the prose below would answer another, for the eight to
 * fifteen seconds a model takes.
 */
export function AskDashboard() {
  const [question, setQuestion] = useState("");
  const [problem, setProblem] = useState<string | null>(null);

  // What was actually sent, and how many times. `asked` fixes the text for the
  // request; `submission` makes each send a distinct key, so asking the same
  // question twice re-runs it instead of being deduplicated into nothing.
  const [asked, setAsked] = useState<string | null>(null);
  const [submission, setSubmission] = useState(0);

  const result = useAnalyticsResource<AskResponse>(
    `ask|${submission}`,
    // Depends on `asked` alone. Asking the same question twice still re-runs
    // it, because the KEY carries the submission counter and the key is what
    // the hook re-fetches on — the fetcher closure does not need to change.
    useCallback((signal) => askQuestion(asked ?? "", { signal }), [asked]),
    { enabled: asked !== null },
  );

  const { data, error, busy, retry } = result;

  const submit = useCallback(
    (value: string) => {
      // Guards the keyboard path as well as the button's `disabled`: Enter in
      // the textarea would otherwise start a second request over the first.
      if (busy) return;

      const trimmed = value.trim();
      const invalid = questionProblem(trimmed);
      setProblem(invalid);
      if (invalid) return;

      setQuestion(trimmed);
      setAsked(trimmed);
      setSubmission((count) => count + 1);
    },
    [busy],
  );

  const askAbout = useCallback(
    (product: ResolvedProduct) => {
      const named = product.variation
        ? `${product.name} (${product.variation})`
        : product.name;
      submit(`${asked ?? ""} Specifically, ${named}.`.trim());
    },
    [asked, submit],
  );

  // Only ever the response to the question currently on screen: `busy` gates
  // both, so nothing from a superseded question is rendered.
  const answer = busy ? null : data;
  const failure = busy ? null : error;
  const warnings = answer ? distinctWarnings(answer) : [];

  return (
    <>
      <PageHeader
        title="Ask"
        description="Ask a question in plain English. It is answered only from figures measured in your own till data, and the analysis behind every answer is shown alongside it."
      />

      <div className="flex flex-col gap-5">
        <QuestionForm
          question={question}
          onQuestionChange={setQuestion}
          onSubmit={submit}
          busy={busy}
          problem={problem}
        />

        {/* One live region for the whole result area, so a screen reader is
            told once when the state changes rather than per panel. */}
        <div aria-live="polite" aria-busy={busy} className="flex flex-col gap-5">
          {busy && <Thinking question={asked} />}

          {failure && <AskFailure error={failure} onRetry={retry} />}

          {answer?.status === "clarification_needed" && (
            <ClarificationPanel
              answer={answer.answer}
              candidates={answer.candidates}
              onChoose={askAbout}
            />
          )}

          {answer?.status === "unsupported" && (
            <UnsupportedPanel answer={answer.answer} />
          )}

          {answer?.status === "answered" && (
            <>
              <section className="rounded-lg border border-line bg-surface p-5">
                <h2 className="text-[13px] font-semibold tracking-tight text-ink">
                  {answer.question}
                </h2>

                {/* Stated ABOVE the prose, and derived from the evidence
                    rather than from the answer's wording — so a prediction is
                    marked even if the sentence that follows forgot to. */}
                {answer.contains_forecast && (
                  <p className="mt-2.5 rounded-md border border-line bg-accent-soft px-3 py-2 text-[12px] leading-relaxed text-ink">
                    <strong className="font-semibold">
                      This answer includes predictions.
                    </strong>{" "}
                    Some figures below are model output for days that have not
                    happened. They are not a record of trade.
                  </p>
                )}

                <div className="mt-3.5">
                  <AnswerBody answer={answer.answer} />
                </div>

                {answer.steps.length > 0 && (
                  <p className="mt-4 border-t border-line pt-3 text-[12px] text-ink-subtle">
                    Answered using{" "}
                    {answer.steps
                      .map((step) => operationLabel(step.operation))
                      .join(", ")}
                    .
                  </p>
                )}
              </section>

              {warnings.length > 0 && (
                <section className="rounded-lg border border-line bg-surface-muted p-4">
                  <h2 className="text-[12px] font-semibold tracking-tight text-ink">
                    Worth knowing
                  </h2>
                  <ul className="mt-2 flex flex-col gap-1.5">
                    {warnings.map((warning) => (
                      <li
                        key={warning}
                        className="text-[12px] leading-relaxed text-ink-muted"
                      >
                        {warning}
                      </li>
                    ))}
                  </ul>
                </section>
              )}

              <EvidenceSummary evidence={answer.evidence} />
            </>
          )}
        </div>
      </div>
    </>
  );
}

/**
 * The waiting state.
 *
 * A model answer takes eight to fifteen seconds — long enough that a bare
 * spinner reads as a hang. Naming the stages sets the expectation honestly,
 * and echoing the question back confirms what is being answered.
 */
function Thinking({ question }: { question: string | null }) {
  return (
    <section className="rounded-lg border border-line bg-surface p-5">
      <div className="flex items-center gap-2.5">
        <span
          aria-hidden
          className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-line-strong border-t-accent"
        />
        <h2 className="text-sm font-semibold text-ink">Working on it</h2>
      </div>
      {question && (
        <p className="mt-2 max-w-2xl text-sm leading-relaxed text-ink-muted">
          “{question}”
        </p>
      )}
      <p className="mt-2 max-w-2xl text-[12px] leading-relaxed text-ink-subtle">
        Choosing which analytics to run, measuring your data, then writing the
        answer. This usually takes about ten seconds.
      </p>
    </section>
  );
}
