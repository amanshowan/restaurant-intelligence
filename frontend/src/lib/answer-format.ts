/**
 * Parsing the answer's light markdown into a structure React can render.
 *
 * WHY THIS EXISTS
 * The answer generator writes for people, and in practice it emits `**bold**`
 * and `- ` bullet lists when comparing several items. Rendering that as plain
 * text shows a reader literal asterisks, which looks broken and undermines the
 * one part of the page they are meant to trust.
 *
 * WHY NOT A MARKDOWN LIBRARY
 * Two reasons, and the second is the important one. The subset actually used
 * is three constructs wide, so a dependency would be mostly unused code. And
 * every general-purpose renderer's fast path is HTML — which means
 * `dangerouslySetInnerHTML`, which means putting model output into the DOM as
 * markup. This module returns DATA. The component maps it to React elements,
 * so there is no path from a generated string to executable markup, and no
 * sanitiser to get wrong.
 *
 * Anything it does not recognise stays literal text. That is the right failure
 * direction: an unstyled asterisk is a cosmetic problem, whereas guessing at
 * unfamiliar syntax risks dropping words from a figure.
 */

/** A run of text, optionally emphasised. */
export interface AnswerSpan {
  text: string;
  strong?: boolean;
}

export type AnswerBlock =
  | { kind: "paragraph"; spans: AnswerSpan[] }
  | { kind: "list"; items: AnswerSpan[][] };

/** `- item` or `* item`, the two bullet markers the model actually produces. */
const BULLET = /^\s*[-*]\s+(.*)$/;

/** `**bold**`. Non-greedy, so two bold runs in a line stay separate. */
const STRONG = /\*\*(.+?)\*\*/g;

/**
 * Splits one line into emphasised and plain runs.
 *
 * Exported for its tests: inline parsing is where an off-by-one silently eats
 * a character, and a dropped digit in "£1,234.56" is exactly the kind of
 * corruption this page cannot afford.
 */
export function parseInline(line: string): AnswerSpan[] {
  const spans: AnswerSpan[] = [];
  let index = 0;

  // `matchAll` on a /g regex, so `lastIndex` bookkeeping is not ours to get
  // wrong.
  for (const match of line.matchAll(STRONG)) {
    const start = match.index ?? 0;
    if (start > index) spans.push({ text: line.slice(index, start) });
    spans.push({ text: match[1], strong: true });
    index = start + match[0].length;
  }

  if (index < line.length) spans.push({ text: line.slice(index) });
  return spans.length > 0 ? spans : [{ text: line }];
}

/**
 * The answer as a list of blocks.
 *
 * Blank lines separate paragraphs; consecutive bullet lines become one list.
 * A single trailing newline does not create an empty paragraph.
 */
export function parseAnswer(answer: string): AnswerBlock[] {
  const blocks: AnswerBlock[] = [];
  let paragraph: string[] = [];
  let items: string[] = [];

  const flushParagraph = () => {
    if (paragraph.length === 0) return;
    blocks.push({ kind: "paragraph", spans: parseInline(paragraph.join(" ")) });
    paragraph = [];
  };
  const flushList = () => {
    if (items.length === 0) return;
    blocks.push({ kind: "list", items: items.map(parseInline) });
    items = [];
  };

  for (const line of answer.replace(/\r\n/g, "\n").split("\n")) {
    const bullet = line.match(BULLET);

    if (bullet) {
      flushParagraph();
      items.push(bullet[1].trim());
      continue;
    }

    if (line.trim() === "") {
      flushParagraph();
      flushList();
      continue;
    }

    flushList();
    paragraph.push(line.trim());
  }

  flushParagraph();
  flushList();
  return blocks;
}
