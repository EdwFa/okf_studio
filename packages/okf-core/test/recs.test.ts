import { describe, expect, it } from "vitest";
import { normalizeBody, parseBody, recommendationsOf, serializeBody, splitIntoSections } from "../src/index.ts";
import { GUIDELINE } from "./fixture.ts";

const sections = splitIntoSections(GUIDELINE);
const byKey = new Map(sections.map((section) => [section.key, section]));

describe("recommendation markup as blocks", () => {
  it("reads back exactly the recommendations the splitter found", () => {
    for (const section of sections) expect(recommendationsOf(section.body)).toEqual(section.recommendations);
  });

  it("round-trips a body without changing it", () => {
    for (const section of sections) {
      const label = section.number ?? section.title;
      expect(normalizeBody(section.body, label)).toBe(section.body.trim());
    }
  });

  it("keeps text around recommendations and the comment with its recommendation", () => {
    const blocks = parseBody(byKey.get("2.1")!.body);
    expect(blocks).toEqual([
      {
        kind: "rec",
        text: "Рекомендуется всем пациентам проводить сбор жалоб и анамнеза с целью выявления факторов риска [1].",
        grade: "C",
        evidence: "5",
        comment: "к факторам риска относятся курение и алкоголь.",
      },
    ]);
  });

  it("renumbers after an edit and tolerates a missing grade", () => {
    const blocks = parseBody(byKey.get("2.2")!.body);
    const edited = serializeBody([{ kind: "rec", text: "Новая рекомендация." }, ...blocks], "2.2");
    expect(edited).toContain("### Рекомендация 2.2/1 · УУР — · УДД —\n\nНовая рекомендация.");
    expect(edited).toContain("### Рекомендация 2.2/3 · УУР B · УДД 2");
    expect(recommendationsOf(edited).map((rec) => [rec.n, rec.grade])).toEqual([[1, undefined], [2, "C"], [3, "B"]]);
  });

  it("treats a body without markup as plain text", () => {
    expect(parseBody("Суммарная доза 70 Гр.")).toEqual([{ kind: "text", text: "Суммарная доза 70 Гр." }]);
    expect(recommendationsOf("")).toEqual([]);
  });
});
