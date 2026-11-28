/**
 * Builds the catalog snapshot from the Minzdrav nosology file.
 * Run by hand: `npx tsx src/catalog/build-groups.ts` from `server/`.
 * The studio server does not import this module.
 */
import { readFileSync, writeFileSync } from "node:fs";
import { homedir } from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import type { CatalogDocument, CatalogGroup, CatalogShelf, CatalogSnapshot } from "./types.ts";

const SNAPSHOT_DATE = "2026-11-26";
const NAME_LIMIT = 120;

interface NosologyDoc {
  id: string;
  name: string;
  age_category: string;
  publish_date?: string;
  mkb10: string[];
}

interface NosologyBlock {
  id: string;
  range: string;
  title: string;
  documents: NosologyDoc[];
}

interface NosologyChapter {
  id: string;
  range: string;
  blocks: NosologyBlock[];
}

interface Nosology {
  snapshot_date: string;
  chapters: NosologyChapter[];
}

interface ShelfDef {
  id: string;
  name: string;
  range: string;
  chapters: string[];
}

const SHELVES: ShelfDef[] = [
  { id: "inf", name: "Инфекции", range: "A00–B99 и U", chapters: ["01", "22"] },
  { id: "neo", name: "Новообразования", range: "C00–D48", chapters: ["02"] },
  { id: "hem", name: "Болезни крови и иммунитета", range: "D50–D89", chapters: ["03"] },
  { id: "endo", name: "Эндокринология и обмен веществ", range: "E00–E90", chapters: ["04"] },
  { id: "psych", name: "Психиатрия", range: "F00–F99", chapters: ["05"] },
  { id: "neuro", name: "Неврология", range: "G00–G99", chapters: ["06"] },
  { id: "eye", name: "Офтальмология", range: "H00–H59", chapters: ["07"] },
  { id: "ear", name: "Болезни уха", range: "H60–H95", chapters: ["08"] },
  { id: "card", name: "Болезни системы кровообращения", range: "I00–I99", chapters: ["09"] },
  { id: "pulm", name: "Болезни органов дыхания", range: "J00–J99", chapters: ["10"] },
  { id: "gastro", name: "Гастроэнтерология", range: "K00–K93", chapters: ["11"] },
  { id: "derm", name: "Дерматология", range: "L00–L99", chapters: ["12"] },
  { id: "msk", name: "Болезни костно-мышечной системы", range: "M00–M99", chapters: ["13"] },
  { id: "uro", name: "Нефрология и урология", range: "N00–N51", chapters: ["14"] },
  { id: "gyn", name: "Гинекология", range: "N60–N98", chapters: ["14"] },
  { id: "obs", name: "Акушерство", range: "O00–O99", chapters: ["15"] },
  { id: "neonat", name: "Неонатология", range: "P00–P96", chapters: ["16"] },
  { id: "cong", name: "Врождённые аномалии", range: "Q00–Q99", chapters: ["17"] },
  { id: "sym", name: "Симптомы и синдромы", range: "R00–R99", chapters: ["18"] },
  { id: "trauma", name: "Травмы и отравления", range: "S00–T98 и W00–W19", chapters: ["19", "20"] },
  { id: "z", name: "Факторы, влияющие на здоровье", range: "Z00–Z99", chapters: ["21"] },
];

/** Whole chapter, one group. The titles fit in one skill description. */
const CHAPTER_GROUP: Record<string, string> = {
  "08": "Болезни уха",
  "12": "Дерматология",
  "18": "Симптомы и синдромы",
  "21": "Факторы, влияющие на здоровье",
};

/** A chapter that is one document and belongs on another shelf. */
const CHAPTER_NAME: Record<string, string> = {
  "20": "Падения у пожилых",
  "22": "Коронавирусная инфекция COVID-19",
};

const BY_ID: Record<string, [string, string[]][]> = {
  "F10-F19": [
    ["Алкоголь: зависимость, отмена, амнестический синдром", ["899_1", "784_1", "146_2"]],
    ["Психоз, делирий и пагубное употребление ПАВ", ["817_1", "590_2", "592_3"]],
    ["Зависимость и отмена ПАВ, кроме алкоголя и никотина", ["161_2", "32_2"]],
    ["Острая интоксикация психоактивными веществами", ["888_1"]],
    ["Никотин: зависимость и отмена", ["601_2"]],
  ],
  "O30-O48": [
    ["Беременность: таз, рубец матки, плод", ["766_1", "635_2", "671_2", "823_1", "722_2"]],
    ["Беременность: плацента, воды, многоплодие", ["820_1", "776_1", "638_2", "767_1", "800_1"]],
  ],
};

