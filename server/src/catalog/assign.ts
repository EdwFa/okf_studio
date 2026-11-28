/**
 * Recommendation → shelf, group, and the title an agent sees.
 * Titles longer than 200 characters lose a shared lead or a trailing list,
 * and keep the syndrome or the clause that tells this document from the next.
 */
import { readFileSync } from "node:fs";
import type { CatalogDocument, CatalogGroup, CatalogShelf, CatalogSnapshot } from "./types.ts";

export const MAX_AGENT_TITLE = 200;
export const MAX_CARD_DESCRIPTION = 500;

const PSYCH_LEAD = "Психические и поведенческие расстройства, вызванные употреблением ";

function loadSnapshot(): CatalogSnapshot {
  return JSON.parse(readFileSync(new URL("./knowledge-groups.json", import.meta.url), "utf8")) as CatalogSnapshot;
}

const snapshot = loadSnapshot();

const shelves = new Map<string, CatalogShelf>(snapshot.shelves.map((shelf) => [shelf.catalogKey, shelf]));

interface Indexed {
  shelf: CatalogShelf;
  group: CatalogGroup;
  doc: CatalogDocument;
}

const byCr = new Map<string, Indexed>();
for (const group of snapshot.groups) {
  const shelf = shelves.get(group.shelfKey);
  if (!shelf) throw new Error(`group ${group.catalogKey} points at a missing shelf ${group.shelfKey}`);
  for (const doc of group.documents) {
    if (byCr.has(doc.id)) throw new Error(`document ${doc.id} is in more than one group`);
    byCr.set(doc.id, { shelf, group, doc });
  }
}

/** Shorten a Minzdrav title to the length a document card and a skill description can carry. */
export function agentTitle(name: string): string {
  let text = name.replace(/\s+/g, " ").trim();
  if (text.length <= MAX_AGENT_TITLE) return text;
  text = text.replace(/\s*\[[^\]]*\]/g, "").replace(/\s+/g, " ").replace(/\s+([.,])/g, "$1").trim();
  if (text.length <= MAX_AGENT_TITLE) return text;
  if (text.startsWith(PSYCH_LEAD)) {
    const syndrome = text.slice(PSYCH_LEAD.length).replace(/^психоактивных веществ[.\s]*/i, "");
    text = syndrome ? syndrome.charAt(0).toUpperCase() + syndrome.slice(1) : text;
    if (text.length <= MAX_AGENT_TITLE) return text;
  }
  text = text.replace(/,?\s*требующее предоставления медицинской помощи матери$/, "");
  if (text.length <= MAX_AGENT_TITLE) return text;
  text = text.replace(/\s*\([^)]*(?:классифицирован|рубрик)[^)]*\)\s*$/i, "").trim();
  if (text.length <= MAX_AGENT_TITLE) return text;
  const comma = text.lastIndexOf(", ", MAX_AGENT_TITLE);
  const space = text.lastIndexOf(" ", MAX_AGENT_TITLE);
  const at = comma > 80 ? comma : space;
  return text.slice(0, at > 0 ? at : MAX_AGENT_TITLE).replace(/[.,;:\s]+$/, "");
}

/** Age and ICD codes for the document card, never longer than 500 characters. */
export function cardDescription(age: string, codes: string[]): string {
  const head = age ? `${age}. Коды: ` : "Коды: ";
  const full = `${head}${codes.join(", ")}.`;
  if (full.length <= MAX_CARD_DESCRIPTION) return full;
  const kept: string[] = [];
  for (const code of codes) {
    const next = `${head}${[...kept, code].join(", ")}.`;
    if (next.length > MAX_CARD_DESCRIPTION) break;
    kept.push(code);
  }
  const more = codes.length - kept.length;
  const text = more ? `${head}${kept.join(", ")} +${more}.` : `${head}${kept.join(", ")}.`;
  return text.length <= MAX_CARD_DESCRIPTION ? text : `${text.slice(0, MAX_CARD_DESCRIPTION - 1)}…`;
}

export interface Assignment {
  crId: string;
  shelfKey: string;
  shelfName: string;
  groupKey: string;
  groupName: string;
  age: string;
  codes: string[];
  year?: string;
  title: string;
  description: string;
}

export function catalogSnapshot(): CatalogSnapshot {
  return snapshot;
}

/** Where a Minzdrav recommendation goes, and the title the agent will see. */
export function assignCr(id: string): Assignment | undefined {
  const hit = byCr.get(id);
  if (!hit) return undefined;
  return {
    crId: id,
    shelfKey: hit.shelf.catalogKey,
    shelfName: hit.shelf.name,
    groupKey: hit.group.catalogKey,
    groupName: hit.group.name,
    age: hit.doc.age,
    codes: hit.doc.mkb10,
    ...(hit.doc.year ? { year: hit.doc.year } : {}),
    title: agentTitle(hit.doc.name),
    description: cardDescription(hit.doc.age, hit.doc.mkb10),
  };
}
