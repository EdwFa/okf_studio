/**
 * The studio's working store: domains, groups, documents and their sections.
 *
 * Everything is plain files under the data directory (by default
 * `~/.okf-studio/`), so the store can be read, backed up and repaired by hand:
 *
 *   studio.json                 domains and their groups, in display order
 *   log.md                      append-only journal of every change
 *   docs/<docId>/meta.json      the document's card: group, metadata, status, counts
 *   docs/<docId>/source/<file>  the original uploaded file
 *   docs/<docId>/text.txt       the text extracted from it
 *   docs/<docId>/auto.json      the sections as the automatic split produced them
 *   docs/<docId>/sections.json  the working sections: the automatic split plus manual edits
 *   docs/<docId>/history.jsonl  the document's edit history
 *
 * Manual edits live in sections.json only; auto.json is never edited, so the
 * automatic result can always be compared with or restored.
 *
 * A section's text is the single source of truth for its recommendations: they
 * are read back from the markup in the body (okf-core/recs.ts).
 *
 * All operations are synchronous and the server is one process, so no two
 * changes interleave.
 */
import crypto from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import {
  appendLogEntry,
  normalizeBody,
  parseBody,
  recommendationsOf,
  sectionLabel,
  serializeBody,
  splitIntoSections,
  structureRecommendations,
  type KnowledgeSection,
  type RecBlock,
  type Recommendation,
} from "okf-core";

export const MAX_DOCUMENT_BYTES = 100 * 1024 * 1024;
export const EXTENSIONS = [".pdf", ".docx", ".md", ".markdown", ".txt"] as const;
export const DOCUMENT_KINDS = ["guideline", "standard", "order", "article", "manual", "other"] as const;
const MAX_TEXT_CHARS = 5_000_000;
const ID_RE = /^[a-z0-9]{6,16}$/;
const CATALOG_KEY_RE = /^(?:shelf:[a-z0-9]+|group:[a-z0-9]+\/[a-z0-9-]+)$/;
const catalogKeyOf = (value: unknown): string | undefined => (typeof value === "string" && CATALOG_KEY_RE.test(value) ? value : undefined);

export type DocumentKind = (typeof DOCUMENT_KINDS)[number];
export type DocumentStatus = "draft" | "reviewed" | "published";
export type SectionStatus = "draft" | "reviewed";
export type JobState = "queued" | "processing" | "ready" | "failed";

export interface Group {
  id: string;
  name: string;
  description: string;
  /** Hidden groups are left out when publishing to agents. */
  hidden: boolean;
  /** The group this one sits inside; absent at the top level of its domain. Groups nest to any depth. */
  parentId?: string;
  /** Stable id from the classifier snapshot. Absent on a group a person created by hand. */
  catalogKey?: string;
}

export interface Domain {
  id: string;
  name: string;
  description: string;
  /** Who answers for the domain's content. */
  owner: string;
  groups: Group[];
  /** Stable id from the classifier snapshot. Absent on a domain a person created by hand. */
  catalogKey?: string;
}

export interface DocumentMeta {
  id: string;
  groupId: string;
  title: string;
  /** One line telling an agent when this document is the one to read. */
  description: string;
  kind: DocumentKind;
  /** Original file name, kept under `source/`. */
  sourceName: string;
  /** Where the document comes from: publisher, and a link. */
  origin: string;
  url: string;
  year?: number;
  version: string;
  /** ISO dates (YYYY-MM-DD) or "". */
  approvedAt: string;
  reviewDue: string;
  icd10: string[];
  tags: string[];
  status: DocumentStatus;
  job: { state: JobState; error?: string };
  chars: number;
  pages?: number;
  sections: number;
  reviewedSections: number;
  recommendations: number;
  addedAt: string;
  updatedAt: string;
  /** When the document was last published to Luka. */
  publishedAt?: string;
  /** When the document was last marked as checked. */
  reviewedAt?: string;
}

export interface Section {
  id: string;
  /** Heading number as printed ("2.4.1"), when the heading is numbered. */
  number?: string;
  /** Heading text without its number. */
  heading: string;
  /** 1 for top-level parts; derived from the parent chain. */
  level: number;
  parentId?: string;
  pageStart?: number;
  pageEnd?: number;
  /** Section text with recommendations marked up. */
  body: string;
  /** File-name stem used on export, without its order prefix. */
  slugBase: string;
  status: SectionStatus;
  /** When the section was last marked as checked. */
  reviewedAt?: string;
  /** Changed by hand since the automatic split. */
  edited: boolean;
}

export interface SectionView extends Section {
  title: string;
  recommendations: Recommendation[];
}

export interface DocumentView {
  doc: DocumentMeta;
  sections: SectionView[];
  domain: { id: string; name: string } | null;
  group: { id: string; name: string } | null;
}

export interface HistoryEntry {
  at: string;
  action: string;
  detail?: string;
}

export class StoreError extends Error {
  readonly status: 400 | 404 | 409 | 413 | 422;

  constructor(message: string, status: 400 | 404 | 409 | 413 | 422 = 400) {
    super(message);
    this.status = status;
  }
}

type Rec = Record<string, unknown>;
const isRecord = (value: unknown): value is Rec => Boolean(value) && typeof value === "object" && !Array.isArray(value);
const line = (value: unknown, max: number): string => (typeof value === "string" ? value.replace(/\s+/g, " ").trim().slice(0, max) : "");
const newId = (): string => crypto.randomBytes(5).toString("hex");
const now = (): string => new Date().toISOString();
const DATE_RE = /^\d{4}-\d{2}-\d{2}$/;

export const sectionTitle = (section: { number?: string; heading: string }): string =>
  section.number ? `${section.number} ${section.heading}`.trim() : section.heading;

function writeFile(file: string, content: string): void {
  fs.mkdirSync(path.dirname(file), { recursive: true, mode: 0o700 });
  const tmp = `${file}.${process.pid}.tmp`;
  fs.writeFileSync(tmp, content, { encoding: "utf-8", mode: 0o600 });
  fs.renameSync(tmp, file);
}

