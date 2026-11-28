/** The classifier snapshot: every recommendation once, every agent title inside the skill description. */
import { existsSync, readFileSync } from "node:fs";
import { homedir } from "node:os";
import path from "node:path";
import { describe, expect, it } from "vitest";
import { skillDescription } from "okf-core";
import { agentTitle, assignCr, cardDescription, catalogSnapshot, MAX_AGENT_TITLE, MAX_CARD_DESCRIPTION } from "../src/catalog/assign.ts";
import { buildCatalog } from "../src/catalog/build-groups.ts";

const snapshot = catalogSnapshot();

describe("knowledge groups snapshot", () => {
  it("holds 21 shelves and 182 groups, and a hand-made domain has no place in it", () => {
    expect(snapshot.snapshot).toBe("2026-11-26");
    expect(snapshot.shelves).toHaveLength(21);
    expect(snapshot.groups).toHaveLength(182);
    expect(snapshot.shelves.every((shelf) => shelf.catalogKey.startsWith("shelf:"))).toBe(true);
    expect(snapshot.groups.every((group) => group.catalogKey.startsWith("group:"))).toBe(true);
    expect(new Set(snapshot.shelves.map((shelf) => shelf.catalogKey)).size).toBe(21);
    expect(new Set(snapshot.groups.map((group) => group.catalogKey)).size).toBe(182);
  });

  it("puts the digestive neoplasms in one group of 12", () => {
    const group = snapshot.groups.find((item) => item.catalogKey === "group:neo/c15-c26");
    expect(group?.name).toBe("Злокачественные новообразования органов пищеварения");
    expect(group?.documents).toHaveLength(12);
    expect(group?.shelfKey).toBe("shelf:neo");
  });

  it("covers each of the 781 recommendations once", () => {
    const ids = snapshot.groups.flatMap((group) => group.documents.map((doc) => doc.id));
    expect(new Set(ids).size).toBe(781);
    expect(ids).toHaveLength(781);
    for (const id of ids) expect(assignCr(id)?.crId).toBe(id);
    expect(assignCr("no-such")).toBeUndefined();
  });

  it("keeps names unique and within 120 characters on a shelf", () => {
    for (const shelf of snapshot.shelves) {
      const names = snapshot.groups.filter((group) => group.shelfKey === shelf.catalogKey).map((group) => group.name);
      expect(new Set(names).size).toBe(names.length);
      for (const name of names) expect(name.length).toBeLessThanOrEqual(120);
    }
  });

  it("keeps the syndrome when a psychiatric title is longer than 200 characters", () => {
    const intoxication = assignCr("888_1");
    const psychosis = assignCr("817_1");
    const withdrawal = assignCr("32_2");
    expect(intoxication?.title.length).toBeLessThanOrEqual(MAX_AGENT_TITLE);
    expect(psychosis?.title.length).toBeLessThanOrEqual(MAX_AGENT_TITLE);
    expect(withdrawal?.title.length).toBeLessThanOrEqual(MAX_AGENT_TITLE);
    expect(intoxication?.title).toContain("Острая интоксикация");
    expect(psychosis?.title).toContain("Психотическое расстройство");
    expect(withdrawal?.title).toContain("Синдром отмены");
    expect(withdrawal?.title).toContain("кроме алкоголя и никотина");
    expect(assignCr("766_1")?.title).toContain("Лицевое, лобное или подбородочное предлежание");
  });

  it("fits every agent title into the skill description", () => {
    for (const group of snapshot.groups) {
      const docs = group.documents.map((doc) => {
        const title = agentTitle(doc.name);
        const description = cardDescription(doc.age, doc.mkb10);
        expect(title.length).toBeLessThanOrEqual(MAX_AGENT_TITLE);
        expect(title.length).toBeGreaterThan(0);
        expect(description.length).toBeLessThanOrEqual(MAX_CARD_DESCRIPTION);
        expect(description).toContain(doc.age);
        return { title };
      });
      const description = skillDescription({ id: group.catalogKey, name: group.name }, docs);
      expect(description.length).toBeLessThanOrEqual(1000);
      for (const doc of docs) expect(description).toContain(doc.title);
    }
  });

  it("rebuilds the same keys from the nosology snapshot", () => {
    const source = path.join(homedir(), "ClinRec", "data", "nosology.json");
    if (!existsSync(source)) return;
    const rebuilt = buildCatalog(JSON.parse(readFileSync(source, "utf8")));
    expect(rebuilt.groups.map((group) => group.catalogKey)).toEqual(snapshot.groups.map((group) => group.catalogKey));
    expect(rebuilt).toEqual(snapshot);
  });
});
