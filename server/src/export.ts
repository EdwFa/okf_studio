/**
 * Exporting the store as an Open Knowledge Format 0.2 bundle: a zip of
 * Markdown files with typed YAML frontmatter, one folder per group, laid out
 * the way Luka's knowledge base expects a group (see okf-core/bundle.ts).
 */
import AdmZip from "adm-zip";
import path from "node:path";
import { okfInstant, renderDocument, renderGroupIndex, renderRootIndex, type OkfDocument, type OkfDocumentSummary } from "okf-core";
import { toCore, type DocumentMeta, type Domain, type Group, type Store } from "./store.ts";

export const KIND_LABELS: Record<string, string> = {
  guideline: "клинические рекомендации",
  standard: "стандарт",
  order: "приказ",
  article: "статья",
  manual: "руководство",
  other: "другое",
};

/** The producer name written into `generated.by` (OKF §7: `<producer>/<version>`). */
export const PRODUCER = "okf-studio/0.1.0";

/** Who checks documents: the domain's owner when one is named (OKF §7: `human:<id>`). */
function reviewer(store: Store, doc: DocumentMeta): string {
  const owner = store.findGroup(doc.groupId)?.domain.owner.trim();
  return `human:${owner || "editor"}`;
}

/**
 * The document as okf-core renders it, with the standard OKF 0.2 keys:
 * `resource` and `tags` (§4.1), `sources` and `generated` (§5.1, §5.2),
 * `verified` for a checked document (§5.2), `status` (§5.4) and
 * `stale_after` from the review date (§5.5).
 */
export function okfDocument(store: Store, group: Group, doc: DocumentMeta): OkfDocument {
  const checked = doc.status !== "draft";
  // The original file sits beside the group's documents in Luka's store; elsewhere the link is simply unresolved.
  const original = `/${group.id}/sources/${doc.id}${path.extname(doc.sourceName).toLowerCase()}`;
  return {
    id: doc.id,
    title: doc.title,
    description: doc.description,
    source: doc.sourceName,
    ...(doc.pages ? { pages: doc.pages } : {}),
    addedAt: doc.addedAt,
    extra: {
      resource: doc.url,
      tags: doc.tags,
      status: checked ? "stable" : "draft",
      ...(checked ? { verified: [{ by: reviewer(store, doc), at: okfInstant(doc.reviewedAt ?? doc.updatedAt) }] } : {}),
      stale_after: doc.reviewDue ? okfInstant(doc.reviewDue) : "",
      kind: KIND_LABELS[doc.kind] ?? doc.kind,
      origin: doc.origin,
      year: doc.year,
      version: doc.version,
      approved: doc.approvedAt,
      icd10: doc.icd10,
    },
    provenance: {
      sources: [{ id: "original", resource: doc.url || original, ...(doc.origin ? { author: doc.origin } : {}) }],
      generated: { by: PRODUCER, at: okfInstant(doc.updatedAt) },
    },
  };
}

/** One document's files, keyed by path relative to its group's folder. */
export function documentFiles(store: Store, group: Group, doc: DocumentMeta): Map<string, string> {
  const sections = store.rawSections(doc.id);
  const okf = okfDocument(store, group, doc);
  // One section means the text had no usable headings: it is stored as a single file.
  if (sections.length <= 1) return renderDocument(group, okf, [], sections[0]?.body ?? "");
  const byId = new Map(sections.map((section) => [section.id, section]));
  // A section carries its own check: it can be verified while the document is still a draft.
  return renderDocument(group, okf, toCore(sections), "", (section) => {
    const mine = byId.get(section.key);
    return mine?.status === "reviewed"
      ? { status: "stable", verified: [{ by: reviewer(store, doc), at: okfInstant(mine.reviewedAt ?? doc.updatedAt) }] }
      : { status: "draft" };
  });
}

/** A group's files, keyed by path relative to the group's folder. Only parsed documents are included. */
export function groupFiles(store: Store, group: Group): Map<string, string> {
  const files = new Map<string, string>();
  const summaries: OkfDocumentSummary[] = [];
  for (const doc of store.documentsOf(group.id)) {
    if (doc.job.state !== "ready") continue;
    for (const [name, content] of documentFiles(store, group, doc)) files.set(name, content);
    summaries.push({ ...okfDocument(store, group, doc), sections: doc.sections > 1 ? doc.sections : 0, recommendations: doc.recommendations });
  }
  files.set("index.md", renderGroupIndex(group, summaries));
  return files;
}

/** Zip of one group (`<groupId>/…`) or of a whole domain (`index.md` plus its groups). */
export function exportZip(store: Store, domain: Domain, onlyGroup?: Group): Buffer {
  const zip = new AdmZip();
  const counts = new Map<string, number>();
  for (const item of onlyGroup ? [onlyGroup] : domain.groups) {
    // A nested group is named by its full path, so the bundle reads without the tree.
    const group = { ...item, name: store.groupPath(item.id) };
    const files = groupFiles(store, group);
    counts.set(group.id, [...files.keys()].filter((name) => /^[^/]+\.md$/.test(name) && name !== "index.md").length);
    for (const [name, content] of files) zip.addFile(`${group.id}/${name}`, Buffer.from(content, "utf-8"));
  }
  if (!onlyGroup) {
    const groups = domain.groups.map((group) => ({ id: group.id, name: store.groupPath(group.id), note: `документов: ${counts.get(group.id) ?? 0}${group.description ? `. ${group.description}` : ""}` }));
    zip.addFile("index.md", Buffer.from(renderRootIndex(domain.name, domain.description, groups), "utf-8"));
  }
  return zip.toBuffer();
}