/** `null` is the remainder of the block. */
const BY_RUBRIC: Record<string, [string, string[] | null][]> = {
  "C81-C96": [
    ["Лимфомы", ["C81", "C82", "C83", "C84", "C85", "C88"]],
    ["Множественная миелома", ["C90"]],
    ["Лимфоидные лейкозы", ["C91"]],
    ["Миелоидные лейкозы", ["C92"]],
  ],
  "E70-E90": [
    ["Аминокислоты с разветвлённой цепью", ["E71"]],
    ["Сфинголипидозы", ["E75"]],
    ["Мукополисахаридозы", ["E76"]],
    ["Муковисцидоз, амилоидоз и другие нарушения обмена", null],
  ],
  "Q20-Q28": [
    ["Врождённые пороки камер и перегородок сердца", ["Q20", "Q21"]],
    ["Врождённые пороки клапанов сердца", ["Q22", "Q23"]],
    ["Другие врождённые пороки сердца", ["Q24"]],
    ["Врождённые пороки крупных артерий", ["Q25"]],
    ["Врождённые пороки крупных вен", ["Q26"]],
  ],
};

/** Slug for a split whose block range is shared by several groups. */
const SPLIT_SLUG: Record<string, string> = {
  "Лимфомы": "c81-c88",
  "Множественная миелома": "c90",
  "Лимфоидные лейкозы": "c91",
  "Миелоидные лейкозы": "c92",
  "Аминокислоты с разветвлённой цепью": "e71",
  "Сфинголипидозы": "e75",
  "Мукополисахаридозы": "e76",
  "Муковисцидоз, амилоидоз и другие нарушения обмена": "e70-other",
  "Алкоголь: зависимость, отмена, амнестический синдром": "f10-alcohol",
  "Психоз, делирий и пагубное употребление ПАВ": "f10-psychosis",
  "Зависимость и отмена ПАВ, кроме алкоголя и никотина": "f11-dependence",
  "Острая интоксикация психоактивными веществами": "f10-intoxication",
  "Никотин: зависимость и отмена": "f17-nicotine",
  "Беременность: таз, рубец матки, плод": "o30-fetus",
  "Беременность: плацента, воды, многоплодие": "o30-placenta",
  "Врождённые пороки камер и перегородок сердца": "q20-q21",
  "Врождённые пороки клапанов сердца": "q22-q23",
  "Другие врождённые пороки сердца": "q24",
  "Врождённые пороки крупных артерий": "q25",
  "Врождённые пороки крупных вен": "q26",
};

function shelfOf(chapterId: string, blockId: string): string {
  if (chapterId === "14") {
    const start = blockId.split("-")[0] ?? "";
    return Number(start.slice(1)) >= 60 ? "gyn" : "uro";
  }
  const shelf = SHELVES.find((item) => item.chapters.includes(chapterId));
  if (!shelf) throw new Error(`unknown chapter ${chapterId}`);
  return shelf.id;
}

/** First 3-digit rubric of the document that falls inside the block. */
function rubricOf(block: NosologyBlock, doc: NosologyDoc): string {
  const keys: string[] = [];
  for (const code of doc.mkb10) {
    const match = /^([A-Z]\d{2})/.exec(code);
    const key = match?.[1];
    if (key && !keys.includes(key)) keys.push(key);
  }
  const range = /^([A-Z])(\d{2})[–-]([A-Z])(\d{2})$/.exec(block.range);
  let pool = keys;
  if (range?.[1] && range[2] && range[4]) {
    const letter = range[1];
    const from = Number(range[2]);
    const to = Number(range[4]);
    const inside = keys.filter((key) => key[0] === letter && from <= Number(key.slice(1)) && Number(key.slice(1)) <= to);
    if (inside.length) pool = inside;
  }
  return pool[0] ?? "?";
}

function pack(doc: NosologyDoc): CatalogDocument {
  return {
    id: doc.id,
    name: doc.name,
    age: doc.age_category,
    year: (doc.publish_date ?? "").slice(0, 4),
    mkb10: doc.mkb10,
  };
}

function codesSlug(codes: string): string {
  return codes.toLowerCase().replace(/–/g, "-").replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "");
}

function groupKey(shelfId: string, name: string, codes: string): string {
  const slug = SPLIT_SLUG[name] ?? codesSlug(codes);
  if (!slug) throw new Error(`empty key for ${name}`);
  return `group:${shelfId}/${slug}`;
}

interface Pending {
  name: string;
  shelfId: string;
  codes: string;
  documents: CatalogDocument[];
}