const writeJson = (file: string, value: unknown): void => writeFile(file, `${JSON.stringify(value, null, 2)}\n`);

function readJson(file: string): unknown {
  try {
    return JSON.parse(fs.readFileSync(file, "utf-8"));
  } catch (exc) {
    if ((exc as NodeJS.ErrnoException).code === "ENOENT") return undefined;
    throw new StoreError(`Файл ${path.basename(file)} повреждён: исправьте или удалите его`, 409);
  }
}

function stringList(value: unknown, max: number, each: (item: string) => string = (item) => item): string[] {
  const items = Array.isArray(value) ? value : typeof value === "string" ? value.split(/[,;\n]/) : [];
  const out: string[] = [];
  for (const item of items) {
    const text = each(line(item, 60));
    if (text && !out.includes(text)) out.push(text);
    if (out.length >= max) break;
  }
  return out;
}

/** ICD-10 codes as printed in Russian documents often use Cyrillic look-alike letters. */
const CYRILLIC_ICD: Record<string, string> = { А: "A", В: "B", С: "C", Е: "E", Н: "H", К: "K", М: "M", О: "O", Р: "P", Т: "T", Х: "X" };
function icdCode(value: string): string {
  const code = value.toUpperCase().replace(/\s+/g, "").replace(/^[А-Я]/u, (letter) => CYRILLIC_ICD[letter] ?? letter).replace(",", ".");
  return /^[A-Z]\d{2}(\.\d{1,2})?(-[A-Z]\d{2}(\.\d{1,2})?)?$/.test(code) ? code : "";
}

/** What a guideline's title page says about itself; a starting point the user checks. */
export function guessMetadata(text: string, fileName = ""): { year?: number; icd10: string[]; kind: DocumentKind } {
  const head = text.slice(0, 6000);
  // The title page says it best; a file name like "КР Рак ротоглотки 2024.pdf" is the fallback.
  const year = /Год\s+утверждения[^\d]{0,60}((?:19|20)\d{2})/iu.exec(head) ?? /(?<!\d)((?:19|20)\d{2})(?!\d)/.exec(fileName);
  const icd: string[] = [];
  const icdBlock = /(?:МКБ|Международной\s+статистической\s+классификации)[^\n]*\n?([\s\S]{0,400})/iu.exec(head);
  if (icdBlock) {
    for (const match of (icdBlock[0] ?? "").matchAll(/(?<![A-Za-zА-Яа-я\d])[A-ZАВСЕНКМОРТХ]\s?\d{2}(?:[.,]\d{1,2})?(?![\d])/gu)) {
      const code = icdCode(match[0]);
      if (code && !icd.includes(code) && icd.length < 20) icd.push(code);
    }
  }
  const guideline = /клинические\s+рекомендации/iu.test(head) || /^КР(?![А-Яа-яЁё])|клинич\S*\s+рекомендац/iu.test(fileName.normalize("NFC"));
  const kind: DocumentKind = guideline ? "guideline" : "other";
  return { ...(year ? { year: Number(year[1]) } : {}), icd10: icd, kind };
}

