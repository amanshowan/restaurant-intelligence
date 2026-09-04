import { parseAnswer, type AnswerSpan } from "@/lib/answer-format";

/**
 * The generated answer, rendered as React elements.
 *
 * The model's light markdown is parsed to DATA by `parseAnswer` and mapped to
 * elements here. Nothing on this path uses `dangerouslySetInnerHTML`, so model
 * output can never become markup — which is the property that matters, given
 * the text is written by a language model reading a user's question.
 */
export function AnswerBody({ answer }: { answer: string }) {
  const blocks = parseAnswer(answer);

  return (
    <div className="flex flex-col gap-3 text-sm leading-relaxed text-ink">
      {blocks.map((block, index) =>
        block.kind === "paragraph" ? (
          <p key={index}>
            <Spans spans={block.spans} />
          </p>
        ) : (
          <ul key={index} className="flex flex-col gap-1.5 pl-4">
            {block.items.map((item, itemIndex) => (
              <li key={itemIndex} className="list-disc marker:text-ink-subtle">
                <Spans spans={item} />
              </li>
            ))}
          </ul>
        ),
      )}
    </div>
  );
}

function Spans({ spans }: { spans: AnswerSpan[] }) {
  return (
    <>
      {spans.map((span, index) =>
        span.strong ? (
          <strong key={index} className="font-semibold">
            {span.text}
          </strong>
        ) : (
          <span key={index}>{span.text}</span>
        ),
      )}
    </>
  );
}
