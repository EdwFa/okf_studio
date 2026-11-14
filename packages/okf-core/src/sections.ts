/**
 * Split a knowledge-base document into its sections and subsections.
 *
 * The text is kept verbatim: nothing is summarized or reworded. Structure
 * comes from the document itself — its numbered headings ("2.4.1 …"), the
 * named parts every clinical guideline has (abbreviations, terms, quality
 * criteria, references, appendices), and Markdown headings from DOCX. A table
 * of contents, when present, is the authority on which numbered lines are
 * headings: body text is full of numbered lists and reference lists that look
 * the same.
 *
 * Inside a section, recommendation statements followed by a graded-evidence
 * line ("Уровень убедительности рекомендаций – C (уровень достоверности
 * доказательств – 5)") are marked up as numbered recommendations with their
 * grade, evidence level and comment, so an agent can cite one precisely.
 */

export interface Recommendation {
  /** 1-based position within its section. */
  n: number;
  text: string;
  /** УУР: strength of the recommendation, A–C. */
  grade?: string;
  /** УДД: level of evidence, 1–5. */
  evidence?: string;
  comment?: string;
}

export interface KnowledgeSection {
  /** Stable id within the document: the number ("2.4.1") or a named key. */
  key: string;
  /** Heading number as printed, when the heading is numbered. */
  number?: string;
  title: string;
  /** 1 for top-level parts, 2 for "1.1", and so on. */
  level: number;
  /** Key of the enclosing section. */
  parent?: string;
  /** PDF pages the section spans (1-based), when the text carries page marks. */
  pageStart?: number;
  pageEnd?: number;
  /** Section text, with recommendations marked up. */
  body: string;
  recommendations: Recommendation[];
  /** File name stem, unique within the document and stable in order. */
  slug: string;
}

