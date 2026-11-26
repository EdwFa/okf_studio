export type RubricNames = Record<string, string>;

const DOC = /<li class="doc"[\s\S]*?<\/li>/g;
const RANGE = /^([A-Z])(\d{2})[–-]([A-Z])(\d{2})$/;
const RUBRIC = /^([A-Z])(\d{2})$/;

function escapeHtml(value: string) {
  return value
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function codesOf(doc: string) {
  const title = doc.match(/class="codes" title="([^"]*)"/)?.[1] ?? "";
  return title.split(",").map((code) => code.trim().toUpperCase()).filter(Boolean);
}

function inRange(key: string, letter: string, from: number, to: number) {
  return key[0] === letter && Number(key.slice(1)) >= from && Number(key.slice(1)) <= to;
}

function fallbackName(key: string, docs: string[], names: RubricNames) {
  if (names[key]) return names[key];
  const titles = new Set<string>();
  for (const doc of docs) {
    for (const code of codesOf(doc)) {
      if (code.startsWith(key) && names[code]) titles.add(names[code]);
    }
  }
  return titles.size === 1 ? [...titles][0] : "";
}

function rubricKey(doc: string, letter: string, from: number, to: number) {
  const keys = codesOf(doc)
    .map((code) => code.match(/^([A-Z])(\d{2})/))
    .filter((match): match is RegExpMatchArray => match !== null)
    .map((match) => match[1] + match[2]);
  const inside = keys.filter((key) => inRange(key, letter, from, to));
  const pool = inside.length > 0 ? inside : keys;
  if (pool.length === 0) return "";
  const counts = new Map<string, number>();
  for (const key of pool) counts.set(key, (counts.get(key) ?? 0) + 1);
  let best = pool[0];
  let bestCount = 0;
  for (const key of pool) {
    const count = counts.get(key) ?? 0;
    if (count > bestCount) {
      best = key;
      bestCount = count;
    }
  }
  return best;
}

function ageOf(doc: string) {
  return doc.match(/data-age="([^"]*)"/)?.[1] ?? "";
}

function track(docs: string[]) {
  const adult = docs.filter((doc) => ageOf(doc) === "взрослые").length;
  const child = docs.filter((doc) => ageOf(doc) === "дети").length;
  const both = docs.filter((doc) => ageOf(doc) === "взрослые и дети").length;
  const total = docs.length || 1;
  const width = (count: number) => ((count / total) * 100).toFixed(2);
  const bars = [
    adult ? `<i class="adult" style="width:${width(adult)}%"></i>` : "",
    child ? `<i class="child" style="width:${width(child)}%"></i>` : "",
    both ? `<i class="both" style="width:${width(both)}%"></i>` : "",
  ].join("");
  return `<span class="track" title="взрослые ${adult}, дети ${child}, взрослые и дети ${both}">${bars}</span>`;
}

function rubricItem(key: string, name: string, docs: string[]) {
  const title = name || key;
  const search = `${key.toLowerCase()} ${title.toLowerCase()}`;
  return `<li class="rubric" data-total="${docs.length}" data-search="${escapeHtml(search)}"><details><summary><span class="code">${key}</span><span class="label"><span class="title">${escapeHtml(title)}</span></span>${track(docs)}<span class="count">${docs.length}</span></summary><ul class="docs">${docs.join("")}</ul></details></li>`;
}

function groupDocs(inner: string, blockCode: string, names: RubricNames) {
  const range = blockCode.match(RANGE);
  if (!range || RUBRIC.test(blockCode)) return inner;
  const letter = range[1];
  const from = Number(range[2]);
  const to = Number(range[4]);
  if (letter !== range[3]) return inner;
  const docs = inner.match(DOC) ?? [];
  if (docs.length === 0) return inner;
  const groups = new Map<string, string[]>();
  const loose: string[] = [];
  for (const doc of docs) {
    const key = rubricKey(doc, letter, from, to);
    if (!key) {
      loose.push(doc);
      continue;
    }
    const list = groups.get(key);
    if (list) list.push(doc);
    else groups.set(key, [doc]);
  }
  const items = [...groups.keys()]
    .sort((a, b) => a.localeCompare(b))
    .map((key) => {
      const docs = groups.get(key) ?? [];
      return rubricItem(key, fallbackName(key, docs, names), docs);
    });
  return `${items.join("")}${loose.join("")}`;
}

export function nestRubrics(html: string, names: RubricNames) {
  const marker = '<ul class="docs">';
  let result = "";
  let cursor = 0;
  let count = 0;
  while (cursor < html.length) {
    const start = html.indexOf(marker, cursor);
    if (start < 0) {
      result += html.slice(cursor);
      break;
    }
    const contentStart = start + marker.length;
    const end = html.indexOf("</ul>", contentStart);
    if (end < 0) {
      result += html.slice(cursor);
      break;
    }
    const before = html.slice(Math.max(0, start - 1200), start);
    const codes = [...before.matchAll(/<span class="code">([^<]+)<\/span>/g)];
    const blockCode = codes.at(-1)?.[1] ?? "";
    const grouped = groupDocs(html.slice(contentStart, end), blockCode, names);
    count += grouped.match(/class="rubric"/g)?.length ?? 0;
    result += html.slice(cursor, contentStart) + grouped;
    cursor = end;
  }
  return { html: result, count };
}