export function buildCatalog(nosology: Nosology): CatalogSnapshot {
  if (nosology.snapshot_date !== SNAPSHOT_DATE) {
    throw new Error(`expected snapshot ${SNAPSHOT_DATE}, got ${nosology.snapshot_date}`);
  }
  const pending: Pending[] = [];
  for (const chapter of nosology.chapters) {
    const chapterName = CHAPTER_GROUP[chapter.id];
    if (chapterName) {
      const first = chapter.blocks[0];
      if (!first) throw new Error(`chapter ${chapter.id} has no blocks`);
      pending.push({
        name: chapterName,
        shelfId: shelfOf(chapter.id, first.id),
        codes: chapter.range,
        documents: chapter.blocks.flatMap((block) => block.documents.map(pack)),
      });
      continue;
    }
    for (const block of chapter.blocks) {
      const shelfId = shelfOf(chapter.id, block.id);
      const moved = CHAPTER_NAME[chapter.id];
      if (moved) {
        pending.push({ name: moved, shelfId, codes: block.range, documents: block.documents.map(pack) });
        continue;
      }
      const byId = BY_ID[block.id];
      if (byId) {
        const found = new Map<string, CatalogDocument[]>(byId.map(([name]) => [name, []]));
        const idmap = new Map<string, string>();
        for (const [name, ids] of byId) for (const id of ids) idmap.set(id, name);
        for (const doc of block.documents) {
          const name = idmap.get(doc.id);
          if (!name) throw new Error(`unassigned ${doc.id} in ${block.id}`);
          found.get(name)?.push(pack(doc));
        }
        for (const [name] of byId) pending.push({ name, shelfId, codes: block.range, documents: found.get(name) ?? [] });
        continue;
      }
      const rules = BY_RUBRIC[block.id];
      if (rules) {
        const found = new Map<string, CatalogDocument[]>(rules.map(([name]) => [name, []]));
        const rest = rules.find(([, rubrics]) => rubrics === null)?.[0];
        for (const doc of block.documents) {
          const key = rubricOf(block, doc);
          const match = rules.find(([, rubrics]) => rubrics?.includes(key));
          const name = match?.[0] ?? rest;
          if (!name) throw new Error(`unplaced ${doc.id} ${key} ${block.id}`);
          found.get(name)?.push(pack(doc));
        }
        for (const [name] of rules) pending.push({ name, shelfId, codes: block.range, documents: found.get(name) ?? [] });
        continue;
      }
      pending.push({ name: block.title, shelfId, codes: block.range, documents: block.documents.map(pack) });
    }
  }

  const shelves: CatalogShelf[] = SHELVES.map((shelf) => ({
    catalogKey: `shelf:${shelf.id}`,
    id: shelf.id,
    name: shelf.name,
    range: shelf.range,
  }));
  const groups: CatalogGroup[] = pending.map((item) => ({
    catalogKey: groupKey(item.shelfId, item.name, item.codes),
    shelfKey: `shelf:${item.shelfId}`,
    name: item.name,
    codes: item.codes,
    documents: item.documents,
  }));

  const keys = new Set<string>();
  const names = new Map<string, Set<string>>();
  const ids = new Set<string>();
  for (const group of groups) {
    if (group.name.length > NAME_LIMIT) throw new Error(`name longer than ${NAME_LIMIT}: ${group.name}`);
    if (keys.has(group.catalogKey)) throw new Error(`duplicate key ${group.catalogKey}`);
    keys.add(group.catalogKey);
    const taken = names.get(group.shelfKey) ?? new Set<string>();
    if (taken.has(group.name)) throw new Error(`duplicate name on ${group.shelfKey}: ${group.name}`);
    taken.add(group.name);
    names.set(group.shelfKey, taken);
    if (group.documents.length === 0) throw new Error(`empty group ${group.catalogKey}`);
    for (const doc of group.documents) {
      if (ids.has(doc.id)) throw new Error(`duplicate document ${doc.id}`);
      ids.add(doc.id);
    }
  }
  if (groups.length !== 182) throw new Error(`expected 182 groups, got ${groups.length}`);
  if (ids.size !== 781) throw new Error(`expected 781 documents, got ${ids.size}`);
  return { snapshot: SNAPSHOT_DATE, shelves, groups };
}

const here = path.dirname(fileURLToPath(import.meta.url));

function isDirectRun(): boolean {
  const entry = process.argv[1];
  if (!entry) return false;
  return path.resolve(entry) === fileURLToPath(import.meta.url);
}

if (isDirectRun()) {
  const source = process.argv[2] ?? path.join(homedir(), "ClinRec", "data", "nosology.json");
  const target = process.argv[3] ?? path.join(here, "knowledge-groups.json");
  const nosology = JSON.parse(readFileSync(source, "utf8")) as Nosology;
  const catalog = buildCatalog(nosology);
  writeFileSync(target, `${JSON.stringify(catalog, null, 2)}\n`);
  console.log(`${catalog.shelves.length} shelves, ${catalog.groups.length} groups, ${catalog.groups.reduce((sum, group) => sum + group.documents.length, 0)} documents → ${target}`);
}
