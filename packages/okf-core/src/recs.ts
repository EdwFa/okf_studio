/**
 * The recommendation markup inside a section body, as an editable structure.
 *
 * `structureRecommendations` (sections.ts) writes each graded recommendation
 * into the section text as
 *
 *   ### Рекомендация <label>/<n> · УУР <A–C или 0> · УДД <1–5 или 0>
 *
 *   <statement, one paragraph>
 *
 *   **Комментарий.** <comment>
 *
 * The body is the single source of truth: the recommendation list is always
 * read back from it, so hand edits to the text and edits made through a
 * recommendations table cannot drift apart.
 */
import type { Recommendation } from "./sections.ts";

export interface TextBlock {
  kind: "text";
  text: string;
}

export interface RecBlock {
  kind: "rec";
  text: string;
  grade?: string;
  evidence?: string;
  comment?: string;
}

export type BodyBlock = TextBlock | RecBlock;

const HEAD = /^### Рекомендация [^\n]*?\/\d+ · УУР (\S+) · УДД (\S+)[ \t]*$/gmu;
const COMMENT = "**Комментарий.**";

/** The label recommendations of a section are numbered under: its number, or the start of its title. */
export function sectionLabel(section: { number?: string; title: string }): string {
  return section.number ?? section.title.split(/[.:]/)[0]!.trim();
}

/** Split a section body into plain text and recommendation blocks, in order. */
export function parseBody(body: string): BodyBlock[] {
  const heads = [...body.matchAll(HEAD)];
  const blocks: BodyBlock[] = [];
  const pushText = (value: string) => {
    const text = value.trim();
    if (text) blocks.push({ kind: "text", text });
  };
  if (!heads.length) {
    pushText(body);
    return blocks;
  }
  pushText(body.slice(0, heads[0]!.index));
  heads.forEach((head, index) => {
    const content = body.slice(head.index + head[0].length, heads[index + 1]?.index ?? body.length).trim();
    const gap = /\n[ \t]*\n/.exec(content);
    const text = (gap ? content.slice(0, gap.index) : content).trim();
    const rest = gap ? content.slice(gap.index).trim() : "";
    const grade = /^(?:[A-C]|0)$/.test(head[1]!) ? head[1]! : undefined;
    const evidence = /^(?:[1-5]|0)$/.test(head[2]!) ? head[2]! : undefined;
    const block: RecBlock = { kind: "rec", text, ...(grade ? { grade } : {}), ...(evidence ? { evidence } : {}) };
    if (rest.startsWith(COMMENT)) {
      const comment = rest.slice(COMMENT.length).trim();
      if (comment) block.comment = comment;
      blocks.push(block);
    } else {
      blocks.push(block);
      pushText(rest);
    }
  });
  return blocks;
}

/** Write blocks back as a section body, numbering the recommendations 1…n under `label`. */
export function serializeBody(blocks: BodyBlock[], label: string): string {
  let n = 0;
  return blocks
    .map((block) => {
      if (block.kind === "text") return block.text.trim();
      n += 1;
      const head = `### Рекомендация ${label}/${n} · УУР ${block.grade ?? "—"} · УДД ${block.evidence ?? "—"}`;
      const comment = block.comment?.trim() ? `\n\n${COMMENT} ${block.comment.trim()}` : "";
      return `${head}\n\n${block.text.trim()}${comment}`;
    })
    .filter(Boolean)
    .join("\n\n");
}

/** A body with its recommendations renumbered under `label`; text is untouched. */
export function normalizeBody(body: string, label: string): string {
  const blocks = parseBody(body);
  return blocks.some((block) => block.kind === "rec") ? serializeBody(blocks, label) : body.trim();
}

const oneLine = (value: string): string => value.replace(/<!-- page \d+ -->/g, " ").replace(/\s+/g, " ").trim();

/** The recommendations marked up in a body, numbered in order. */
export function recommendationsOf(body: string): Recommendation[] {
  return parseBody(body)
    .filter((block): block is RecBlock => block.kind === "rec")
    .map((block, index) => ({
      n: index + 1,
      text: oneLine(block.text),
      ...(block.grade ? { grade: block.grade } : {}),
      ...(block.evidence ? { evidence: block.evidence } : {}),
      ...(block.comment ? { comment: oneLine(block.comment) } : {}),
    }));
}
