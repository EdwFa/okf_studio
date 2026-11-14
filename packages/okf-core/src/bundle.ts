/**
 * Rendering documents as Open Knowledge Format files: Markdown with YAML
 * frontmatter that carries a `type`.
 *
 * The layout is the one Luka's knowledge base reads and publishes to agents
 * (k-dense-pi/server/src/knowledge.ts), so a group rendered here can be placed
 * into Luka's store as is:
 *
 *   <group>/index.md                 the group's document list
 *   <group>/<doc>.md                 the document: its section index, or the whole text
 *   <group>/<doc>/NN_<slug>.md       one section or subsection
 *   <group>/<doc>/recommendations.md every graded recommendation
 *
 * The files follow the OKF specification, version 0.2
 * (github.com/GoogleCloudPlatform/open-knowledge-format, SPEC.md):
 *   - every concept file has frontmatter with a `type` (§4.1);
 *   - `index.md` has no frontmatter, except `okf_version` at the bundle root,
 *     and lists entries as links with a short description (§8);
 *   - `log.md` has no frontmatter and groups entries under ISO dates, newest first (§9);
 *   - provenance, trust and lifecycle use the standard keys: `sources`,
 *     `generated`, `verified`, `status`, `stale_after`, `resource`, `tags` (§5).
 *
 * Nothing here touches the disk: each function returns file contents.
 */
import { stringify as yamlStringify } from "yaml";
import { sectionLabel } from "./recs.ts";
import type { KnowledgeSection } from "./sections.ts";

export interface OkfGroup {
  id: string;
  name: string;
  description?: string;
}

export interface OkfDocument {
  id: string;
  title: string;
  /** One line telling an agent when this document is the one to read. */
  description: string;
  /** Original file name. */
  source: string;
  pages?: number;
  /** ISO date or timestamp. */
  addedAt: string;
  /** Further frontmatter fields of the document file (resource, tags, verified, status, year, icd10…); empty values are dropped. */
  extra?: Record<string, unknown>;
  /** Where the text comes from and what produced the files (`sources`, `generated`): written into every file of the document. */
  provenance?: Record<string, unknown>;
}

export interface OkfDocumentSummary extends OkfDocument {
  sections: number;
  recommendations: number;
}

type Fields = Record<string, unknown>;

export function frontmatter(fields: Fields): string {
  return `---\n${yamlStringify(fields, { lineWidth: 0 }).trimEnd()}\n---\n`;
}

const cell = (value: string): string => value.replace(/\|/g, "/").replace(/\s+/g, " ").trim();
const today = (): string => new Date().toISOString().slice(0, 10);

export const documentFile = (doc: { id: string }): string => `${doc.id}.md`;
export const sectionFile = (section: { slug: string }): string => `${section.slug}.md`;

const pageSpan = (section: KnowledgeSection): string =>
  section.pageStart === undefined
    ? ""
    : section.pageStart === section.pageEnd || section.pageEnd === undefined
      ? `${section.pageStart}`
      : `${section.pageStart}–${section.pageEnd}`;

/** The OKF specification version these files follow. */
export const OKF_VERSION = "0.2";

function present(fields: Fields | undefined): Fields {
  const out: Fields = {};
  for (const [key, value] of Object.entries(fields ?? {})) {
    if (value === undefined || value === null || value === "" || (Array.isArray(value) && !value.length)) continue;
    out[key] = value;
  }
  return out;
}

function documentFrontmatter(group: OkfGroup, doc: OkfDocument): Fields {
  return {
    type: "document",
    title: doc.title,
    ...(doc.description ? { description: doc.description } : {}),
    group: group.name,
    source: doc.source,
    ...(doc.pages ? { pages: doc.pages } : {}),
    added: doc.addedAt.slice(0, 10),
    ...present(doc.extra),
    ...present(doc.provenance),
  };
}

function sectionMarkdown(group: OkfGroup, doc: OkfDocument, section: KnowledgeSection, all: KnowledgeSection[], fields: Fields): string {
  const byKey = new Map(all.map((item) => [item.key, item]));
  const trail: string[] = [];
  for (let up = section.parent; up; up = byKey.get(up)?.parent) {
    const parent = byKey.get(up);
    if (!parent) break;
    trail.unshift(`[${parent.title}](${sectionFile(parent)})`);
  }
  const children = all.filter((item) => item.parent === section.key);
  const pages = pageSpan(section);
  const lines = [
    `# ${section.title}`,
    "",
    [`Документ: [${doc.title}](../${documentFile(doc)})`, ...(trail.length ? [`Раздел: ${trail.join(" › ")}`] : []), ...(pages ? [`PDF-страницы: ${pages}`] : [])].join(" · "),
    "",
  ];
  if (children.length) lines.push("Подразделы:", ...children.map((child) => `- [${child.title}](${sectionFile(child)})`), "");
  lines.push(section.body || "_В этом разделе нет собственного текста: содержание находится в подразделах._", "");
  return `${frontmatter({
    type: "section",
    title: section.title,
    description: `Раздел документа «${doc.title}»${pages ? `, PDF-страницы ${pages}` : ""}.`,
    ...(section.number ? { number: section.number } : {}),
    document: doc.title,
    group: group.name,
    ...(section.parent ? { parent: byKey.get(section.parent)?.title ?? section.parent } : {}),
    ...(pages ? { pages } : {}),
    ...(section.recommendations.length ? { recommendations: section.recommendations.length } : {}),
    source: doc.source,
    ...present(fields),
    ...present(doc.provenance),
  })}\n${lines.join("\n")}`;
}

