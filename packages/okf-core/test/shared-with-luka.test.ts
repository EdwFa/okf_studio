/**
 * okf-core starts as a copy of two files from Luka (k-dense-pi). Until Luka
 * depends on this package instead of its own files, the copies must stay
 * identical: fix a splitting rule in one place and this test tells you to
 * carry it over. Skipped where Luka's checkout is not next to this one.
 */
import fs from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

const here = path.dirname(new URL(import.meta.url).pathname);
const luka = process.env.LUKA_DIR ?? path.resolve(here, "../../../../k-dense-pi");
const pairs: [string, string][] = [
  ["../src/sections.ts", "server/src/knowledge-sections.ts"],
  ["../python/extract_text.py", "server/src/helpers/knowledge_helper.py"],
];

describe.skipIf(!fs.existsSync(luka))("copies shared with Luka", () => {
  for (const [mine, theirs] of pairs) {
    it(`${path.basename(mine)} matches Luka's ${theirs}`, () => {
      expect(fs.readFileSync(path.resolve(here, mine), "utf-8")).toBe(fs.readFileSync(path.join(luka, theirs), "utf-8"));
    });
  }
});
