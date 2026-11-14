/**
 * Publishing a group into Luka's knowledge base, where its agents read it.
 *
 * Luka keeps its base under `<agentDir>/knowledge/` (k-dense-pi/server/src/
 * knowledge.ts): `knowledge.json` lists groups and documents, each group has a
 * folder of OKF files, and every visible, non-empty group is projected into
 * `<agentDir>/skills/kb-<groupId>/` as a skill. This module writes one studio
 * group into that layout directly, so Luka need not be running:
 *
 *   - only documents marked "проверено" are published; they become "опубликовано";
 *   - a document edited after publishing goes back to a draft here, and Luka
 *     keeps the version published last until the group is published again;
 *   - documents are flagged `curated`, which tells Luka never to rebuild their
 *     files from the extracted text;
 *   - the group folder carries a marker file. A folder or skill without our
 *     marker is never overwritten or removed, and other groups in
 *     knowledge.json are passed through untouched.
 *
 * A new chat in Luka sees the change; an open chat keeps the skills it started with.
 */
import fs from "node:fs";
import path from "node:path";
import { appendLogEntry, frontmatter, groupIndexBody, renderGroupIndex, renderRootIndex, skillDescription, type OkfDocumentSummary } from "okf-core";
import { documentFiles } from "./export.ts";
import { StoreError, type DocumentMeta, type Store } from "./store.ts";

const GROUP_MARKER = ".okf-studio";
const SKILL_MARKER = ".kady-knowledge";
const SKILL_PREFIX = "kb-";
/** Luka's limit (MAX_DOCS_PER_GROUP). */
const MAX_DOCS_PER_GROUP = 100;

type Rec = Record<string, unknown>;
const isRecord = (value: unknown): value is Rec => Boolean(value) && typeof value === "object" && !Array.isArray(value);

interface LukaDoc extends Rec {
  id: string;
  title: string;
  description: string;
  source: string;
  chars: number;
  pages?: number;
  sections: number;
  recommendations: number;
  curated: true;
  addedAt: string;
}

export interface PublishResult {
  published: { id: string; title: string }[];
  /** Published earlier, changed since and not re-checked: Luka keeps the earlier version. */
  kept: { id: string; title: string }[];
  /** Never published and not marked as checked. */
  skipped: { id: string; title: string }[];
  /** Removed from Luka: deleted here or moved to another group. */
  removed: number;
  /** Whether agents can see the group now (it is not hidden and has documents). */
  visible: boolean;
}

function writeFile(file: string, content: string | Buffer): void {
  fs.mkdirSync(path.dirname(file), { recursive: true, mode: 0o700 });
  const tmp = `${file}.${process.pid}.tmp`;
  fs.writeFileSync(tmp, content, { mode: 0o600 });
  fs.renameSync(tmp, file);
}

function readState(root: string): { raw: Rec; groups: Rec[] } {
  const file = path.join(root, "knowledge.json");
  if (!fs.existsSync(file)) return { raw: { version: 1 }, groups: [] };
  let raw: unknown;
  try {
    raw = JSON.parse(fs.readFileSync(file, "utf-8"));
  } catch {
    throw new StoreError("Файл knowledge.json в базе знаний Луки повреждён. Публикация остановлена, чтобы его не затереть.", 409);
  }
  if (!isRecord(raw)) throw new StoreError("Файл knowledge.json в базе знаний Луки имеет неожиданный вид. Публикация остановлена.", 409);
  return { raw, groups: Array.isArray(raw.groups) ? raw.groups.filter(isRecord) : [] };
}

function saveState(root: string, raw: Rec, groups: Rec[], entry: string): void {
  writeFile(path.join(root, "knowledge.json"), `${JSON.stringify({ ...raw, groups }, null, 2)}\n`);
  // Reserved files as OKF 0.2 defines them: the same content Luka writes (knowledge.ts, writeIndexes and appendLog).
  const entries = groups.map((group) => {
    const docs = Array.isArray(group.docs) ? group.docs.length : 0;
    return { id: String(group.id), name: String(group.name), note: `${docs} documents${group.hidden === true ? " (hidden from agents)" : ""}` };
  });
  writeFile(path.join(root, "index.md"), renderRootIndex("База знаний", "", entries));
  const log = path.join(root, "log.md");
  writeFile(log, appendLogEntry(fs.existsSync(log) ? fs.readFileSync(log, "utf-8") : undefined, "База знаний: журнал изменений", entry));
}

