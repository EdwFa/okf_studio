/**
 * Splitting a document into sections and marking up recommendations.
 * Mirrors the first two suites of Luka's server/test/knowledge-sections.test.ts.
 */
import { describe, expect, it } from "vitest";
import { splitIntoSections, structureRecommendations } from "../src/sections.ts";
import { GUIDELINE } from "./fixture.ts";

describe("splitIntoSections", () => {
  const sections = splitIntoSections(GUIDELINE);
  const byKey = new Map(sections.map((section) => [section.key, section]));

  it("follows the document's own outline and ignores its table of contents", () => {
    expect(sections.map((section) => section.key)).toEqual([
      "титул", "список сокращений", "1", "1.1", "1.2", "2", "2.1", "2.2", "3", "3.1", "3.2",
      "критерии оценки качества", "список литературы", "приложение а1",
    ]);
    expect(sections[0]!.body).toContain("Год утверждения: 2024");
    expect(sections.some((section) => section.body.includes("Оглавление"))).toBe(false);
  });

  it("does not mistake numbered lists and references for headings", () => {
    expect(byKey.get("2")!.body).toContain("1. Данных анамнеза;");
    expect(byKey.get("2")!.body).toContain("2. Физикального обследования.");
    expect(byKey.get("список литературы")!.body).toContain("2. Petrov P.");
  });

  it("joins a heading that wraps and records level, parent and pages", () => {
    expect(byKey.get("1")!.title).toBe("1 Краткая информация по заболеванию или состоянию (группы заболеваний или состояний)");
    expect(byKey.get("2")!.title).toMatch(/противопоказания к применению методов диагностики$/);
    expect(byKey.get("2.1")).toMatchObject({ level: 2, parent: "2", pageStart: 4, pageEnd: 4, number: "2.1" });
    expect(byKey.get("1.2")!.body).toBe("Т1 Опухоль до 2 см в наибольшем измерении\nТ2 Опухоль от 2 см до 4 см");
  });

  it("accepts subsections the table of contents does not list, when they continue the outline", () => {
    expect(byKey.get("3.1")).toMatchObject({ parent: "3", title: "3.1 Хирургическое лечение" });
    expect(byKey.get("3.2")!.body).toContain("70 Гр за 35 фракций");
  });

  it("gives every section a unique, ordered file name", () => {
    const slugs = sections.map((section) => section.slug);
    expect(new Set(slugs).size).toBe(slugs.length);
    expect(slugs.slice(0, 4)).toEqual(["01_titul", "02_sokrashcheniya", "03_1", "04_1.1"]);
    expect(slugs.at(-1)).toBe("14_prilozhenie-A1");
  });

  it("leaves a text without headings unsplit", () => {
    expect(splitIntoSections("Просто заметки.\n1. Первое.\n2. Второе.\n3. Третье.")).toEqual([]);
  });

  it("splits DOCX text along its Markdown headings", () => {
    const docx = "## Введение\nТекст.\n### Цель\nЦель работы.\n## Методы\nОписание.\n## Результаты\nИтог.";
    const parts = splitIntoSections(docx);
    expect(parts.map((part) => [part.title, part.level])).toEqual([["Введение", 1], ["Цель", 2], ["Методы", 1], ["Результаты", 1]]);
    expect(parts[1]!.parent).toBe(parts[0]!.key);
  });
});

describe("recommendations", () => {
  const byKey = new Map(splitIntoSections(GUIDELINE).map((section) => [section.key, section]));

  it("extracts the statement, both grades and the comment, in either order of the grades", () => {
    expect(byKey.get("2.1")!.recommendations).toEqual([
      {
        n: 1,
        text: "Рекомендуется всем пациентам проводить сбор жалоб и анамнеза с целью выявления факторов риска [1].",
        grade: "C",
        evidence: "5",
        comment: "к факторам риска относятся курение и алкоголь.",
      },
    ]);
    const lab = byKey.get("2.2")!.recommendations;
    expect(lab.map((rec) => [rec.grade, rec.evidence])).toEqual([["C", "4"], ["B", "2"]]);
    expect(lab[0]!.text).toBe("Рекомендуется выполнять определение ДНК вируса методом ПЦР [2].");
    // Worded mid-sentence: the whole sentence is the statement.
    expect(lab[1]!.text).toBe("При наличии отдаленных метастазов рекомендуется проведение ПЭТ-КТ [3].");
  });

  it("marks them up in the section text without dropping anything", () => {
    const body = byKey.get("2.1")!.body;
    expect(body).toContain("### Рекомендация 2.1/1 · УУР C · УДД 5");
    expect(body).toContain("**Комментарий.** к факторам риска относятся курение и алкоголь.");
    expect(byKey.get("3.1")!.body).toContain("### Рекомендация 3.1/1 · УУР A · УДД 1");
  });

  it("reads letters a PDF stored as base letter plus combining mark", () => {
    const decomposed = "Рекомендуется наблюдение.\nУровень убедительности рекомендаций – C (уровень достоверности доказательств – 5)".normalize("NFD");
    expect(structureRecommendations(decomposed.normalize("NFC"), "5").recommendations).toHaveLength(1);
    expect(splitIntoSections(GUIDELINE.normalize("NFD")).reduce((n, section) => n + section.recommendations.length, 0)).toBe(4);
  });

  it("leaves text alone when no statement can be tied to a grade", () => {
    const text = "Доза 70 Гр.\nУровень убедительности рекомендаций – C (уровень достоверности доказательств – 5)";
    expect(structureRecommendations(text, "3")).toEqual({ body: text, recommendations: [] });
  });

  it("writes 0 for a level the document does not state", () => {
    const gradeOnly = "Рекомендуется наблюдение за пациентом.\nУровень убедительности рекомендаций – C.";
    expect(structureRecommendations(gradeOnly, "1").recommendations[0]).toMatchObject({ grade: "C", evidence: "0" });
    const evidenceOnly = "Рекомендуется наблюдение за пациентом.\nУровень достоверности доказательств – 4.";
    expect(structureRecommendations(evidenceOnly, "1").recommendations[0]).toMatchObject({ grade: "0", evidence: "4" });
    const neither = "Рекомендовано проведение целенаправленной антибактериальной терапии при развитии инфекционных осложнений.";
    expect(structureRecommendations(neither, "1").recommendations).toEqual([
      { n: 1, text: neither, grade: "0", evidence: "0" },
    ]);
  });

  it("does not turn a definition into a recommendation", () => {
    const text = "Под ингаляционной травмой следует понимать повреждение слизистой оболочки дыхательных путей.";
    expect(structureRecommendations(text, "1")).toEqual({ body: text, recommendations: [] });
  });
});
