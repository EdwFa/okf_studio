/**
 * Checking a bundle against the conformance rules of OKF 0.2 (§11):
 *   1. every non-reserved `.md` file has a parseable YAML frontmatter block;
 *   2. that block has a non-empty `type`;
 *   3. reserved files follow their sections: `index.md` has no frontmatter
 *      other than `okf_version` at the bundle root (§8), `log.md` has none and
 *      its date headings are ISO `YYYY-MM-DD` (§9).
 */
import { parse as parseYaml } from "yaml";

function splitFrontmatter(content: string): { meta: string | null; body: string } {
  if (!content.startsWith("---\n")) return { meta: null, body: content };
  const end = content.indexOf("\n---\n", 3);
  return end < 0 ? { meta: null, body: content } : { meta: content.slice(4, end), body: content.slice(end + 5) };
}

/** Problems found in a bundle, as "path: what is wrong"; empty when the bundle conforms. `files` maps bundle-relative paths to contents. */
export function checkBundle(files: Map<string, string>): string[] {
  const problems: string[] = [];
  for (const [file, content] of files) {
    if (!file.endsWith(".md")) continue;
    const name = file.split("/").pop()!;
    const { meta, body } = splitFrontmatter(content);
    if (name === "index.md") {
      if (meta === null) continue;
      let keys: string[] = [];
      try {
        keys = Object.keys((parseYaml(meta) as Record<string, unknown> | null) ?? {});
      } catch {
        problems.push(`${file}: frontmatter is not valid YAML`);
        continue;
      }
      const extra = keys.filter((key) => key !== "okf_version");
      if (file !== "index.md") problems.push(`${file}: an index file below the bundle root must not have frontmatter`);
      else if (extra.length) problems.push(`${file}: the root index may carry only okf_version, found ${extra.join(", ")}`);
      continue;
    }
    if (name === "log.md") {
      if (meta !== null) problems.push(`${file}: a log file must not have frontmatter`);
      for (const row of body.split("\n")) {
        if (row.startsWith("## ") && !/^## \d{4}-\d{2}-\d{2}$/.test(row)) problems.push(`${file}: date heading "${row}" is not YYYY-MM-DD`);
      }
      continue;
    }
    if (meta === null) {
      problems.push(`${file}: no frontmatter block`);
      continue;
    }
    try {
      const parsed = parseYaml(meta) as Record<string, unknown> | null;
      if (!parsed || typeof parsed.type !== "string" || !parsed.type.trim()) problems.push(`${file}: frontmatter has no type`);
    } catch {
      problems.push(`${file}: frontmatter is not valid YAML`);
    }
  }
  return problems;
}