function recommendationsMarkdown(group: OkfGroup, doc: OkfDocument, sections: KnowledgeSection[]): string {
  const rows: string[] = [];
  for (const section of sections) {
    const label = sectionLabel(section);
    for (const rec of section.recommendations) {
      rows.push(`| ${label}/${rec.n} | [${cell(section.title)}](${sectionFile(section)}) | ${rec.grade ?? "—"} | ${rec.evidence ?? "—"} | ${cell(rec.text)} |`);
    }
  }
  return `${frontmatter({
    type: "summary",
    title: `${doc.title}: рекомендации`,
    description: `Все рекомендации документа «${doc.title}» с уровнями убедительности и доказательности.`,
    document: doc.title,
    group: group.name,
    recommendations: rows.length,
    source: doc.source,
    ...present(doc.provenance),
  })}
# ${doc.title}: рекомендации

Все рекомендации документа с уровнем убедительности (УУР, A–C) и уровнем достоверности доказательств (УДД, 1–5).
Текст рекомендаций дословный. Комментарии к рекомендации и окружающий текст находятся в файле раздела.

| № | Раздел | УУР | УДД | Рекомендация |
| --- | --- | --- | --- | --- |
${rows.join("\n")}
`;
}

function documentIndexMarkdown(group: OkfGroup, doc: OkfDocument, sections: KnowledgeSection[]): string {
  const total = sections.reduce((sum, section) => sum + section.recommendations.length, 0);
  const rows = sections.map((section) => {
    const indent = "&nbsp;&nbsp;".repeat(Math.max(section.level - 1, 0));
    return `| ${indent}[${cell(section.title)}](${doc.id}/${sectionFile(section)}) | ${pageSpan(section) || "—"} | ${section.recommendations.length || "—"} | ${section.body.length} |`;
  });
  return `${frontmatter({ ...documentFrontmatter(group, doc), sections: sections.length, ...(total ? { recommendations: total } : {}) })}
# ${doc.title}

${doc.description ? `${doc.description}\n\n` : ""}Документ разбит на разделы и подразделы по собственным заголовкам; каждый лежит в отдельном файле в папке \`${doc.id}/\`.
Текст разделов дословный. Читайте только нужные разделы.${total ? `\n\nВсе рекомендации с уровнями убедительности и доказательности собраны в [${doc.id}/recommendations.md](${doc.id}/recommendations.md) — ${total} шт.` : ""}

| Раздел | PDF-страницы | Рекомендаций | Знаков |
| --- | --- | --- | --- |
${rows.join("\n")}
`;
}

/**
 * A document's files, keyed by path relative to its group's directory. With
 * sections: the index, one file per section and the recommendations table.
 * Without: one file holding `text`.
 */
export function renderDocument(
  group: OkfGroup,
  doc: OkfDocument,
  sections: KnowledgeSection[],
  text: string,
  /** Further frontmatter of one section's file (its own `verified`, `status`). */
  sectionFields: (section: KnowledgeSection) => Fields = () => ({}),
): Map<string, string> {
  const files = new Map<string, string>();
  if (!sections.length) {
    files.set(documentFile(doc), `${frontmatter(documentFrontmatter(group, doc))}\n# ${doc.title}\n\n${text.trim()}\n`);
    return files;
  }
  for (const section of sections) files.set(`${doc.id}/${sectionFile(section)}`, sectionMarkdown(group, doc, section, sections, sectionFields(section)));
  if (sections.some((section) => section.recommendations.length)) {
    files.set(`${doc.id}/recommendations.md`, recommendationsMarkdown(group, doc, sections));
  }
  files.set(documentFile(doc), documentIndexMarkdown(group, doc, sections));
  return files;
}