const sourceCopy = (doc: { id: string; source: string }): string => `${doc.id}${path.extname(doc.source).toLowerCase()}`;

function removeDocFiles(dir: string, doc: { id: string; source: string }): void {
  fs.rmSync(path.join(dir, `${doc.id}.md`), { force: true });
  fs.rmSync(path.join(dir, doc.id), { recursive: true, force: true });
  fs.rmSync(path.join(dir, "sources", `${doc.id}.txt`), { force: true });
  fs.rmSync(path.join(dir, "sources", sourceCopy(doc)), { force: true });
}

/** Rebuild (or remove) the group's skill from its folder, the way Luka's syncKnowledgeSkills does. */
function projectSkill(agentDir: string, group: { id: string; name: string; hidden: boolean }, docs: OkfDocumentSummary[]): boolean {
  const dir = path.join(agentDir, "skills", `${SKILL_PREFIX}${group.id}`);
  const ours = fs.existsSync(path.join(dir, SKILL_MARKER));
  if (fs.existsSync(dir) && !ours) throw new StoreError(`В Луке уже есть навык ${SKILL_PREFIX}${group.id}, созданный не базой знаний. Публикация остановлена.`, 409);
  const visible = !group.hidden && docs.length > 0;
  fs.rmSync(dir, { recursive: true, force: true });
  if (!visible) return false;
  const from = path.join(agentDir, "knowledge", group.id);
  writeFile(path.join(dir, SKILL_MARKER), "Generated from the knowledge base (Settings → База знаний). Edits here are overwritten.\n");
  for (const doc of docs) {
    fs.copyFileSync(path.join(from, `${doc.id}.md`), path.join(dir, `${doc.id}.md`));
    if (fs.existsSync(path.join(from, doc.id))) fs.cpSync(path.join(from, doc.id), path.join(dir, doc.id), { recursive: true });
  }
  const name = `${SKILL_PREFIX}${group.id}`;
  writeFile(path.join(dir, "SKILL.md"), `${frontmatter({ name, description: skillDescription(group, docs), type: "index" })}\n${groupIndexBody(group, docs)}`);
  return true;
}

function summary(entry: LukaDoc): OkfDocumentSummary {
  return { id: entry.id, title: entry.title, description: entry.description, source: entry.source, addedAt: entry.addedAt, sections: entry.sections, recommendations: entry.recommendations };
}

