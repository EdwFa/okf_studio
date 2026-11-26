import { existsSync, readdirSync, readFileSync } from "node:fs";
import path from "node:path";

const ID = /^\d+_\d+$/;

export function repoRoot(): string {
  const cwd = process.cwd();
  if (existsSync(path.join(cwd, "data", "pdf"))) return cwd;
  const parent = path.join(cwd, "..");
  if (existsSync(path.join(parent, "data", "pdf"))) return parent;
  throw new Error("Каталог data/pdf не найден");
}

export function pdfFile(id: string): string | null {
  if (!ID.test(id)) return null;
  const file = path.join(repoRoot(), "data", "pdf", `${id}.pdf`);
  return existsSync(file) ? file : null;
}

/** Свежий разбор важнее пробного файла. */
export function markdownFile(id: string): string | null {
  if (!ID.test(id)) return null;
  const root = repoRoot();
  for (const dir of ["data/md", "data/md-trial"]) {
    const file = path.join(root, dir, `${id}.md`);
    if (existsSync(file)) return file;
  }
  return null;
}

export function outputFile(id: string): string {
  return path.join(repoRoot(), "data", "md", `${id}.md`);
}

export interface ParseDoc {
  id: string;
  name: string;
  age: string;
  year: string;
  codes: string;
  ready: boolean;
}

interface IndexRow {
  id?: string;
  name?: string;
  age_category?: string;
  publish_date?: string;
  mkb10?: string[];
}

let cached: ParseDoc[] | null = null;

export function parseDocs(): ParseDoc[] {
  if (cached) return cached.map((doc) => ({ ...doc, ready: markdownFile(doc.id) !== null }));
  const root = repoRoot();
  const ids = readdirSync(path.join(root, "data", "pdf"))
    .filter((name) => name.endsWith(".pdf"))
    .map((name) => name.slice(0, -4))
    .filter((id) => ID.test(id));
  const byId = new Map<string, IndexRow>();
  const indexFile = path.join(process.env.HOME || "", "ClinRec", "data", "index.json");
  if (existsSync(indexFile)) {
    const rows = JSON.parse(readFileSync(indexFile, "utf8")) as IndexRow[];
    for (const row of rows) if (row.id) byId.set(row.id, row);
  }
  cached = ids
    .map((id) => {
      const row = byId.get(id);
      return {
        id,
        name: (row?.name || id).trim(),
        age: row?.age_category || "",
        year: (row?.publish_date || "").slice(0, 4),
        codes: (row?.mkb10 || []).join(" "),
        ready: false,
      };
    })
    .sort((a, b) => a.name.localeCompare(b.name, "ru"));
  return parseDocs();
}
