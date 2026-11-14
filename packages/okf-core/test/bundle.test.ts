import { parse as parseYaml } from "yaml";
import { describe, expect, it } from "vitest";
import { appendLogEntry, checkBundle, okfInstant, renderDocument, renderGroupIndex, renderRootIndex, splitIntoSections } from "../src/index.ts";
import { GUIDELINE } from "./fixture.ts";

const group = { id: "g1", name: "КР" };
const doc = { id: "abc123", title: "КР тест", description: "Когда читать", source: "КР тест.pdf", pages: 6, addedAt: "2026-11-14T10:00:00Z", extra: { year: 2024, icd10: ["C10"], tags: [] } };

describe("OKF rendering", () => {
  const files = renderDocument(group, doc, splitIntoSections(GUIDELINE), GUIDELINE);

  it("writes an index, one file per section and a recommendations table", () => {
    expect(files.size).toBe(16);
    const index = files.get("abc123.md")!;
    expect(index).toContain("[2.1 Жалобы и анамнез](abc123/07_2.1.md)");
    expect(index).not.toContain("сбор жалоб");
    const meta = parseYaml(index.slice(4, index.indexOf("\n---\n", 4))) as Record<string, unknown>;
    expect(meta).toMatchObject({ type: "document", group: "КР", sections: 14, recommendations: 4, year: 2024, icd10: ["C10"] });
    expect(meta).not.toHaveProperty("tags");
    expect(files.get("abc123/recommendations.md")).toContain("| 3.1/1 | [3.1 Хирургическое лечение](10_3.1.md) | A | 1 | Рекомендуется удаление первичной опухоли [4]. |");
  });

  it("gives every file a type", () => {
    for (const content of files.values()) expect(content).toMatch(/^---\ntype: (document|section|summary)\n/);
  });

  it("stores a text without headings as one file", () => {
    const plain = renderDocument(group, doc, [], "Просто заметки.");
    expect([...plain.keys()]).toEqual(["abc123.md"]);
    expect(plain.get("abc123.md")).toContain("# КР тест\n\nПросто заметки.");
  });

  it("writes provenance into every file and section fields into their section", () => {
    const provenance = { sources: [{ id: "original", resource: "sources/abc123.pdf" }], generated: { by: "okf-studio/0.1.0", at: "2026-11-14T10:00:00+00:00" } };
    const marked = renderDocument(group, { ...doc, provenance }, splitIntoSections(GUIDELINE), GUIDELINE, (section) => (section.number === "2.1" ? { status: "stable" } : { status: "draft" }));
    for (const content of marked.values()) {
      const meta = parseYaml(content.slice(4, content.indexOf("\n---\n", 4))) as Record<string, any>;
      expect(meta.sources).toEqual(provenance.sources);
      expect(meta.generated.by).toBe("okf-studio/0.1.0");
      expect(typeof meta.description).toBe("string");
    }
    expect(marked.get("abc123/07_2.1.md")).toContain("status: stable");
    expect(marked.get("abc123/08_2.2.md")).toContain("status: draft");
  });
});

describe("reserved files (OKF 0.2 §8, §9)", () => {
  it("writes a group index without frontmatter, as links with descriptions", () => {
    const index = renderGroupIndex({ ...group, description: "Действующие КР" }, [{ ...doc, sections: 14, recommendations: 4 }]);
    expect(index.startsWith("# КР\n")).toBe(true);
    expect(index).toContain("- [КР тест](abc123.md) — Когда читать (разделов: 14, рекомендаций: 4)");
  });

  it("puts only okf_version into the root index frontmatter", () => {
    const index = renderRootIndex("База знаний", "", [{ id: "g1", name: "КР", note: "1 документов" }]);
    expect(index.startsWith('---\nokf_version: "0.2"\n---\n\n# База знаний')).toBe(true);
    expect(index).toContain("- [КР](g1/index.md) — 1 документов");
  });

  it("keeps the log grouped by date, newest first, and converts the older layout", () => {
    const legacy = "---\ntype: log\ntitle: Журнал\n---\n\n# Журнал изменений\n\n- 2026-11-13T09:05:11.000Z group created: КР\n- 2026-11-13T10:00:00.000Z document added\n";
    const first = appendLogEntry(legacy, "Журнал изменений", "group  renamed", new Date("2026-11-14T08:30:00Z"));
    expect(first).toBe("# Журнал изменений\n\n## 2026-11-14\n\n- 08:30 UTC — group renamed\n\n## 2026-11-13\n\n- 10:00 UTC — document added\n- 09:05 UTC — group created: КР\n");
    const second = appendLogEntry(first, "Журнал изменений", "document deleted", new Date("2026-11-14T09:00:00Z"));
    expect(second).toContain("## 2026-11-14\n\n- 09:00 UTC — document deleted\n- 08:30 UTC — group renamed\n\n## 2026-11-13");
    expect(appendLogEntry(undefined, "Журнал", "x", new Date("2026-01-02T03:04:00Z"))).toBe("# Журнал\n\n## 2026-01-02\n\n- 03:04 UTC — x\n");
  });

  it("writes instants with an explicit UTC offset", () => {
    expect(okfInstant("2026-11-14T10:00:00.123Z")).toBe("2026-11-14T10:00:00+00:00");
    expect(okfInstant("2027-01-01")).toBe("2027-01-01T00:00:00+00:00");
    expect(okfInstant("не дата")).toBe("");
  });
});

describe("checkBundle (OKF 0.2 §11)", () => {
  it("accepts what this package renders", () => {
    const files = new Map(renderDocument(group, doc, splitIntoSections(GUIDELINE), GUIDELINE));
    files.set("index.md", renderRootIndex("База", "", []));
    files.set("g1/index.md", renderGroupIndex(group, []));
    files.set("log.md", appendLogEntry(undefined, "Журнал", "x"));
    expect(checkBundle(files)).toEqual([]);
  });

  it("reports each kind of violation", () => {
    const problems = checkBundle(
      new Map([
        ["a.md", "# No frontmatter"],
        ["b.md", "---\ntitle: x\n---\ntext"],
        ["g/index.md", "---\ntype: index\n---\n# G"],
        ["index.md", '---\nokf_version: "0.2"\ntitle: x\n---\n# Root'],
        ["log.md", "---\ntype: log\n---\n## 14.11.2026\n- x"],
        ["notes.txt", "ignored"],
      ]),
    );
    expect(problems).toEqual([
      "a.md: no frontmatter block",
      "b.md: frontmatter has no type",
      "g/index.md: an index file below the bundle root must not have frontmatter",
      "index.md: the root index may carry only okf_version, found title",
      "log.md: a log file must not have frontmatter",
      'log.md: date heading "## 14.11.2026" is not YYYY-MM-DD',
    ]);
  });
});