/** Publish one group into Luka's knowledge base under `agentDir`. */
export function publishGroup(store: Store, groupId: string, agentDir: string): PublishResult {
  const place = store.findGroup(groupId);
  if (!place) throw new StoreError("Группа не найдена", 404);
  if (!fs.existsSync(agentDir)) throw new StoreError(`Не найдена папка Луки: ${agentDir}`, 409);
  // Luka's groups are a flat list: a nested group goes there under its full path.
  const group = { ...place.group, name: store.groupPath(groupId).slice(0, 120) };
  const root = path.join(agentDir, "knowledge");
  const dir = path.join(root, group.id);
  const { raw, groups } = readState(root);
  const at = groups.findIndex((candidate) => candidate.id === group.id);
  const marked = fs.existsSync(path.join(dir, GROUP_MARKER));
  if ((at >= 0 || fs.existsSync(dir)) && !marked) throw new StoreError("В базе знаний Луки уже есть группа с таким идентификатором, созданная не из OKF Studio. Публикация остановлена.", 409);
  if (groups.some((candidate, index) => index !== at && String(candidate.name).toLowerCase() === group.name.toLowerCase())) {
    throw new StoreError(`В базе знаний Луки уже есть другая группа «${group.name}». Переименуйте одну из них: имена групп в Луке не повторяются.`, 409);
  }
  const before = new Map<string, LukaDoc>();
  for (const doc of at >= 0 && Array.isArray(groups[at]!.docs) ? (groups[at]!.docs as unknown[]) : []) {
    if (isRecord(doc) && typeof doc.id === "string") before.set(doc.id, doc as LukaDoc);
  }

  const result: PublishResult = { published: [], kept: [], skipped: [], removed: 0, visible: false };
  const fresh: DocumentMeta[] = [];
  const entries: LukaDoc[] = [];
  for (const doc of store.documentsOf(group.id)) {
    const label = { id: doc.id, title: doc.title };
    if (doc.job.state === "ready" && doc.status !== "draft") {
      fresh.push(doc);
      result.published.push(label);
      entries.push({
        id: doc.id,
        title: doc.title,
        description: doc.description,
        source: doc.sourceName,
        chars: doc.chars,
        ...(doc.pages ? { pages: doc.pages } : {}),
        sections: doc.sections > 1 ? doc.sections : 0,
        recommendations: doc.recommendations,
        curated: true,
        addedAt: doc.addedAt,
      });
    } else if (before.has(doc.id)) {
      result.kept.push(label);
      entries.push(before.get(doc.id)!);
    } else result.skipped.push(label);
  }
  if (entries.length > MAX_DOCS_PER_GROUP) throw new StoreError(`В группе Луки помещается не больше ${MAX_DOCS_PER_GROUP} документов, а к публикации готово ${entries.length}. Разделите группу.`, 409);
  if (!entries.length && at < 0) throw new StoreError("Публиковать нечего: в группе нет документов со статусом «проверено».", 409);

  writeFile(path.join(dir, GROUP_MARKER), "Published from OKF Studio. Change documents there and publish again; edits here are overwritten.\n");
  const keep = new Set(entries.map((entry) => entry.id));
  for (const [id, old] of before) {
    if (keep.has(id)) continue;
    removeDocFiles(dir, old);
    result.removed += 1;
  }
  for (const doc of fresh) {
    removeDocFiles(dir, { id: doc.id, source: before.get(doc.id)?.source ?? doc.sourceName });
    for (const [name, content] of documentFiles(store, group, { ...doc, status: "published" })) writeFile(path.join(dir, name), content);
    writeFile(path.join(dir, "sources", `${doc.id}.txt`), store.text(doc.id));
    const source = store.sourcePath(doc);
    if (fs.existsSync(source)) {
      const copy = path.join(dir, "sources", sourceCopy({ id: doc.id, source: doc.sourceName }));
      fs.copyFileSync(source, copy);
      fs.chmodSync(copy, 0o600);
    }
  }
  const summaries = entries.map(summary);
  writeFile(path.join(dir, "index.md"), renderGroupIndex(group, summaries));

  const entry: Rec = { id: group.id, name: group.name, hidden: group.hidden, docs: entries };
  if (at >= 0) groups[at] = entry;
  else groups.push(entry);
  saveState(root, raw, groups, `group published from OKF Studio: ${group.name} (${result.published.length} published, ${result.kept.length} kept, ${result.removed} removed)`);
  result.visible = projectSkill(agentDir, group, summaries);
  store.markPublished(group.id, fresh.map((doc) => doc.id));
  return result;
}

/** Remove a group published earlier from Luka's knowledge base. Documents here are untouched and go back to "проверено". */
export function unpublishGroup(store: Store, groupId: string, agentDir: string): void {
  const place = store.findGroup(groupId);
  if (!place) throw new StoreError("Группа не найдена", 404);
  const root = path.join(agentDir, "knowledge");
  const dir = path.join(root, groupId);
  if (!fs.existsSync(path.join(dir, GROUP_MARKER))) throw new StoreError("Эта группа не опубликована в Луке.", 409);
  const { raw, groups } = readState(root);
  projectSkill(agentDir, { ...place.group, hidden: true }, []);
  fs.rmSync(dir, { recursive: true, force: true });
  saveState(root, raw, groups.filter((candidate) => candidate.id !== groupId), `group unpublished from OKF Studio: ${place.group.name}`);
  store.markUnpublished(groupId);
}

/** What Luka currently holds of a group: whether it is published there and which documents. */
export function publication(groupId: string, agentDir: string): { published: boolean; documents: string[] } {
  const root = path.join(agentDir, "knowledge");
  if (!fs.existsSync(path.join(root, groupId, GROUP_MARKER))) return { published: false, documents: [] };
  try {
    const group = readState(root).groups.find((candidate) => candidate.id === groupId);
    const docs = group && Array.isArray(group.docs) ? group.docs : [];
    return { published: Boolean(group), documents: docs.filter(isRecord).map((doc) => String(doc.id)) };
  } catch {
    return { published: false, documents: [] };
  }
}
