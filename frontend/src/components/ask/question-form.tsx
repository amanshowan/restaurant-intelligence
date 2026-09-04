"use client";

import { useId } from "react";

import { EXAMPLE_QUESTIONS, MAX_QUESTION_LENGTH } from "@/lib/ask";

/**
 * The question input, its example chips and the submit control.
 *
 * A textarea rather than a single-line input: questions run to a sentence or
 * two, and a field that scrolls sideways hides what the user typed. Enter
 * submits, Shift+Enter adds a line — the convention people already expect from
 * a message box, and the reason the hint is stated rather than left to be
 * discovered.
 *
 * The chips are not decoration. This is a general-purpose question box over a
 * bounded set of operations, and the gap between "ask anything" and what the
 * system can actually answer is the page's main usability risk. Six worked
 * examples show the shape of a good question faster than any instruction.
 */
export function QuestionForm({
  question,
  onQuestionChange,
  onSubmit,
  busy,
  problem,
}: {
  question: string;
  onQuestionChange: (value: string) => void;
  /** Submits `value`, which may differ from `question` when a chip is used. */
  onSubmit: (value: string) => void;
  busy: boolean;
  /** A local validation message, shown before anything is sent. */
  problem: string | null;
}) {
  const inputId = useId();
  const hintId = useId();
  const problemId = useId();
  const remaining = MAX_QUESTION_LENGTH - question.trim().length;

  return (
    <form
      className="rounded-lg border border-line bg-surface p-4"
      onSubmit={(event) => {
        event.preventDefault();
        onSubmit(question);
      }}
    >
      <label
        htmlFor={inputId}
        className="block text-[13px] font-semibold tracking-tight text-ink"
      >
        Ask a question about your trading
      </label>

      <textarea
        id={inputId}
        name="question"
        value={question}
        onChange={(event) => onQuestionChange(event.target.value)}
        onKeyDown={(event) => {
          if (event.key === "Enter" && !event.shiftKey) {
            event.preventDefault();
            if (!busy) onSubmit(question);
          }
        }}
        rows={3}
        maxLength={MAX_QUESTION_LENGTH}
        // Not `disabled` while busy: disabling a focused field moves focus to
        // the body, which drops a screen-reader user out of the form and loses
        // their place. Read-only keeps focus and the caret where they are.
        readOnly={busy}
        aria-describedby={problem ? `${hintId} ${problemId}` : hintId}
        aria-invalid={problem ? true : undefined}
        placeholder="How did we perform last month?"
        className="mt-2 w-full resize-y rounded-md border border-line-strong bg-surface px-3 py-2.5 text-sm leading-relaxed text-ink placeholder:text-ink-subtle read-only:bg-surface-muted"
      />

      <p id={hintId} className="mt-1.5 text-[12px] text-ink-subtle">
        Enter to send, Shift+Enter for a new line. Each question is answered on
        its own — this page does not remember the last one.
        {remaining < 100 && ` ${remaining} characters left.`}
      </p>

      {problem && (
        <p id={problemId} role="alert" className="mt-1.5 text-[12px] text-negative">
          {problem}
        </p>
      )}

      <div className="mt-3 flex flex-wrap items-center gap-2">
        <button
          type="submit"
          disabled={busy}
          className="h-9 rounded-md bg-accent px-4 text-sm font-medium text-white disabled:cursor-not-allowed disabled:opacity-60"
        >
          {busy ? "Thinking…" : "Ask"}
        </button>
      </div>

      {/* The fieldset carries the GROUP semantics; each button carries its own
          `disabled`. A disabled fieldset does disable its descendants per the
          HTML spec, but `button.disabled` reflects only the button's own
          attribute — so relying on inheritance alone leaves the guard
          invisible to anything inspecting the control itself. */}
      <fieldset className="mt-4 border-t border-line pt-3.5" disabled={busy}>
        <legend className="sr-only">Example questions</legend>
        <p aria-hidden className="mb-2 text-[12px] font-medium text-ink-muted">
          Try one of these
        </p>
        <ul className="flex flex-wrap gap-2">
          {EXAMPLE_QUESTIONS.map((example) => (
            <li key={example}>
              <button
                type="button"
                // Submits directly rather than only filling the box: a chip
                // that needs a second click to do anything is a worse
                // affordance than one that asks the question.
                disabled={busy}
                onClick={() => {
                  onQuestionChange(example);
                  onSubmit(example);
                }}
                className="rounded-full border border-line-strong bg-surface px-3 py-1.5 text-[12px] text-ink-muted hover:bg-surface-muted disabled:cursor-not-allowed disabled:opacity-50"
              >
                {example}
              </button>
            </li>
          ))}
        </ul>
      </fieldset>
    </form>
  );
}