const PAGE_MARK = /^<!-- page (\d+) -->$/;
const NUMBERED = /^(\d{1,2}(?:\.\d{1,2}){0,3})\.?\s*([A-ZА-ЯЁ].{2,})$/u;
const NAMED: { re: RegExp; key: string; slug: string }[] = [
  { re: /^Список\s+сокращений/iu, key: "список сокращений", slug: "sokrashcheniya" },
  { re: /^Термины\s+и\s+определения/iu, key: "термины и определения", slug: "terminy" },
  { re: /^Критерии\s+оценки\s+качества/iu, key: "критерии оценки качества", slug: "kriterii-kachestva" },
  { re: /^Список\s+литературы/iu, key: "список литературы", slug: "literatura" },
];
const APPENDIX = /^Приложение\s+([А-ЯA-Z]\d{0,2})(?![А-Яа-яA-Za-z])/u;
const TOC_MARK = /^(Оглавление|Содержание)\s*:?\s*\d*$/iu;
const MD_HEADING = /^(#{2,6})\s+(\S.*)$/;
const CYRILLIC_TO_LATIN: Record<string, string> = { А: "A", Б: "B", В: "V", Г: "G", Д: "D", Е: "E" };
const MIN_SECTIONS = 3;

interface Candidate {
  line: number;
  page: number | undefined;
  key: string;
  number?: string;
  /** Heading text without its number, TOC page reference removed. */
  title: string;
  slug: string;
  /** Markdown heading depth, for DOCX text. */
  mdLevel?: number;
}

const normalize = (value: string): string => value.toLowerCase().replace(/[^a-zа-яё0-9]+/giu, "");

/** Drop a table-of-contents page reference: "… · стр. 7", "… 12". */
function stripTocPage(title: string): string {
  return title
    .replace(/\s*·\s*стр\.?\s*\d*\s*$/iu, "")
    .replace(/\s{2,}\d{1,3}\s*$/u, "")
    .replace(/\s+\d{1,3}\s*$/u, "")
    .trim();
}

function candidateOf(raw: string, line: number, page: number | undefined): Candidate | null {
  const text = raw.trim();
  if (!text || text.length > 220) return null;
  const md = MD_HEADING.exec(text);
  if (md) {
    const inner = md[2]!.trim();
    const numbered = NUMBERED.exec(inner);
    if (numbered) return { line, page, key: numbered[1]!, number: numbered[1]!, title: numbered[2]!.trim(), slug: numbered[1]!, mdLevel: md[1]!.length - 1 };
    return { line, page, key: `md:${line}`, title: inner, slug: "razdel", mdLevel: md[1]!.length - 1 };
  }
  for (const named of NAMED) {
    if (named.re.test(text)) return { line, page, key: named.key, title: stripTocPage(text), slug: named.slug };
  }
  const appendix = APPENDIX.exec(text);
  if (appendix) {
    const code = appendix[1]!;
    const latin = (CYRILLIC_TO_LATIN[code[0]!] ?? code[0]!) + code.slice(1);
    return { line, page, key: `приложение ${code.toLowerCase()}`, title: stripTocPage(text), slug: `prilozhenie-${latin}` };
  }
  const numbered = NUMBERED.exec(text);
  if (numbered) {
    const title = numbered[2]!.trim();
    if (/;$/.test(title)) return null;
    return { line, page, key: numbered[1]!, number: numbered[1]!, title, slug: numbered[1]! };
  }
  return null;
}

const tupleOf = (number: string): number[] => number.split(".").map(Number);
const parentOf = (number: string): string => number.split(".").slice(0, -1).join(".");

/** Whether `next` can follow `last` in a well-formed outline: a first child or the next sibling of it or an ancestor. */
function follows(last: number[], next: number[]): boolean {
  if (next.length === last.length + 1) return next[next.length - 1] === 1 && last.every((part, i) => part === next[i]);
  if (next.length > last.length) return false;
  const depth = next.length - 1;
  return next.slice(0, depth).every((part, i) => part === last[i]) && next[depth] === (last[depth] ?? 0) + 1;
}

/** A heading that wraps over several lines: keep reading while the title is visibly unfinished. */
function fullTitle(lines: string[], start: number, first: string): { title: string; lines: number } {
  let title = first;
  let used = 1;
  const open = (value: string) => (value.match(/\(/g)?.length ?? 0) > (value.match(/\)/g)?.length ?? 0);
  while (used < 5) {
    const next = lines[start + used]?.trim();
    if (!next || PAGE_MARK.test(next) || candidateOf(next, 0, undefined)) break;
    const unfinished = open(title) || /[,–-]$/.test(title) || (/^[a-zа-яё(]/u.test(next) && !/[.:]$/.test(title));
    if (!unfinished) break;
    title = `${title} ${next}`;
    used += 1;
  }
  return { title: title.replace(/\s+/g, " ").trim(), lines: used };
}

const EVIDENCE =
  /Уровень\s+(убедительности\s+рекоменда-?\s*ций|достоверности\s+доказательств)\s*[-–—:]?\s*([A-CА-ВС1-5])\s*\(\s*уровень\s+(убедительности\s+рекоменда-?\s*ций|достоверности\s+доказательств)\s*[-–—:]?\s*([A-CА-ВС1-5])\s*\)?\.?/giu;
const REC_START = /(?:^|\n)[^\p{L}\p{N}\n]{0,4}(?:\n[ \t]*)?((?:Не\s+)?(?:Рекомендуется|Рекомендовано|Рекомендована|Рекомендован)(?![а-яё]))/gu;
/** A recommendation worded mid-sentence: "При … рекомендуется проведение …", "… показано …". */
const REC_VERB = /(?:рекомендуется|рекомендовано|рекомендована|рекомендован|показано|показана|показан|целесообразно|следует)(?![а-яё])/giu;
/** Where a sentence can begin: the start of a line that follows a finished one. */
const SENTENCE_BREAK = /(?:[.!?\]\)»:]|-->)[ \t]*\n/gu;
const GRADE: Record<string, string> = { А: "A", В: "B", С: "C" };
const BULLET_ONLY = /(?:\n[^\p{L}\p{N}\n]{1,4})+\s*$/u;

const oneLine = (value: string): string => value.replace(/<!-- page \d+ -->/g, " ").replace(/\s+/g, " ").trim();

/**
 * Mark up the graded recommendations in a section. Text between them is left
 * where it was; a statement that cannot be delimited with confidence is left
 * untouched too.
 */
