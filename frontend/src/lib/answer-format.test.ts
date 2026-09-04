import { describe, expect, it } from "vitest";

import { parseAnswer, parseInline } from "./answer-format";

describe("parseInline", () => {
  it("returns one plain span for text with no emphasis", () => {
    expect(parseInline("Net sales were £47,194.08.")).toEqual([
      { text: "Net sales were £47,194.08." },
    ]);
  });

  it("splits a bold run from the text around it", () => {
    expect(parseInline("**Sunday** — £91,621.40 net sales")).toEqual([
      { text: "Sunday", strong: true },
      { text: " — £91,621.40 net sales" },
    ]);
  });

  it("keeps two bold runs on one line separate", () => {
    expect(parseInline("**A** and **B** rose")).toEqual([
      { text: "A", strong: true },
      { text: " and " },
      { text: "B", strong: true },
      { text: " rose" },
    ]);
  });

  it("loses no characters from a money figure", () => {
    const line = "Up **£2,155.50** on July's £45,038.58 — a rise of 4.79%.";
    expect(parseInline(line).map((span) => span.text).join("")).toBe(
      "Up £2,155.50 on July's £45,038.58 — a rise of 4.79%.",
    );
  });

  it("leaves an unmatched asterisk as literal text", () => {
    expect(parseInline("2 * 3 is 6")).toEqual([{ text: "2 * 3 is 6" }]);
  });
});

describe("parseAnswer", () => {
  it("makes one paragraph per blank-line-separated block", () => {
    const blocks = parseAnswer("First para.\n\nSecond para.");
    expect(blocks).toHaveLength(2);
    expect(blocks[0]).toEqual({
      kind: "paragraph",
      spans: [{ text: "First para." }],
    });
  });

  it("joins wrapped lines into one paragraph", () => {
    const blocks = parseAnswer("A sentence that\nwraps across lines.");
    expect(blocks).toEqual([
      { kind: "paragraph", spans: [{ text: "A sentence that wraps across lines." }] },
    ]);
  });

  it("collects consecutive bullets into a single list", () => {
    const blocks = parseAnswer("- Sunday\n- Saturday\n- Friday");
    expect(blocks).toHaveLength(1);
    expect(blocks[0].kind).toBe("list");
    expect(blocks[0].kind === "list" && blocks[0].items).toHaveLength(3);
  });

  it("handles the real shape the model returns", () => {
    const blocks = parseAnswer(
      "Saturday and Sunday are your busiest days.\n\n" +
        "- **Sunday** — £91,621.40 net sales\n" +
        "- **Saturday** — £90,479.53 net sales\n\n" +
        "Each figure is a total for all occurrences of that weekday.",
    );
    expect(blocks.map((block) => block.kind)).toEqual([
      "paragraph",
      "list",
      "paragraph",
    ]);
    expect(blocks[1].kind === "list" && blocks[1].items[0][0]).toEqual({
      text: "Sunday",
      strong: true,
    });
  });

  it("does not emit an empty block for trailing whitespace", () => {
    expect(parseAnswer("Only paragraph.\n\n")).toHaveLength(1);
    expect(parseAnswer("")).toEqual([]);
  });

  it("separates a list from the paragraph directly above it", () => {
    const blocks = parseAnswer("Top items:\n- One\n- Two");
    expect(blocks.map((block) => block.kind)).toEqual(["paragraph", "list"]);
  });

  it("treats a * bullet the same as a - bullet", () => {
    expect(parseAnswer("* One\n* Two")[0].kind).toBe("list");
  });
});
