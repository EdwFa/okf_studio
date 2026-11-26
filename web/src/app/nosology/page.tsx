import { readFileSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import { markdownFile } from "@/lib/parse-files";
import { Classifier } from "./classifier";
import { nestRubrics, type RubricNames } from "./rubrics";
import "./nosology.css";

export const dynamic = "force-dynamic";

function rubricNames(): RubricNames {
  const file = path.join(os.homedir(), "ClinRec", "data", "mkb10.json");
  return JSON.parse(readFileSync(file, "utf8")) as RubricNames;
}

function treeHtml() {
  const file = [process.cwd(), path.join(process.cwd(), "..")]
    .map((dir) => path.join(dir, "nosology.html"))
    .find((candidate) => {
      try {
        readFileSync(candidate);
        return true;
      } catch {
        return false;
      }
    });
  if (!file) throw new Error("nosology.html не найден");
  const html = readFileSync(file, "utf8");
  const start = html.indexOf("<ul class=\"tree\"");
  const end = html.indexOf("</main>");
  if (start < 0 || end < 0) throw new Error("В nosology.html нет дерева классификатора");
  const list = html.slice(start, end);
  const innerStart = list.indexOf(">") + 1;
  const innerEnd = list.lastIndexOf("</ul>");
  const linked = list.slice(innerStart, innerEnd)
    .replace(/href="\.\.\/ClinRec\/data\/text\/(\d+_\d+)\.md"/g, "href=\"/clinrec/$1\"")
    .replace(/href="data\/pdf\/(\d+_\d+)\.pdf"/g, "href=\"/pdf/$1\"")
    .replace(/<a class="ext" href="\/pdf\/(\d+_\d+)" target="_blank" rel="noopener">PDF<\/a>/g, (link, id: string) => {
      const parsed = markdownFile(id)
        ? `<a class="ext md" href="/parse/${id}">MD</a>`
        : `<span class="ext md is-off">MD</span>`;
      return `${link}${parsed}`;
    });
  return nestRubrics(linked, rubricNames());
}

export default function NosologyPage() {
  const tree = treeHtml();
  return <Classifier treeHtml={tree.html} rubricCount={tree.count} />;
}