export function structureRecommendations(body: string, label: string): { body: string; recommendations: Recommendation[] } {
  const found: { start: number; evidenceStart: number; evidenceEnd: number; grade: string; evidence: string }[] = [];
  let floor = 0;
  for (const match of body.matchAll(EVIDENCE)) {
    const evidenceStart = match.index;
    const evidenceEnd = evidenceStart + match[0].length;
    const window = body.slice(floor, evidenceStart);
    let start = -1;
    for (const rec of window.matchAll(REC_START)) start = floor + rec.index + rec[0].lastIndexOf(rec[1]!);
    if (start < 0) {
      // No statement opens with the verb: take the sentence that contains its last use.
      let verb = -1;
      for (const hit of window.matchAll(REC_VERB)) verb = hit.index;
      if (verb >= 0) {
        let from = 0;
        for (const stop of window.slice(0, verb).matchAll(SENTENCE_BREAK)) from = stop.index + stop[0].length;
        start = floor + from;
      }
    }
    const gradeFirst = /убедительности/iu.test(match[1]!);
    const gradeRaw = (gradeFirst ? match[2]! : match[4]!).toUpperCase();
    const evidenceRaw = gradeFirst ? match[4]! : match[2]!;
    floor = evidenceEnd;
    if (start < 0 || !/[A-CА-ВС]/u.test(gradeRaw) || !/[1-5]/.test(evidenceRaw)) continue;
    found.push({ start, evidenceStart, evidenceEnd, grade: GRADE[gradeRaw] ?? gradeRaw, evidence: evidenceRaw });
  }
  if (!found.length) return { body, recommendations: [] };

  const recommendations: Recommendation[] = [];
  const out: string[] = [];
  let cursor = 0;
  found.forEach((item, index) => {
    const before = body.slice(cursor, item.start).replace(BULLET_ONLY, "\n");
    if (before.trim()) out.push(before.trimEnd());
    const text = oneLine(body.slice(item.start, item.evidenceStart));
    const next = found[index + 1]?.start ?? body.length;
    const after = body.slice(item.evidenceEnd, next).replace(BULLET_ONLY, "\n");
    const commentMatch = /^(?:\s|<!-- page \d+ -->)*Комментари[йи]\s*:?\s*/iu.exec(after);
    const comment = commentMatch ? after.slice(commentMatch[0].length).trim() : "";
    const n = index + 1;
    recommendations.push({ n, text, grade: item.grade, evidence: item.evidence, ...(comment ? { comment: oneLine(comment) } : {}) });
    out.push(`### Рекомендация ${label}/${n} · УУР ${item.grade} · УДД ${item.evidence}\n\n${text}`);
    if (comment) out.push(`**Комментарий.** ${comment}`);
    else if (after.trim()) out.push(after.trim());
    cursor = next;
  });
  return { body: out.join("\n\n"), recommendations };
}

/**
 * The document's sections in reading order, or `[]` when it has no usable
 * structure (fewer than three headings), in which case it stays one file.
 */