function defaultDescription(body: string): string {
  const first = body
    .split(/\n+/)
    .map((row) => row.replace(/<!--.*?-->/g, "").replace(/^#+\s*/, "").trim())
    .filter((row) => row.length > 20)
    .slice(0, 2)
    .join(" ");
  return line(first, 240);
}

export class Store {
  readonly root: string;
  private catalog: { domains: Domain[] };
  private readonly docs = new Map<string, DocumentMeta>();

  constructor(root: string) {
    this.root = root;
    fs.mkdirSync(path.join(root, "docs"), { recursive: true, mode: 0o700 });
    this.catalog = this.loadCatalog();
    for (const entry of fs.readdirSync(path.join(root, "docs"))) {
      if (!ID_RE.test(entry)) continue;
      const meta = readJson(path.join(root, "docs", entry, "meta.json"));
      if (isRecord(meta) && meta.id === entry) this.docs.set(entry, meta as unknown as DocumentMeta);
    }
  }

  // ---- files ------------------------------------------------------------------

  docDir(docId: string): string {
    return path.join(this.root, "docs", docId);
  }

  sourcePath(doc: DocumentMeta): string {
    return path.join(this.docDir(doc.id), "source", doc.sourceName);
  }

  private loadCatalog(): { domains: Domain[] } {
    const raw = readJson(path.join(this.root, "studio.json"));
    const domains: Domain[] = [];
    for (const value of isRecord(raw) && Array.isArray(raw.domains) ? raw.domains : []) {
      if (!isRecord(value) || typeof value.id !== "string" || !ID_RE.test(value.id)) continue;
      const groups: Group[] = [];
      for (const item of Array.isArray(value.groups) ? value.groups : []) {
        if (!isRecord(item) || typeof item.id !== "string" || !ID_RE.test(item.id)) continue;
        const groupKey = catalogKeyOf(item.catalogKey);
        groups.push({
          id: item.id,
          name: line(item.name, 120) || "Без названия",
          description: line(item.description, 500),
          hidden: item.hidden === true,
          ...(typeof item.parentId === "string" ? { parentId: item.parentId } : {}),
          ...(groupKey ? { catalogKey: groupKey } : {}),
        });
      }
      // A parent link must point to a group of the same domain and never loop.
      const byId = new Map(groups.map((group) => [group.id, group]));
      for (const group of groups) {
        const seen = new Set([group.id]);
        for (let up = group.parentId; up; up = byId.get(up)?.parentId) {
          if (!byId.has(up) || seen.has(up)) {
            delete group.parentId;
            break;
          }
          seen.add(up);
        }
      }
      const domainKey = catalogKeyOf(value.catalogKey);
      domains.push({
        id: value.id,
        name: line(value.name, 120) || "Без названия",
        description: line(value.description, 500),
        owner: line(value.owner, 120),
        groups,
        ...(domainKey ? { catalogKey: domainKey } : {}),
      });
    }
    return { domains };
  }

  private saveCatalog(entry: string): void {
    writeJson(path.join(this.root, "studio.json"), { version: 1, domains: this.catalog.domains });
    this.log(entry);
  }

  private log(entry: string): void {
    // Laid out as OKF 0.2 defines log.md: dates as headings, newest first.
    const file = path.join(this.root, "log.md");
    writeFile(file, appendLogEntry(fs.existsSync(file) ? fs.readFileSync(file, "utf-8") : undefined, "OKF Studio: журнал изменений", entry));
  }

  private saveDoc(doc: DocumentMeta): void {
    doc.updatedAt = now();
    this.docs.set(doc.id, doc);
    writeJson(path.join(this.docDir(doc.id), "meta.json"), doc);
  }

  private record(doc: DocumentMeta, action: string, detail?: string): void {
    const entry: HistoryEntry = { at: now(), action, ...(detail ? { detail } : {}) };
    fs.appendFileSync(path.join(this.docDir(doc.id), "history.jsonl"), `${JSON.stringify(entry)}\n`, "utf-8");
    this.log(`«${doc.title}»: ${action}${detail ? ` — ${detail}` : ""}`);
  }

  // ---- catalog ----------------------------------------------------------------

  /** Domains and groups with document counts per group. */
  catalogView(): { domains: (Omit<Domain, "groups"> & { groups: (Group & { documents: number; reviewed: number; failed: number; busy: number })[] })[] } {
    const counts = new Map<string, { documents: number; reviewed: number; failed: number; busy: number }>();
    for (const doc of this.docs.values()) {
      const count = counts.get(doc.groupId) ?? { documents: 0, reviewed: 0, failed: 0, busy: 0 };
      count.documents += 1;
      if (doc.status !== "draft") count.reviewed += 1;
      if (doc.job.state === "failed") count.failed += 1;
      if (doc.job.state === "queued" || doc.job.state === "processing") count.busy += 1;
      counts.set(doc.groupId, count);
    }
    return {
      domains: this.catalog.domains.map((domain) => ({
        ...domain,
        groups: domain.groups.map((group) => ({ ...group, ...(counts.get(group.id) ?? { documents: 0, reviewed: 0, failed: 0, busy: 0 }) })),
      })),
    };
  }

  private domain(id: string): Domain {
    const domain = this.catalog.domains.find((candidate) => candidate.id === id);
    if (!domain) throw new StoreError("Домен не найден", 404);
    return domain;
  }

  private groupWithDomain(id: string): { domain: Domain; group: Group } {
    for (const domain of this.catalog.domains) {
      const group = domain.groups.find((candidate) => candidate.id === id);
      if (group) return { domain, group };
    }
    throw new StoreError("Группа не найдена", 404);
  }

  findGroup(id: string): { domain: Domain; group: Group } | null {
    try {
      return this.groupWithDomain(id);
    } catch {
      return null;
    }
  }

  private uniqueName(value: unknown, taken: { id: string; name: string }[], exceptId: string | undefined, what: string): string {
    const name = line(value, 120);
    if (!name) throw new StoreError("Название не может быть пустым");
    if (taken.some((item) => item.id !== exceptId && item.name.toLowerCase() === name.toLowerCase())) {
      throw new StoreError(`${what} «${name}» уже есть`, 409);
    }
    return name;
  }

  private claimCatalogKey(value: unknown): string | undefined {
    if (value === undefined) return undefined;
    const key = catalogKeyOf(value);
    if (!key) throw new StoreError("Ключ каталога задан неверно");
    for (const domain of this.catalog.domains) {
      if (domain.catalogKey === key) throw new StoreError("Такой ключ каталога уже есть", 409);
      if (domain.groups.some((group) => group.catalogKey === key)) throw new StoreError("Такой ключ каталога уже есть", 409);
    }
    return key;
  }

  createDomain(input: unknown): Domain {
    const body = isRecord(input) ? input : {};
    const catalogKey = this.claimCatalogKey(body.catalogKey);
    const domain: Domain = {
      id: newId(),
      name: this.uniqueName(body.name, this.catalog.domains, undefined, "Домен"),
      description: line(body.description, 500),
      owner: line(body.owner, 120),
      groups: [],
      ...(catalogKey ? { catalogKey } : {}),
    };
    this.catalog.domains.push(domain);
    this.saveCatalog(`домен создан: ${domain.name}`);
    return domain;
  }

  updateDomain(id: string, input: unknown): Domain {
    if (!isRecord(input)) throw new StoreError("Ожидается объект JSON");
    const domain = this.domain(id);
    if (input.name !== undefined) domain.name = this.uniqueName(input.name, this.catalog.domains, id, "Домен");
    if (input.description !== undefined) domain.description = line(input.description, 500);
    if (input.owner !== undefined) domain.owner = line(input.owner, 120);
    this.saveCatalog(`домен изменён: ${domain.name}`);
    return domain;
  }

  /** Only an empty domain can be deleted: documents are never removed as a side effect. */
  deleteDomain(id: string): void {
    const domain = this.domain(id);
    if (domain.groups.length) throw new StoreError("В домене есть группы. Сначала удалите или перенесите их.", 409);
    this.catalog.domains = this.catalog.domains.filter((candidate) => candidate.id !== id);
    this.saveCatalog(`домен удалён: ${domain.name}`);
  }

  private static reorder<T extends { id: string }>(items: T[], order: unknown): T[] {
    const ids = Array.isArray(order) ? order.filter((id): id is string => typeof id === "string") : [];
    const known = new Map(items.map((item) => [item.id, item]));
    if (ids.length !== known.size || new Set(ids).size !== ids.length || ids.some((id) => !known.has(id))) {
      throw new StoreError("Порядок должен перечислять каждый элемент ровно один раз");
    }
    return ids.map((id) => known.get(id)!);
  }

  reorderDomains(order: unknown): void {
    this.catalog.domains = Store.reorder(this.catalog.domains, order);
    this.saveCatalog("порядок доменов изменён");
  }

  reorderGroups(domainId: string, order: unknown): void {
    const domain = this.domain(domainId);
    domain.groups = Store.reorder(domain.groups, order);
    this.saveCatalog(`порядок групп изменён: ${domain.name}`);
  }

  /** The group's names from the top of its domain down: "Клинические рекомендации / Минздрав". */
  groupPath(id: string): string {
    const { domain, group } = this.groupWithDomain(id);
    const names = [group.name];
    for (let up = group.parentId; up; ) {
      const parent = domain.groups.find((candidate) => candidate.id === up);
      if (!parent) break;
      names.unshift(parent.name);
      up = parent.parentId;
    }
    return names.join(" / ");
  }

  private static siblings(domain: Domain, parentId: string | undefined): Group[] {
    return domain.groups.filter((candidate) => candidate.parentId === parentId);
  }

  /** The group and everything nested in it. */
  private static subtree(domain: Domain, id: string): Group[] {
    const out = domain.groups.filter((candidate) => candidate.id === id);
    for (let index = 0; index < out.length; index += 1) out.push(...Store.siblings(domain, out[index]!.id));
    return out;
  }

  private parentIn(domain: Domain, value: unknown): string | undefined {
    if (value === undefined || value === null || value === "") return undefined;
    if (typeof value !== "string" || !domain.groups.some((candidate) => candidate.id === value)) throw new StoreError("Родительская группа не найдена в этом домене", 404);
    return value;
  }

  /** Create a group in the domain, at the top level or inside `parentId`. */
  createGroup(domainId: string, input: unknown): Group {
    const body = isRecord(input) ? input : {};
    const domain = this.domain(domainId);
    const parentId = this.parentIn(domain, body.parentId);
    if (body.hidden !== undefined && typeof body.hidden !== "boolean") throw new StoreError("hidden должно быть true или false");
    const catalogKey = this.claimCatalogKey(body.catalogKey);
    const group: Group = {
      id: newId(),
      name: this.uniqueName(body.name, Store.siblings(domain, parentId), undefined, "Группа"),
      description: line(body.description, 500),
      hidden: body.hidden === true,
      ...(parentId ? { parentId } : {}),
      ...(catalogKey ? { catalogKey } : {}),
    };
    domain.groups.push(group);
    this.saveCatalog(`группа создана: ${domain.name} / ${this.groupPath(group.id)}`);
    return group;
  }

  /** Set visibility of many groups and write the catalog once. */
  setHidden(updates: { id: string; hidden: boolean }[]): void {
    let changed = false;
    for (const update of updates) {
      const { group } = this.groupWithDomain(update.id);
      if (group.hidden === update.hidden) continue;
      group.hidden = update.hidden;
      changed = true;
    }
    if (changed) this.saveCatalog("видимость полок каталога изменена");
  }

  /**
   * Rename, describe, hide, or move the group: into another group (`parentId`,
   * empty for the top level) or to another domain (`domainId`). Whatever is
   * nested in the group moves with it.
   */
  updateGroup(id: string, input: unknown): Group {
    if (!isRecord(input)) throw new StoreError("Ожидается объект JSON");
    const { domain, group } = this.groupWithDomain(id);
    const target = typeof input.domainId === "string" && input.domainId !== domain.id ? this.domain(input.domainId) : domain;
    const moved = Store.subtree(domain, id);
    // In another domain the group lands at the top level unless a parent there is named.
    const parentId = input.parentId !== undefined || target !== domain ? this.parentIn(target, input.parentId) : group.parentId;
    if (parentId && moved.some((item) => item.id === parentId)) throw new StoreError("Группу нельзя перенести в саму себя или в свою подгруппу");
    if (input.name !== undefined || target !== domain || parentId !== group.parentId) {
      group.name = this.uniqueName(input.name ?? group.name, Store.siblings(target, parentId), id, "Группа");
    }
    if (parentId) group.parentId = parentId;
    else delete group.parentId;
    if (input.description !== undefined) group.description = line(input.description, 500);
    if (input.hidden !== undefined) {
      if (typeof input.hidden !== "boolean") throw new StoreError("hidden должно быть true или false");
      group.hidden = input.hidden;
    }
    if (target !== domain) {
      domain.groups = domain.groups.filter((candidate) => !moved.includes(candidate));
      target.groups.push(...moved);
    }
    this.saveCatalog(`группа изменена: ${target.name} / ${this.groupPath(group.id)}`);
    return group;
  }

  deleteGroup(id: string): void {
    const { domain, group } = this.groupWithDomain(id);
    if (Store.siblings(domain, id).length) throw new StoreError("В группе есть подгруппы. Сначала удалите или перенесите их.", 409);
    if ([...this.docs.values()].some((doc) => doc.groupId === id)) {
      throw new StoreError("В группе есть документы. Сначала удалите или перенесите их.", 409);
    }
    domain.groups = domain.groups.filter((candidate) => candidate.id !== id);
    this.saveCatalog(`группа удалена: ${domain.name} / ${group.name}`);
  }

  // ---- documents --------------------------------------------------------------

  documentsOf(groupId: string): DocumentMeta[] {
    this.groupWithDomain(groupId);
    return [...this.docs.values()].filter((doc) => doc.groupId === groupId).sort((a, b) => a.title.localeCompare(b.title, "ru"));
  }

  allDocuments(): DocumentMeta[] {
    return [...this.docs.values()];
  }

  doc(id: string): DocumentMeta {
    const doc = this.docs.get(id);
    if (!doc) throw new StoreError("Документ не найден", 404);
    return doc;
  }

  /** Register an uploaded file (already on disk at `upload`) as a queued document; the file is moved into the store. */
  addDocument(groupId: string, upload: string, filename: string): DocumentMeta {
    this.groupWithDomain(groupId);
    const sourceName = path.basename(filename).normalize("NFC").replace(/[\0/\\]/g, "_") || "document";
    const ext = path.extname(sourceName).toLowerCase();
    if (!(EXTENSIONS as readonly string[]).includes(ext)) {
      throw new StoreError(`Формат ${ext || "без расширения"} не поддерживается. Подходят: ${EXTENSIONS.join(", ")}`, 422);
    }
    const id = newId();
    const stamp = now();
    const doc: DocumentMeta = {
      id,
      groupId,
      title: line(path.basename(sourceName, path.extname(sourceName)).replace(/[_]+/g, " "), 200) || "Документ",
      description: "",
      kind: "other",
      sourceName,
      origin: "",
      url: "",
      version: "",
      approvedAt: "",
      reviewDue: "",
      icd10: [],
      tags: [],
      status: "draft",
      job: { state: "queued" },
      chars: 0,
      sections: 0,
      reviewedSections: 0,
      recommendations: 0,
      addedAt: stamp,
      updatedAt: stamp,
    };
    fs.mkdirSync(path.join(this.docDir(id), "source"), { recursive: true, mode: 0o700 });
    fs.renameSync(upload, this.sourcePath(doc));
    this.saveDoc(doc);
    this.record(doc, "документ загружен", sourceName);
    return doc;
  }

  setJob(id: string, state: JobState, error?: string): void {
    const doc = this.docs.get(id);
    if (!doc) return;
    doc.job = { state, ...(error ? { error } : {}) };
    this.saveDoc(doc);
    if (state === "failed") this.record(doc, "разбор не удался", error);
  }

  /** Store the extracted text and split it. Called by the background job; replaces any existing sections. */
  setText(id: string, text: string, pages?: number): DocumentMeta {
    const doc = this.doc(id);
    const clean = text.normalize("NFC").trim();
    if (!clean) throw new StoreError("В файле не найден текст. Если это скан, нужен текстовый слой (распознавание появится на следующем этапе).", 422);
    if (clean.length > MAX_TEXT_CHARS) throw new StoreError("Текст документа слишком велик", 413);
    writeFile(path.join(this.docDir(id), "text.txt"), `${clean}\n`);
    doc.chars = clean.length;
    if (pages) doc.pages = pages;
    if (!doc.description) doc.description = defaultDescription(clean);
    const guess = guessMetadata(clean, doc.sourceName);
    if (doc.year === undefined && guess.year) doc.year = guess.year;
    if (!doc.icd10.length) doc.icd10 = guess.icd10;
    if (doc.kind === "other") doc.kind = guess.kind;
    const sections = this.autoSplit(doc, clean);
    this.saveSections(doc, sections);
    doc.job = { state: "ready" };
    doc.status = "draft";
    this.saveDoc(doc);
    this.record(doc, "документ разобран", `${doc.sections} разделов, ${doc.recommendations} рекомендаций`);
    return doc;
  }

  private autoSplit(doc: DocumentMeta, text: string): Section[] {
    const split = splitIntoSections(text);
    const sections = split.length ? fromCore(split) : [wholeSection(doc.title, text)];
    writeJson(path.join(this.docDir(doc.id), "auto.json"), sections);
    return sections;
  }

  text(id: string): string {
    this.doc(id);
    const file = path.join(this.docDir(id), "text.txt");
    return fs.existsSync(file) ? fs.readFileSync(file, "utf-8") : "";
  }

  rawSections(id: string): Section[] {
    const raw = readJson(path.join(this.docDir(id), "sections.json"));
    return Array.isArray(raw) ? (raw as Section[]) : [];
  }

  private saveSections(doc: DocumentMeta, sections: Section[]): void {
    relevel(sections);
    writeJson(path.join(this.docDir(doc.id), "sections.json"), sections);
    doc.sections = sections.length;
    doc.reviewedSections = sections.filter((section) => section.status === "reviewed").length;
    doc.recommendations = sections.reduce((sum, section) => sum + recommendationsOf(section.body).length, 0);
  }

  view(id: string): DocumentView {
    const doc = this.doc(id);
    const place = this.findGroup(doc.groupId);
    return {
      doc,
      sections: this.rawSections(id).map((section) => ({ ...section, title: sectionTitle(section), recommendations: recommendationsOf(section.body) })),
      domain: place ? { id: place.domain.id, name: place.domain.name } : null,
      group: place ? { id: place.group.id, name: place.group.name } : null,
    };
  }

  history(id: string): HistoryEntry[] {
    this.doc(id);
    const file = path.join(this.docDir(id), "history.jsonl");
    if (!fs.existsSync(file)) return [];
    const rows = fs.readFileSync(file, "utf-8").split("\n").filter(Boolean);
    return rows.slice(-300).map((row) => JSON.parse(row) as HistoryEntry).reverse();
  }

  updateDocument(id: string, input: unknown): DocumentView {
    if (!isRecord(input)) throw new StoreError("Ожидается объект JSON");
    const doc = this.doc(id);
    const changed: string[] = [];
    const set = <K extends keyof DocumentMeta>(key: K, value: DocumentMeta[K], label: string) => {
      if (JSON.stringify(doc[key]) === JSON.stringify(value)) return;
      doc[key] = value;
      changed.push(label);
    };
    if (input.title !== undefined) {
      const title = line(input.title, 200);
      if (!title) throw new StoreError("Название не может быть пустым");
      set("title", title, "название");
    }
    if (input.description !== undefined) set("description", line(input.description, 500), "описание");
    if (input.kind !== undefined) {
      if (!(DOCUMENT_KINDS as readonly unknown[]).includes(input.kind)) throw new StoreError("Неизвестный тип документа");
      set("kind", input.kind as DocumentKind, "тип");
    }
    if (input.origin !== undefined) set("origin", line(input.origin, 300), "источник");
    if (input.url !== undefined) {
      const url = line(input.url, 500);
      if (url && !/^https?:\/\//i.test(url)) throw new StoreError("Ссылка должна начинаться с http:// или https://");
      set("url", url, "ссылка");
    }
    if (input.year !== undefined) {
      const year = input.year === null || input.year === "" ? undefined : Number(input.year);
      if (year !== undefined && (!Number.isInteger(year) || year < 1900 || year > 2100)) throw new StoreError("Год указан неверно");
      if (doc.year !== year) {
        if (year === undefined) delete doc.year;
        else doc.year = year;
        changed.push("год");
      }
    }
    if (input.version !== undefined) set("version", line(input.version, 60), "версия");
    for (const [key, label] of [["approvedAt", "дата утверждения"], ["reviewDue", "срок пересмотра"]] as const) {
      if (input[key] === undefined) continue;
      const value = line(input[key], 10);
      if (value && !DATE_RE.test(value)) throw new StoreError(`Поле «${label}»: нужна дата в виде ГГГГ-ММ-ДД`);
      set(key, value, label);
    }
    if (input.icd10 !== undefined) {
      const raw = stringList(input.icd10, 50);
      const codes = raw.map(icdCode);
      const bad = raw.filter((_, index) => !codes[index]);
      if (bad.length) throw new StoreError(`Не похоже на код МКБ-10: ${bad.join(", ")}`);
      set("icd10", [...new Set(codes)], "коды МКБ-10");
    }
    if (input.tags !== undefined) set("tags", stringList(input.tags, 30), "теги");
    if (input.groupId !== undefined && input.groupId !== doc.groupId) {
      if (typeof input.groupId !== "string") throw new StoreError("groupId должен быть строкой");
      const { domain, group } = this.groupWithDomain(input.groupId);
      doc.groupId = group.id;
      changed.push(`перенесён в «${domain.name} / ${group.name}»`);
    }
    if (input.status !== undefined && input.status !== doc.status) {
      if (input.status !== "draft" && input.status !== "reviewed") throw new StoreError("Статус может быть «черновик» или «проверено»");
      if (doc.job.state !== "ready") throw new StoreError("Документ ещё не разобран", 409);
      doc.status = input.status;
      if (input.status === "reviewed") doc.reviewedAt = now();
      changed.push(input.status === "reviewed" ? "отмечен как проверенный" : "возвращён в черновики");
    }
    if (input.sectionsStatus !== undefined) {
      if (input.sectionsStatus !== "draft" && input.sectionsStatus !== "reviewed") throw new StoreError("Неизвестный статус разделов");
      const sections = this.rawSections(id);
      for (const section of sections) {
        if (input.sectionsStatus === "reviewed" && section.status !== "reviewed") section.reviewedAt = now();
        section.status = input.sectionsStatus;
      }
      this.saveSections(doc, sections);
      changed.push(input.sectionsStatus === "reviewed" ? "все разделы отмечены проверенными" : "проверка снята со всех разделов");
    }
    if (changed.length) {
      this.saveDoc(doc);
      this.record(doc, "карточка изменена", changed.join(", "));
    }
    return this.view(id);
  }

  deleteDocument(id: string): void {
    const doc = this.doc(id);
    fs.rmSync(this.docDir(id), { recursive: true, force: true });
    this.docs.delete(id);
    this.log(`документ удалён: «${doc.title}» (${doc.sourceName})`);
  }

  /** Throw away manual edits and split the stored text again. */
  resplit(id: string): DocumentView {
    const doc = this.doc(id);
    const text = this.text(id).trim();
    if (!text) throw new StoreError("У документа нет извлечённого текста", 409);
    this.saveSections(doc, this.autoSplit(doc, text));
    doc.status = "draft";
    this.saveDoc(doc);
    this.record(doc, "разбит заново", "ручные правки разделов сброшены");
    return this.view(id);
  }

  /** After publishing: the given documents of the group are "опубликовано". */
  markPublished(groupId: string, docIds: string[]): void {
    for (const id of docIds) {
      const doc = this.docs.get(id);
      if (!doc || doc.groupId !== groupId) continue;
      doc.status = "published";
      doc.publishedAt = now();
      this.saveDoc(doc);
      this.record(doc, "опубликован в Луку");
    }
  }

  /** After removing the group from Luka: published documents are "проверено" again. */
  markUnpublished(groupId: string): void {
    for (const doc of this.docs.values()) {
      if (doc.groupId !== groupId || !doc.publishedAt) continue;
      delete doc.publishedAt;
      if (doc.status === "published") doc.status = "reviewed";
      this.saveDoc(doc);
      this.record(doc, "снят с публикации в Луке");
    }
  }

  // ---- sections ---------------------------------------------------------------

  /** Run an edit on the document's sections, then save, mark the document a draft again and record it. */
  private edit(id: string, sectionId: string | null, run: (sections: Section[], section: Section, index: number) => { action: string; detail?: string; keepStatus?: boolean }): DocumentView {
    const doc = this.doc(id);
    if (doc.job.state !== "ready") throw new StoreError("Документ ещё не разобран", 409);
    const sections = this.rawSections(id);
    const index = sectionId === null ? 0 : sections.findIndex((section) => section.id === sectionId);
    if (index < 0 || !sections[index]) throw new StoreError("Раздел не найден", 404);
    const result = run(sections, sections[index], index);
    this.saveSections(doc, sections);
    if (!result.keepStatus && doc.status !== "draft") doc.status = "draft";
    this.saveDoc(doc);
    this.record(doc, result.action, result.detail);
    return this.view(id);
  }

  updateSection(id: string, sectionId: string, input: unknown): DocumentView {
    if (!isRecord(input)) throw new StoreError("Ожидается объект JSON");
    return this.edit(id, sectionId, (sections, section, index) => {
      const changed: string[] = [];
      let content = false;
      if (input.heading !== undefined) {
        const heading = line(input.heading, 300);
        if (!heading) throw new StoreError("Заголовок не может быть пустым");
        if (heading !== section.heading) {
          section.heading = heading;
          changed.push("заголовок");
          content = true;
        }
      }
      if (input.number !== undefined) {
        const number = line(input.number, 20);
        if (number && !/^\d{1,2}(\.\d{1,2}){0,4}$/.test(number)) throw new StoreError("Номер раздела — цифры через точку, например 2.4.1");
        if ((section.number ?? "") !== number) {
          if (number) section.number = number;
          else delete section.number;
          changed.push("номер");
          content = true;
        }
      }
      if (input.parentId !== undefined) {
        const parentId = typeof input.parentId === "string" && input.parentId ? input.parentId : undefined;
        if (parentId !== section.parentId) {
          if (parentId) {
            const parentIndex = sections.findIndex((candidate) => candidate.id === parentId);
            if (parentIndex < 0) throw new StoreError("Родительский раздел не найден", 404);
            if (parentIndex >= index) throw new StoreError("Родительский раздел должен стоять выше по тексту");
            section.parentId = parentId;
          } else delete section.parentId;
          changed.push("уровень");
          content = true;
        }
      }
      for (const key of ["pageStart", "pageEnd"] as const) {
        if (input[key] === undefined) continue;
        const page = input[key] === null || input[key] === "" ? undefined : Number(input[key]);
        if (page !== undefined && (!Number.isInteger(page) || page < 1 || page > 100000)) throw new StoreError("Номер страницы указан неверно");
        if (section[key] !== page) {
          if (page === undefined) delete section[key];
          else section[key] = page;
          changed.push("страницы");
          content = true;
        }
      }
      if (input.body !== undefined) {
        if (typeof input.body !== "string") throw new StoreError("Текст раздела должен быть строкой");
        if (input.body.length > MAX_TEXT_CHARS) throw new StoreError("Текст раздела слишком велик", 413);
        const body = input.body.normalize("NFC").replace(/\r\n?/g, "\n").trim();
        if (body !== section.body) {
          section.body = body;
          changed.push("текст");
          content = true;
        }
      }
      // Recommendation numbers follow the section's number or title.
      section.body = normalizeBody(section.body, sectionLabel({ ...(section.number ? { number: section.number } : {}), title: sectionTitle(section) }));
      if (content) {
        section.edited = true;
        section.status = "draft";
      }
      if (input.status !== undefined) {
        if (input.status !== "draft" && input.status !== "reviewed") throw new StoreError("Статус раздела может быть «черновик» или «проверено»");
        if (section.status !== input.status) {
          section.status = input.status;
          if (input.status === "reviewed") section.reviewedAt = now();
          changed.push(input.status === "reviewed" ? "проверен" : "проверка снята");
        }
      }
      return { action: "раздел изменён", detail: `${sectionTitle(section)}: ${changed.join(", ") || "без изменений"}`, keepStatus: !content };
    });
  }

  /** Cut a section in two at `offset` characters of its text; the tail becomes a new section right after it. */
  splitSection(id: string, sectionId: string, input: unknown): DocumentView {
    if (!isRecord(input)) throw new StoreError("Ожидается объект JSON");
    return this.edit(id, sectionId, (sections, section, index) => {
      const offset = Number(input.offset);
      if (!Number.isInteger(offset) || offset <= 0 || offset >= section.body.length) throw new StoreError("Поставьте курсор внутри текста раздела — там, где должен начаться новый раздел");
      const heading = line(input.heading, 300);
      if (!heading) throw new StoreError("Укажите заголовок нового раздела");
      const number = line(input.number, 20);
      if (number && !/^\d{1,2}(\.\d{1,2}){0,4}$/.test(number)) throw new StoreError("Номер раздела — цифры через точку, например 2.4.1");
      const head = section.body.slice(0, offset);
      const tail = section.body.slice(offset);
      let page = section.pageStart;
      for (const mark of head.matchAll(/<!-- page (\d+) -->/g)) page = Number(mark[1]);
      const created: Section = {
        id: newId(),
        ...(number ? { number } : {}),
        heading,
        level: section.level,
        ...(section.parentId ? { parentId: section.parentId } : {}),
        ...(page !== undefined ? { pageStart: page } : {}),
        ...(section.pageEnd !== undefined ? { pageEnd: section.pageEnd } : {}),
        body: "",
        slugBase: number || "razdel",
        status: "draft",
        edited: true,
      };
      created.body = normalizeBody(tail.replace(/^(?:\s*<!-- page \d+ -->)+/, "").trim(), sectionLabel({ ...(number ? { number } : {}), title: sectionTitle(created) }));
      section.body = normalizeBody(head.replace(/(?:<!-- page \d+ -->\s*)+$/, "").trim(), sectionLabel({ ...(section.number ? { number: section.number } : {}), title: sectionTitle(section) }));
      if (page !== undefined) section.pageEnd = page;
      section.edited = true;
      section.status = "draft";
      sections.splice(index + 1, 0, created);
      return { action: "раздел разделён", detail: `${sectionTitle(section)} → ${sectionTitle(created)}` };
    });
  }

  /** Join a section to the one before it; its heading stays in the text as a line. */
  mergeSection(id: string, sectionId: string): DocumentView {
    return this.edit(id, sectionId, (sections, section, index) => {
      const previous = sections[index - 1];
      if (!previous) throw new StoreError("Первый раздел не с чем объединять");
      const label = sectionLabel({ ...(previous.number ? { number: previous.number } : {}), title: sectionTitle(previous) });
      previous.body = normalizeBody([previous.body, sectionTitle(section), section.body].filter((part) => part.trim()).join("\n\n"), label);
      if (section.pageEnd !== undefined) previous.pageEnd = Math.max(previous.pageEnd ?? section.pageEnd, section.pageEnd);
      if (previous.pageStart === undefined && section.pageStart !== undefined) previous.pageStart = section.pageStart;
      previous.edited = true;
      previous.status = "draft";
      removeSection(sections, index);
      return { action: "разделы объединены", detail: `${sectionTitle(section)} → ${sectionTitle(previous)}` };
    });
  }

  deleteSection(id: string, sectionId: string): DocumentView {
    return this.edit(id, sectionId, (sections, section, index) => {
      if (sections.length === 1) throw new StoreError("В документе должен остаться хотя бы один раздел");
      removeSection(sections, index);
      return { action: "раздел удалён", detail: sectionTitle(section) };
    });
  }

  /**
   * Change one recommendation (`n` is its 1-based number within the section):
   * grade, evidence, text, comment. `remove: true` turns it back into plain text.
   */
  updateRecommendation(id: string, sectionId: string, n: number, input: unknown): DocumentView {
    if (!isRecord(input)) throw new StoreError("Ожидается объект JSON");
    return this.edit(id, sectionId, (_sections, section) => {
      const blocks = parseBody(section.body);
      const recs = blocks.filter((block): block is RecBlock => block.kind === "rec");
      const rec = recs[n - 1];
      if (!rec) throw new StoreError("Рекомендация не найдена", 404);
      const label = sectionLabel({ ...(section.number ? { number: section.number } : {}), title: sectionTitle(section) });
      if (input.remove === true) {
        const at = blocks.indexOf(rec);
        blocks.splice(at, 1, { kind: "text", text: [rec.text, rec.comment ? `Комментарий: ${rec.comment}` : ""].filter(Boolean).join("\n\n") });
      } else {
        if (input.grade !== undefined) {
          const grade = line(input.grade, 2).toUpperCase();
          if (grade && !/^(?:[A-C]|0)$/.test(grade)) throw new StoreError("УУР — A, B, C или 0");
          if (grade) rec.grade = grade;
          else delete rec.grade;
        }
        if (input.evidence !== undefined) {
          const evidence = line(input.evidence, 2);
          if (evidence && !/^(?:[1-5]|0)$/.test(evidence)) throw new StoreError("УДД — число от 0 до 5");
          if (evidence) rec.evidence = evidence;
          else delete rec.evidence;
        }
        if (input.text !== undefined) {
          const text = typeof input.text === "string" ? input.text.normalize("NFC").replace(/\s*\n\s*/g, " ").trim() : "";
          if (!text) throw new StoreError("Текст рекомендации не может быть пустым");
          rec.text = text;
        }
        if (input.comment !== undefined) {
          const comment = typeof input.comment === "string" ? input.comment.normalize("NFC").trim() : "";
          if (comment) rec.comment = comment;
          else delete rec.comment;
        }
      }
      section.body = serializeBody(blocks, label);
      section.edited = true;
      section.status = "draft";
      return { action: input.remove === true ? "разметка рекомендации снята" : "рекомендация изменена", detail: `${label}/${n}` };
    });
  }
}

/** Parent links and levels must agree; an orphaned parent link is dropped. */
function relevel(sections: Section[]): void {
  const seen = new Map<string, Section>();
  for (const section of sections) {
    const parent = section.parentId ? seen.get(section.parentId) : undefined;
    if (!parent) delete section.parentId;
    section.level = parent ? parent.level + 1 : 1;
    seen.set(section.id, section);
  }
}

/** Remove a section; its subsections move up to its parent. */
function removeSection(sections: Section[], index: number): void {
  const [removed] = sections.splice(index, 1);
  if (!removed) return;
  for (const section of sections) {
    if (section.parentId !== removed.id) continue;
    if (removed.parentId) section.parentId = removed.parentId;
    else delete section.parentId;
  }
}

function fromCore(split: KnowledgeSection[]): Section[] {
  const ids = new Map(split.map((section) => [section.key, newId()]));
  return split.map((section) => {
    const heading = section.number && section.title.startsWith(section.number) ? section.title.slice(section.number.length).trim() : section.title;
    const parentId = section.parent ? ids.get(section.parent) : undefined;
    return {
      id: ids.get(section.key)!,
      ...(section.number ? { number: section.number } : {}),
      heading: heading || section.title,
      level: section.level,
      ...(parentId ? { parentId } : {}),
      ...(section.pageStart !== undefined ? { pageStart: section.pageStart } : {}),
      ...(section.pageEnd !== undefined ? { pageEnd: section.pageEnd } : {}),
      body: section.body,
      slugBase: section.slug.replace(/^\d+_/, ""),
      status: "draft" as const,
      edited: false,
    };
  });
}

/** A text with no usable headings is one section; the user can cut it by hand. */
function wholeSection(title: string, text: string): Section {
  const label = title.split(/[.:]/)[0]!.trim() || "1";
  return { id: newId(), heading: title, level: 1, body: structureRecommendations(text, label).body, slugBase: "tekst", status: "draft", edited: false };
}

/** The working sections in the shape okf-core renders, with ordered file names. */
export function toCore(sections: Section[]): KnowledgeSection[] {
  const keys = new Map(sections.map((section) => [section.id, section.id]));
  return sections.map((section, index) => ({
    key: section.id,
    ...(section.number ? { number: section.number } : {}),
    title: sectionTitle(section),
    level: section.level,
    ...(section.parentId && keys.has(section.parentId) ? { parent: section.parentId } : {}),
    ...(section.pageStart !== undefined ? { pageStart: section.pageStart } : {}),
    ...(section.pageEnd !== undefined ? { pageEnd: section.pageEnd } : {}),
    body: section.body,
    recommendations: recommendationsOf(section.body),
    slug: `${String(index + 1).padStart(2, "0")}_${section.slugBase.replace(/[^A-Za-z0-9._-]+/g, "-") || "razdel"}`,
  }));
}
