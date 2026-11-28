/**
 * Puts one Minzdrav PDF into the group the snapshot assigned it to.
 * A recommendation already tagged `cr:<id>` is returned as it is.
 */
import { copyFileSync, existsSync, mkdirSync } from "node:fs";
import path from "node:path";
import { pdfDir } from "../config.ts";
import { Store, StoreError, type DocumentMeta } from "../store.ts";
import { assignCr, catalogSnapshot } from "./assign.ts";

const CR_ID = /^\d+_\d+$/;

export interface AssignmentRow {
  catalogKey: string;
  name: string;
  groupId?: string;
  documentId?: string;
}

export interface PlaceResult {
  documentId: string;
  groupId: string;
  catalogKey: string;
  created: boolean;
  status: DocumentMeta["status"];
}

function studioGroup(store: Store, catalogKey: string): string | undefined {
  for (const domain of store.catalogView().domains) {
    const group = domain.groups.find((item) => item.catalogKey === catalogKey);
    if (group) return group.id;
  }
  return undefined;
}

function placed(store: Store, crId: string): DocumentMeta | undefined {
  const tag = `cr:${crId}`;
  return store.allDocuments().find((doc) => doc.tags.includes(tag));
}

/** Every recommendation in the snapshot, plus the studio group and document when they exist. */
export function catalogAssignment(store: Store): Record<string, AssignmentRow> {
  const groups = new Map<string, string>();
  for (const domain of store.catalogView().domains) {
    for (const group of domain.groups) if (group.catalogKey) groups.set(group.catalogKey, group.id);
  }
  const docs = new Map<string, string>();
  for (const doc of store.allDocuments()) {
    const tag = doc.tags.find((item) => item.startsWith("cr:"));
    if (tag) docs.set(tag.slice(3), doc.id);
  }
  const out: Record<string, AssignmentRow> = {};
  for (const group of catalogSnapshot().groups) {
    const groupId = groups.get(group.catalogKey);
    for (const doc of group.documents) {
      const documentId = docs.get(doc.id);
      out[doc.id] = {
        catalogKey: group.catalogKey,
        name: group.name,
        ...(groupId ? { groupId } : {}),
        ...(documentId ? { documentId } : {}),
      };
    }
  }
  return out;
}

/** Copy the local PDF into the assigned group. Missing file: 422, and nothing is created. */
export function placeCr(store: Store, crId: unknown): PlaceResult {
  if (typeof crId !== "string" || !CR_ID.test(crId)) throw new StoreError("Нужен id рекомендации Минздрава");
  const assignment = assignCr(crId);
  if (!assignment) throw new StoreError("Рекомендации нет в снимке классификатора", 404);
  const existing = placed(store, crId);
  if (existing) {
    return { documentId: existing.id, groupId: existing.groupId, catalogKey: assignment.groupKey, created: false, status: existing.status };
  }
  const groupId = studioGroup(store, assignment.groupKey);
  if (!groupId) throw new StoreError("Группа каталога ещё не создана. Заполните студию из классификатора.", 404);
  const source = path.join(pdfDir(), `${crId}.pdf`);
  if (!existsSync(source)) throw new StoreError("Файла нет на диске", 422);
  const tmpDir = path.join(store.root, "tmp");
  mkdirSync(tmpDir, { recursive: true, mode: 0o700 });
  const tmp = path.join(tmpDir, `${crId}-${Date.now()}.pdf`);
  copyFileSync(source, tmp);
  const doc = store.addDocument(groupId, tmp, `${crId}.pdf`);
  const year = assignment.year && /^\d{4}$/.test(assignment.year) ? Number(assignment.year) : undefined;
  store.updateDocument(doc.id, {
    title: assignment.title,
    description: assignment.description,
    kind: "guideline",
    icd10: assignment.codes,
    tags: [`cr:${crId}`],
    origin: `minzdrav:${crId}`,
    ...(year ? { year } : {}),
  });
  return { documentId: doc.id, groupId, catalogKey: assignment.groupKey, created: true, status: "draft" };
}