export function splitIntoSections(source: string): KnowledgeSection[] {
  const lines = source.normalize("NFC").split("\n");
  const pages: (number | undefined)[] = [];
  const candidates: Candidate[] = [];
  let page: number | undefined;
  let tocLine = -1;
  lines.forEach((raw, index) => {
    const mark = PAGE_MARK.exec(raw.trim());
    if (mark) page = Number(mark[1]);
    pages[index] = page;
    if (mark) return;
    if (tocLine < 0 && TOC_MARK.test(raw.trim())) {
      tocLine = index;
      return;
    }
    const candidate = candidateOf(raw, index, page);
    if (candidate) candidates.push(candidate);
  });

  // The table of contents runs from its mark to the first heading that repeats one of its entries.
  const toc = new Map<string, string>();
  let bodyFrom = 0;
  if (tocLine >= 0) {
    const after = candidates.filter((candidate) => candidate.line > tocLine);
    const seen = new Map<string, string>();
    let end = -1;
    for (const candidate of after) {
      if (seen.has(candidate.key)) {
        end = candidate.line;
        break;
      }
      seen.set(candidate.key, candidate.title);
    }
    // Trust it only if it closes early and lists real structure.
    if (end >= 0 && seen.size >= MIN_SECTIONS && end - tocLine < Math.max(200, lines.length * 0.15)) {
      for (const [key, title] of seen) toc.set(key, title);
      bodyFrom = end;
    }
  }
  const tocNumbers = [...toc.keys()].filter((key) => /^\d/.test(key));
  const tocListsChildrenOf = (parent: string) => tocNumbers.some((number) => parentOf(number) === parent);
  const numberedBody = new Set(candidates.filter((c) => c.line >= bodyFrom && c.number).map((c) => c.number!));

  // Numbers for which some body line carries the TOC entry's own title: only that line is the heading.
  const titleMatches = (candidate: Candidate): boolean => {
    const want = normalize(toc.get(candidate.key) ?? "").slice(0, 10);
    return Boolean(want) && normalize(candidate.title).startsWith(want);
  };
  const confirmed = new Set(candidates.filter((c) => c.line >= bodyFrom && c.number && titleMatches(c)).map((c) => c.key));

  const accepted: Candidate[] = [];
  const taken = new Set<string>();
  let last: number[] | null = null;
  for (const candidate of candidates) {
    if (candidate.line < bodyFrom || taken.has(candidate.key)) continue;
    if (candidate.mdLevel || !candidate.number) {
      // Named parts and Markdown headings. A named part mentioned mid-sentence is not a heading.
      if (!candidate.mdLevel && lines[candidate.line]!.trim().length > 200) continue;
    } else {
      const tuple = tupleOf(candidate.number);
      if (toc.has(candidate.number)) {
        if (confirmed.has(candidate.number)) {
          // Some line repeats the TOC title for this number: that one, not a list item numbered alike.
          if (!titleMatches(candidate)) continue;
        } else {
          // The body words this heading differently from the TOC: trust the outline order instead.
          if (last && !follows(last, tuple)) continue;
          if (/[.;:]$/.test(candidate.title) || candidate.title.length > 160) continue;
        }
      } else if (toc.size) {
        // Not in the TOC: allowed only where the TOC does not enumerate this level.
        if (tocListsChildrenOf(parentOf(candidate.number))) continue;
        if (!last || !follows(last, tuple)) continue;
      } else {
        // No TOC at all: accept multi-level numbers, and top-level ones only when they have numbered children.
        if (tuple.length === 1 && !numberedBody.has(`${candidate.number}.1`)) continue;
        if (last && !follows(last, tuple)) continue;
        if (!last && tuple[0]! > 2) continue;
        if (/[.:]$/.test(candidate.title) || candidate.title.length > 120) continue;
      }
      last = tuple;
    }
    taken.add(candidate.key);
    accepted.push(candidate);
  }
  if (accepted.length < MIN_SECTIONS) return [];

  const sections: KnowledgeSection[] = [];
  const push = (base: Omit<KnowledgeSection, "body" | "recommendations" | "slug"> & { slug: string }, from: number, to: number) => {
    // Pages that hold this section's text; a page break right before the next heading is not one of them.
    const span = pages
      .slice(from, to)
      .filter((value, offset): value is number => {
        const trimmed = lines[from + offset]!.trim();
        return value !== undefined && trimmed !== "" && !PAGE_MARK.test(trimmed) && !/^\d{1,3}$/.test(trimmed);
      });
    const raw = lines
      .slice(from, to)
      .filter((line, offset) => {
        const trimmed = line.trim();
        // A bare page number printed next to a page break.
        if (/^\d{1,3}$/.test(trimmed)) {
          const near = [lines[from + offset - 1], lines[from + offset + 1]].some((other) => other !== undefined && PAGE_MARK.test(other.trim()));
          if (near) return false;
        }
        return true;
      })
      .join("\n")
      .replace(/\n{3,}/g, "\n\n")
      .replace(/^(?:\s*<!-- page \d+ -->)+/, "")
      .replace(/(?:<!-- page \d+ -->\s*)+$/, "")
      .trim();
    const label = base.number ?? base.title.split(/[.:]/)[0]!.trim();
    const structured = structureRecommendations(raw, label);
    const order = String(sections.length + 1).padStart(2, "0");
    sections.push({
      ...base,
      ...(span.length ? { pageStart: Math.min(...span), pageEnd: Math.max(...span) } : {}),
      body: structured.body,
      recommendations: structured.recommendations,
      slug: `${order}_${base.slug}`,
    });
  };

  // What precedes the first heading: the title page (the TOC itself is replaced by our index).
  const frontEnd = tocLine >= 0 && toc.size ? tocLine : accepted[0]!.line;
  if (lines.slice(0, frontEnd).join("\n").replace(/<!-- page \d+ -->/g, "").trim().length >= 80) {
    push({ key: "титул", title: "Титульная страница", level: 1, slug: "titul" }, 0, frontEnd);
  }

  const mdStack: { level: number; key: string }[] = [];
  accepted.forEach((candidate, index) => {
    const heading = fullTitle(lines, candidate.line, candidate.title);
    const from = candidate.line + heading.lines;
    const to = accepted[index + 1]?.line ?? lines.length;
    let level = 1;
    let parent: string | undefined;
    if (candidate.mdLevel) {
      level = candidate.mdLevel;
      while (mdStack.length && mdStack[mdStack.length - 1]!.level >= level) mdStack.pop();
      parent = mdStack[mdStack.length - 1]?.key;
      mdStack.push({ level, key: candidate.key });
    } else if (candidate.number) {
      level = tupleOf(candidate.number).length;
      // The nearest ancestor that exists as a section (documents sometimes skip a level).
      let up = parentOf(candidate.number);
      while (up && !taken.has(up)) up = parentOf(up);
      parent = up || undefined;
    }
    const title = candidate.number ? `${candidate.number} ${heading.title}` : heading.title;
    push({ key: candidate.key, ...(candidate.number ? { number: candidate.number } : {}), title, level, ...(parent ? { parent } : {}), slug: candidate.slug }, from, to);
  });
  return sections;
}