/** The body of a group's index: how to use it, and its documents. Also the body of the group's skill. */
export function groupIndexBody(group: OkfGroup, docs: OkfDocumentSummary[]): string {
  const rows = docs.map(
    (doc) => `| ${cell(doc.title)} | [${documentFile(doc)}](${documentFile(doc)}) | ${cell(doc.description) || "—"} | ${doc.sections || "—"} | ${doc.recommendations || "—"} |`,
  );
  return [
    `# База знаний: ${group.name}`,
    "",
    "Documents the user selected as trusted reference material for this topic. They take precedence over general",
    "knowledge and over web search results; when they do not cover the question, say so before looking elsewhere.",
    "",
    "How to use:",
    "1. Pick the documents whose title and description match the task.",
    "2. Open the document's file. For a document split into sections it is an index: a table of its sections and subsections, each in its own file under the folder named after the document. Read only the sections the task needs. To find where a term is discussed, grep this directory.",
    "3. A split document also has `recommendations.md` in its folder: every graded recommendation with its strength (УУР) and level of evidence (УДД), pointing to its section.",
    "4. Cite the document title with the section number, the recommendation number (for example 3.1/4) and the page when shown. Quote thresholds, criteria and doses exactly.",
    "5. Section text is the document's own text, extracted automatically; tables and formulas may be garbled. Say so when a value looks damaged instead of guessing.",
    "",
    "| Document | File | When to read | Sections | Recommendations |",
    "| --- | --- | --- | --- | --- |",
    ...rows,
    "",
  ].join("\n");
}

/** The description of a group's skill: what an agent sees when deciding whether to open the group. */
export function skillDescription(group: OkfGroup, docs: { title: string }[]): string {
  const titles = docs.map((doc) => doc.title).join("; ");
  const base = `База знаний «${group.name}»: ${docs.length} documents selected by the user as trusted references. Read before answering or planning work on this topic, and prefer it over web search. Documents: `;
  const room = 1000 - base.length;
  return base + (titles.length > room ? `${titles.slice(0, Math.max(room - 1, 0))}…` : titles);
}

/**
 * A group's `index.md` (§8): no frontmatter; entries are links with the
 * document's description. How to use the group is told in its skill, not here.
 */
export function renderGroupIndex(group: OkfGroup, docs: OkfDocumentSummary[]): string {
  const entries = docs.map((doc) => {
    const counts = [doc.sections ? `разделов: ${doc.sections}` : "", doc.recommendations ? `рекомендаций: ${doc.recommendations}` : ""].filter(Boolean).join(", ");
    return `- [${cell(doc.title)}](${documentFile(doc)}) — ${cell(doc.description) || "без описания"}${counts ? ` (${counts})` : ""}`;
  });
  return [`# ${group.name}`, "", ...(group.description ? [group.description, ""] : []), "## Документы", "", ...(entries.length ? entries : ["_Документов пока нет._"]), ""].join("\n");
}

/** The bundle root's `index.md` (§8, §12): the only index that carries frontmatter, and only `okf_version`. */
export function renderRootIndex(title: string, description: string, groups: { id: string; name: string; note: string }[]): string {
  const entries = groups.map((group) => `- [${cell(group.name)}](${group.id}/index.md) — ${cell(group.note)}`);
  return [`---\nokf_version: "${OKF_VERSION}"\n---`, "", `# ${title}`, "", ...(description ? [description, ""] : []), "## Группы", "", ...(entries.length ? entries : ["_Групп пока нет._"]), ""].join("\n");
}

/** An ISO 8601 instant with an explicit UTC offset, as OKF timestamps require (§5). */
export function okfInstant(value: string | Date): string {
  const date = typeof value === "string" ? new Date(/^\d{4}-\d{2}-\d{2}$/.test(value) ? `${value}T00:00:00Z` : value) : value;
  return Number.isNaN(date.getTime()) ? "" : date.toISOString().replace(/\.\d{3}Z$/, "+00:00");
}

const LEGACY_ENTRY = /^- (\d{4}-\d{2}-\d{2})T(\d{2}:\d{2})[^ ]* (.*)$/;
const DATE_HEADING = /^## (\d{4}-\d{2}-\d{2})$/;

/**
 * `log.md` with one more entry (§9): no frontmatter, entries grouped under
 * `## YYYY-MM-DD` headings, newest date first and newest entry first within a
 * date. A log in the older layout (frontmatter and a flat list of
 * `- <timestamp> text` lines) is converted on the way.
 */
export function appendLogEntry(existing: string | undefined, title: string, entry: string, at: Date = new Date()): string {
  const days = new Map<string, string[]>();
  let day = "";
  for (const row of (existing ?? "").split("\n")) {
    const heading = DATE_HEADING.exec(row);
    const legacy = LEGACY_ENTRY.exec(row);
    if (heading) day = heading[1]!;
    else if (legacy) days.set(legacy[1]!, [`- ${legacy[2]} UTC — ${legacy[3]}`, ...(days.get(legacy[1]!) ?? [])]);
    else if (day && row.startsWith("- ")) days.set(day, [...(days.get(day) ?? []), row]);
  }
  const iso = at.toISOString();
  const today = iso.slice(0, 10);
  days.set(today, [`- ${iso.slice(11, 16)} UTC — ${entry.replace(/\s+/g, " ").trim()}`, ...(days.get(today) ?? [])]);
  const blocks = [...days.keys()].sort().reverse().map((date) => `## ${date}\n\n${days.get(date)!.join("\n")}`);
  return `# ${title}\n\n${blocks.join("\n\n")}\n`;
}
