/** The studio API end to end, against a temporary data directory and a stub extractor. */
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import AdmZip from "adm-zip";
import type { FastifyInstance } from "fastify";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { parse as parseYaml } from "yaml";
import { checkBundle } from "okf-core";
import { GUIDELINE } from "../../packages/okf-core/test/fixture.ts";
import { buildApp } from "../src/app.ts";
import type { Jobs } from "../src/jobs.ts";
import { guessMetadata, type DocumentView } from "../src/store.ts";

let dataDir: string;
let app: FastifyInstance;
let jobs: Jobs;

const start = async () => {
  ({ app, jobs } = await buildApp({ dataDir, lukaAgentDir: path.join(dataDir, "luka"), extract: async (file) => (file.endsWith(".pdf") ? { text: GUIDELINE, pages: 6 } : { text: fs.readFileSync(file, "utf-8") }) }));
};
beforeEach(async () => {
  dataDir = fs.mkdtempSync(path.join(os.tmpdir(), "okf-studio-"));
  await start();
});
afterEach(async () => {
  await app.close();
  fs.rmSync(dataDir, { recursive: true, force: true });
});

const call = async <T = any>(method: string, url: string, body?: unknown): Promise<{ status: number; json: T }> => {
  const res = await app.inject({ method: method as "GET", url, ...(body === undefined ? {} : { payload: body as object }) });
  return { status: res.statusCode, json: res.headers["content-type"]?.toString().includes("json") ? res.json() : (res.rawPayload as unknown as T) };
};

function multipartBody(files: { name: string; content: string }[]) {
  const boundary = "----okfstudiotest";
  const parts = files.map(
    (file) => `--${boundary}\r\nContent-Disposition: form-data; name="files"; filename="${file.name}"\r\nContent-Type: application/octet-stream\r\n\r\n${file.content}\r\n`,
  );
  return { payload: `${parts.join("")}--${boundary}--\r\n`, headers: { "content-type": `multipart/form-data; boundary=${boundary}` } };
}

async function setup(files = [{ name: "КР тест.pdf", content: "%PDF" }]) {
  const domain = (await call("POST", "/domains", { name: "Онкология головы и шеи", owner: "Э. Ф." })).json;
  const group = (await call("POST", `/domains/${domain.id}/groups`, { name: "КР Минздрава" })).json;
  const upload = await app.inject({ method: "POST", url: `/groups/${group.id}/documents`, ...multipartBody(files) });
  await jobs.whenIdle();
  return { domain, group, upload: upload.json() as { added: { id: string }[]; failed: { name: string; detail: string }[] } };
}

const view = async (id: string) => (await call<DocumentView>("GET", `/documents/${id}`)).json;

describe("domains and groups", () => {
  it("creates, renames, orders and refuses duplicates", async () => {
    const a = (await call("POST", "/domains", { name: "Онкология" })).json;
    const b = (await call("POST", "/domains", { name: "Травматология" })).json;
    expect((await call("POST", "/domains", { name: "онкология" })).status).toBe(409);
    expect((await call("POST", "/domains", { name: " " })).status).toBe(400);
    await call("PUT", "/domains/order", { order: [b.id, a.id] });
    await call("PATCH", `/domains/${a.id}`, { name: "Онкология головы и шеи", description: "ОГШ" });
    const catalog = (await call("GET", "/catalog")).json;
    expect(catalog.domains.map((d: any) => d.name)).toEqual(["Травматология", "Онкология головы и шеи"]);
    expect(catalog.limits.extensions).toContain(".pdf");
  });

  it("moves a group between domains and deletes only what is empty", async () => {
    const { domain, group, upload } = await setup();
    const other = (await call("POST", "/domains", { name: "Архив" })).json;
    expect((await call("DELETE", `/groups/${group.id}`)).status).toBe(409);
    expect((await call("DELETE", `/domains/${domain.id}`)).status).toBe(409);
    await call("PATCH", `/groups/${group.id}`, { domainId: other.id, hidden: true });
    const catalog = (await call("GET", "/catalog")).json;
    expect(catalog.domains[0].groups).toEqual([]);
    expect(catalog.domains[1].groups[0]).toMatchObject({ name: "КР Минздрава", hidden: true, documents: 1 });
    expect((await call("DELETE", `/domains/${domain.id}`)).status).toBe(200);
    await call("DELETE", `/documents/${upload.added[0]!.id}`);
    expect((await call("DELETE", `/groups/${group.id}`)).status).toBe(200);
    expect(fs.existsSync(path.join(dataDir, "docs", upload.added[0]!.id))).toBe(false);
  });
});

describe("nested groups", () => {
  it("nests groups to any depth, keeps names unique among siblings and guards the tree", async () => {
    const domain = (await call("POST", "/domains", { name: "Онкология головы и шеи" })).json;
    const kr = (await call("POST", `/domains/${domain.id}/groups`, { name: "Клинические рекомендации" })).json;
    const mz = (await call("POST", `/domains/${domain.id}/groups`, { name: "Минздрав", parentId: kr.id })).json;
    const y24 = (await call("POST", `/domains/${domain.id}/groups`, { name: "2024", parentId: mz.id })).json;
    const nccn = (await call("POST", `/domains/${domain.id}/groups`, { name: "NCCN", parentId: kr.id })).json;
    expect(y24).toMatchObject({ parentId: mz.id });
    expect((await call("POST", `/domains/${domain.id}/groups`, { name: "минздрав", parentId: kr.id })).status).toBe(409);
    expect((await call("POST", `/domains/${domain.id}/groups`, { name: "Минздрав" })).status).toBe(200); // same name, another level
    expect((await call("POST", `/domains/${domain.id}/groups`, { name: "X", parentId: "nope" })).status).toBe(404);

    expect((await call("PATCH", `/groups/${kr.id}`, { parentId: y24.id })).json.detail).toContain("в саму себя");
    expect((await call("DELETE", `/groups/${mz.id}`)).json.detail).toContain("подгруппы");
    await call("PATCH", `/groups/${y24.id}`, { parentId: nccn.id });
    await call("PATCH", `/groups/${nccn.id}`, { parentId: "" });
    let groups = (await call("GET", "/catalog")).json.domains[0].groups;
    expect(groups.find((group: any) => group.id === y24.id).parentId).toBe(nccn.id);
    expect(groups.find((group: any) => group.id === nccn.id).parentId).toBeUndefined();

    // A group moves to another domain with everything nested in it.
    const other = (await call("POST", "/domains", { name: "Архив" })).json;
    await call("PATCH", `/groups/${nccn.id}`, { domainId: other.id });
    const catalog = (await call("GET", "/catalog")).json;
    expect(catalog.domains[1].groups.map((group: any) => [group.name, group.parentId])).toEqual([["NCCN", undefined], ["2024", nccn.id]]);
    expect(catalog.domains[0].groups.map((group: any) => group.name)).toEqual(["Клинические рекомендации", "Минздрав", "Минздрав"]);
    expect((await call("DELETE", `/groups/${y24.id}`)).status).toBe(200);
  });

  it("publishes and exports a nested group under its full path", async () => {
    const { domain, group, upload } = await setup();
    const parent = (await call("POST", `/domains/${domain.id}/groups`, { name: "Клинические рекомендации" })).json;
    await call("PATCH", `/groups/${group.id}`, { parentId: parent.id });
    await call("PATCH", `/documents/${upload.added[0]!.id}`, { status: "reviewed" });
    fs.mkdirSync(path.join(dataDir, "luka"), { recursive: true });
    await call("POST", `/groups/${group.id}/publish`);
    const state = JSON.parse(fs.readFileSync(path.join(dataDir, "luka", "knowledge", "knowledge.json"), "utf-8"));
    expect(state.groups[0].name).toBe("Клинические рекомендации / КР Минздрава");
    expect(fs.readFileSync(path.join(dataDir, "luka", "skills", `kb-${group.id}`, "SKILL.md"), "utf-8")).toContain("# База знаний: Клинические рекомендации / КР Минздрава");
    const zip = new AdmZip((await call<Buffer>("GET", `/domains/${domain.id}/export`)).json);
    expect(zip.readAsText("index.md")).toContain(`- [Клинические рекомендации / КР Минздрава](${group.id}/index.md)`);
  });

  it("drops a broken parent link when the catalog is read", async () => {
    const domain = (await call("POST", "/domains", { name: "Д" })).json;
    const a = (await call("POST", `/domains/${domain.id}/groups`, { name: "А" })).json;
    const b = (await call("POST", `/domains/${domain.id}/groups`, { name: "Б", parentId: a.id })).json;
    const file = path.join(dataDir, "studio.json");
    const raw = JSON.parse(fs.readFileSync(file, "utf-8"));
    raw.domains[0].groups[0].parentId = b.id; // a loop: А inside Б inside А
    fs.writeFileSync(file, JSON.stringify(raw));
    await app.close();
    await start();
    const groups = (await call("GET", "/catalog")).json.domains[0].groups;
    expect(groups.filter((group: any) => group.parentId).length).toBeLessThan(2);
  });
});

describe("documents", () => {
  it("parses an upload in the background and fills the card from the title page", async () => {
    const { upload, group } = await setup([{ name: "КР тест.pdf", content: "%PDF" }, { name: "макрос.exe", content: "MZ" }]);
    expect(upload.failed).toEqual([{ name: "макрос.exe", detail: expect.stringContaining("не поддерживается") }]);
    const { doc, sections, domain } = await view(upload.added[0]!.id);
    expect(doc).toMatchObject({ title: "КР тест", kind: "guideline", year: 2024, status: "draft", job: { state: "ready" }, sections: 14, recommendations: 4, pages: 6 });
    expect(domain?.name).toBe("Онкология головы и шеи");
    expect(sections[6]).toMatchObject({ number: "2.1", heading: "Жалобы и анамнез", title: "2.1 Жалобы и анамнез", level: 2, parentId: sections[5]!.id, status: "draft", edited: false });
    expect(sections[6]!.recommendations[0]).toMatchObject({ n: 1, grade: "C", evidence: "5" });
    expect((await call("GET", `/groups/${group.id}/documents`)).json.documents).toHaveLength(1);
    expect(fs.readFileSync(path.join(dataDir, "log.md"), "utf-8")).toContain("документ разобран");
  });

  it("reports a file without text and keeps a headingless text as one section", async () => {
    const { upload } = await setup([{ name: "скан.txt", content: "   " }, { name: "заметки.txt", content: "Просто заметки без заголовков." }]);
    const [scan, notes] = await Promise.all(upload.added.map((doc) => view(doc.id)));
    expect(scan!.doc.job).toMatchObject({ state: "failed", error: expect.stringContaining("не найден текст") });
    expect(notes!.sections).toHaveLength(1);
    expect(notes!.sections[0]).toMatchObject({ heading: "заметки", body: "Просто заметки без заголовков." });
  });

  it("validates and saves the card", async () => {
    const { upload } = await setup();
    const id = upload.added[0]!.id;
    expect((await call("PATCH", `/documents/${id}`, { icd10: ["рак"] })).status).toBe(400);
    expect((await call("PATCH", `/documents/${id}`, { approvedAt: "14.11.2024" })).status).toBe(400);
    const saved = (await call<DocumentView>("PATCH", `/documents/${id}`, { title: "Рак ротоглотки", icd10: "с10, C09.1", tags: ["ОГШ", "ОГШ", "2024"], approvedAt: "2024-11-14", version: "2", url: "https://cr.minzdrav.gov.ru/" })).json;
    expect(saved.doc).toMatchObject({ title: "Рак ротоглотки", icd10: ["C10", "C09.1"], tags: ["ОГШ", "2024"], approvedAt: "2024-11-14", version: "2" });
    expect((await call("GET", `/documents/${id}/history`)).json.history[0]).toMatchObject({ action: "карточка изменена" });
  });

  it("survives a restart and resumes unfinished parsing", async () => {
    const { upload } = await setup();
    const id = upload.added[0]!.id;
    const meta = path.join(dataDir, "docs", id, "meta.json");
    fs.writeFileSync(meta, JSON.stringify({ ...JSON.parse(fs.readFileSync(meta, "utf-8")), job: { state: "processing" } }));
    await app.close();
    await start();
    await jobs.whenIdle();
    expect((await view(id)).doc.job.state).toBe("ready");
    expect((await call("GET", "/catalog")).json.domains[0].groups[0].documents).toBe(1);
  });
});

describe("editing sections", () => {
  it("edits text and heading, renumbers recommendations and resets the review status", async () => {
    const { upload } = await setup();
    const id = upload.added[0]!.id;
    let state = await view(id);
    const lab = state.sections.find((section) => section.number === "2.2")!;
    await call("PATCH", `/documents/${id}`, { sectionsStatus: "reviewed" });
    state = (await call<DocumentView>("PATCH", `/documents/${id}`, { status: "reviewed" })).json;
    expect(state.doc).toMatchObject({ status: "reviewed", reviewedSections: 14 });

    const body = `### Рекомендация 2.2/7 · УУР A · УДД 1\n\nРекомендуется новый анализ.\n\n${lab.body}`;
    state = (await call<DocumentView>("PATCH", `/documents/${id}/sections/${lab.id}`, { body, heading: "Лабораторная диагностика" })).json;
    const edited = state.sections.find((section) => section.id === lab.id)!;
    expect(edited).toMatchObject({ title: "2.2 Лабораторная диагностика", edited: true, status: "draft" });
    expect(edited.recommendations.map((rec) => [rec.n, rec.grade])).toEqual([[1, "A"], [2, "C"], [3, "B"]]);
    expect(edited.body).toContain("### Рекомендация 2.2/3 · УУР B · УДД 2");
    expect(state.doc).toMatchObject({ status: "draft", reviewedSections: 13, recommendations: 5 });

    // Marking a section reviewed does not reopen the document.
    await call("PATCH", `/documents/${id}`, { status: "reviewed" });
    state = (await call<DocumentView>("PATCH", `/documents/${id}/sections/${lab.id}`, { status: "reviewed" })).json;
    expect(state.doc).toMatchObject({ status: "reviewed", reviewedSections: 14 });
  });

  it("splits a section at the cursor and merges it back", async () => {
    const { upload } = await setup();
    const id = upload.added[0]!.id;
    let state = await view(id);
    const lab = state.sections.find((section) => section.number === "2.2")!;
    const offset = lab.body.indexOf("### Рекомендация 2.2/2");
    expect((await call("POST", `/documents/${id}/sections/${lab.id}/split`, { offset: 0, heading: "x" })).status).toBe(400);
    state = (await call<DocumentView>("POST", `/documents/${id}/sections/${lab.id}/split`, { offset, heading: "Инструментальные исследования", number: "2.3" })).json;
    expect(state.sections).toHaveLength(15);
    const created = state.sections[state.sections.findIndex((section) => section.id === lab.id) + 1]!;
    expect(created).toMatchObject({ title: "2.3 Инструментальные исследования", level: 2, parentId: lab.parentId, pageStart: 4 });
    expect(created.body).toMatch(/^### Рекомендация 2\.3\/1 · УУР B · УДД 2/);
    expect(state.sections.find((section) => section.id === lab.id)!.recommendations).toHaveLength(1);
    expect(state.doc.recommendations).toBe(4);

    state = (await call<DocumentView>("POST", `/documents/${id}/sections/${created.id}/merge`)).json;
    const merged = state.sections.find((section) => section.id === lab.id)!;
    expect(state.sections).toHaveLength(14);
    expect(merged.body).toContain("2.3 Инструментальные исследования");
    expect(merged.recommendations.map((rec) => rec.n)).toEqual([1, 2]);
  });

  it("moves subsections up when their parent is deleted, and re-parents on request", async () => {
    const { upload } = await setup();
    const id = upload.added[0]!.id;
    let state = await view(id);
    const three = state.sections.find((section) => section.number === "3")!;
    const two = state.sections.find((section) => section.number === "2")!;
    state = (await call<DocumentView>("DELETE", `/documents/${id}/sections/${three.id}`)).json;
    const surgery = state.sections.find((section) => section.number === "3.1")!;
    expect(surgery).toMatchObject({ level: 1 });
    expect(surgery.parentId).toBeUndefined();
    state = (await call<DocumentView>("PATCH", `/documents/${id}/sections/${surgery.id}`, { parentId: two.id })).json;
    expect(state.sections.find((section) => section.id === surgery.id)).toMatchObject({ level: 2, parentId: two.id });
    const later = state.sections.at(-1)!;
    expect((await call("PATCH", `/documents/${id}/sections/${two.id}`, { parentId: later.id })).status).toBe(400);
  });

  it("edits a recommendation's grades and can unmark it", async () => {
    const { upload } = await setup();
    const id = upload.added[0]!.id;
    let state = await view(id);
    const section = state.sections.find((item) => item.number === "2.1")!;
    const url = `/documents/${id}/sections/${section.id}/recommendations/1`;
    expect((await call("PATCH", url, { grade: "D" })).status).toBe(400);
    state = (await call<DocumentView>("PATCH", url, { grade: "b", evidence: "3", comment: "" })).json;
    expect(state.sections.find((item) => item.id === section.id)!.recommendations).toEqual([
      { n: 1, grade: "B", evidence: "3", text: "Рекомендуется всем пациентам проводить сбор жалоб и анамнеза с целью выявления факторов риска [1]." },
    ]);
    state = (await call<DocumentView>("PATCH", url, { remove: true })).json;
    const plain = state.sections.find((item) => item.id === section.id)!;
    expect(plain.recommendations).toEqual([]);
    expect(plain.body).toBe("Рекомендуется всем пациентам проводить сбор жалоб и анамнеза с целью выявления факторов риска [1].");
    expect((await call("PATCH", url, { grade: "A" })).status).toBe(404);
  });

  it("restores the automatic split on request", async () => {
    const { upload } = await setup();
    const id = upload.added[0]!.id;
    const first = (await view(id)).sections[1]!;
    await call("DELETE", `/documents/${id}/sections/${first.id}`);
    const state = (await call<DocumentView>("POST", `/documents/${id}/resplit`)).json;
    expect(state.sections).toHaveLength(14);
    expect(state.sections.every((section) => !section.edited)).toBe(true);
  });
});

describe("OKF export", () => {
  it("zips a domain as typed Markdown with the card's metadata and manual edits", async () => {
    const { domain, group, upload } = await setup([{ name: "КР тест.pdf", content: "%PDF" }, { name: "заметки.txt", content: "Просто заметки." }]);
    const id = upload.added[0]!.id;
    const section = (await view(id)).sections.find((item) => item.number === "2.1")!;
    await call("PATCH", `/documents/${id}/sections/${section.id}/recommendations/1`, { grade: "A" });
    await call("PATCH", `/documents/${id}`, { icd10: ["C10"] });
    const zip = new AdmZip((await call<Buffer>("GET", `/domains/${domain.id}/export`)).json);
    const names = zip.getEntries().map((entry) => entry.entryName);
    expect(names).toContain("index.md");
    expect(names).toContain(`${group.id}/index.md`);
    expect(names).toContain(`${group.id}/${id}/07_2.1.md`);
    expect(names).toContain(`${group.id}/${upload.added[1]!.id}.md`);
    const index = zip.readAsText(`${group.id}/${id}.md`);
    expect(index).toMatch(/^---\ntype: document\n/);
    expect(index).toContain("kind: клинические рекомендации");
    expect(index).toContain("- C10");
    expect(zip.readAsText(`${group.id}/${id}/recommendations.md`)).toContain("| 2.1/1 | [2.1 Жалобы и анамнез](07_2.1.md) | A | 5 |");
    expect(zip.readAsText(`${group.id}/index.md`)).toMatch(/^# КР Минздрава\n\n## Документы\n\n- \[/);
    expect(zip.readAsText(`${group.id}/index.md`)).toContain(`- [КР тест](${id}.md) — `);
    expect(zip.readAsText("index.md")).toMatch(/^---\nokf_version: "0.2"\n---\n\n# Онкология головы и шеи/);
    const files = new Map(zip.getEntries().map((entry) => [entry.entryName, zip.readAsText(entry)]));
    expect(checkBundle(files)).toEqual([]);
  });

  it("writes the standard OKF 0.2 keys: provenance, verification, status, staleness", async () => {
    const { group, upload } = await setup();
    const id = upload.added[0]!.id;
    const section = (await view(id)).sections.find((item) => item.number === "2.1")!;
    await call("PATCH", `/documents/${id}/sections/${section.id}`, { status: "reviewed" });
    await call("PATCH", `/documents/${id}`, { url: "https://cr.minzdrav.gov.ru/view/1", origin: "Минздрав России", tags: ["ОГШ"], reviewDue: "2026-12-31" });
    const read = async (name: string) => {
      const zip = new AdmZip((await call<Buffer>("GET", `/groups/${group.id}/export`)).json);
      const text = zip.readAsText(`${group.id}/${name}`);
      return parseYaml(text.slice(4, text.indexOf("\n---\n", 4))) as Record<string, any>;
    };
    let meta = await read(`${id}.md`);
    expect(meta).toMatchObject({
      status: "draft",
      resource: "https://cr.minzdrav.gov.ru/view/1",
      tags: ["ОГШ"],
      stale_after: "2026-12-31T00:00:00+00:00",
      sources: [{ id: "original", resource: "https://cr.minzdrav.gov.ru/view/1", author: "Минздрав России" }],
      generated: { by: "okf-studio/0.1.0" },
    });
    expect(meta.generated.at).toMatch(/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\+00:00$/);
    expect(meta).not.toHaveProperty("verified");
    // A section is verified on its own, by a named human, before the document is.
    expect(await read(`${id}/07_2.1.md`)).toMatchObject({ status: "stable", verified: [{ by: "human:Э. Ф." }], generated: { by: "okf-studio/0.1.0" } });
    expect(await read(`${id}/08_2.2.md`)).toMatchObject({ status: "draft" });

    await call("PATCH", `/documents/${id}`, { status: "reviewed" });
    meta = await read(`${id}.md`);
    expect(meta).toMatchObject({ status: "stable", verified: [{ by: "human:Э. Ф." }] });
    expect(meta.verified[0].at).toMatch(/\+00:00$/);
  });
});

describe("publishing to Luka", () => {
  const luka = () => path.join(dataDir, "luka");
  const state = () => JSON.parse(fs.readFileSync(path.join(luka(), "knowledge", "knowledge.json"), "utf-8")) as { groups: any[] };

  it("publishes only checked documents, flags them curated and builds the skill", async () => {
    const { group, upload } = await setup([{ name: "КР тест.pdf", content: "%PDF" }, { name: "заметки.txt", content: "Просто заметки без заголовков." }]);
    const [guide, notes] = upload.added.map((doc) => doc.id) as [string, string];
    expect((await call("POST", `/groups/${group.id}/publish`)).status).toBe(409); // Luka's folder is missing
    fs.mkdirSync(path.join(luka(), "knowledge"), { recursive: true });
    fs.writeFileSync(path.join(luka(), "knowledge", "knowledge.json"), JSON.stringify({ version: 1, groups: [{ id: "aaaaaaaaaa", name: "Своя группа Луки", hidden: false, docs: [] }] }));
    expect((await call("POST", `/groups/${group.id}/publish`)).json.detail).toContain("Публиковать нечего");

    const section = (await view(guide)).sections.find((item) => item.number === "2.1")!;
    await call("PATCH", `/documents/${guide}/sections/${section.id}/recommendations/1`, { grade: "A" });
    await call("PATCH", `/documents/${guide}`, { status: "reviewed" });
    const result = (await call("POST", `/groups/${group.id}/publish`)).json;
    expect(result).toMatchObject({ published: [{ id: guide }], kept: [], skipped: [{ id: notes }], removed: 0, visible: true });

    const groups = state().groups;
    expect(groups[0]).toMatchObject({ id: "aaaaaaaaaa", name: "Своя группа Луки" });
    expect(groups[1]).toMatchObject({ id: group.id, name: "КР Минздрава", hidden: false });
    expect(groups[1].docs).toEqual([expect.objectContaining({ id: guide, title: "КР тест", source: "КР тест.pdf", sections: 14, recommendations: 4, curated: true })]);
    const dir = path.join(luka(), "knowledge", group.id);
    expect(fs.readFileSync(path.join(dir, guide, "07_2.1.md"), "utf-8")).toContain("### Рекомендация 2.1/1 · УУР A · УДД 5");
    expect(fs.readFileSync(path.join(dir, `${guide}.md`), "utf-8")).toContain("status: stable");
    // What lands in Luka's store is a conformant OKF 0.2 bundle, reserved files included.
    const bundle = new Map<string, string>();
    const walk = (at: string) => {
      for (const entry of fs.readdirSync(at, { withFileTypes: true })) {
        const full = path.join(at, entry.name);
        if (entry.isDirectory()) walk(full);
        else if (entry.name.endsWith(".md")) bundle.set(path.relative(path.join(luka(), "knowledge"), full), fs.readFileSync(full, "utf-8"));
      }
    };
    walk(path.join(luka(), "knowledge"));
    expect([...bundle.keys()]).toEqual(expect.arrayContaining(["index.md", "log.md", `${group.id}/index.md`]));
    expect(checkBundle(bundle)).toEqual([]);
    expect(fs.readFileSync(path.join(dir, "sources", `${guide}.txt`), "utf-8")).toContain("Год утверждения: 2024");
    expect(fs.existsSync(path.join(dir, "sources", `${guide}.pdf`))).toBe(true);
    const skill = path.join(luka(), "skills", `kb-${group.id}`);
    expect(fs.readFileSync(path.join(skill, "SKILL.md"), "utf-8")).toMatch(/^---\nname: kb-[a-z0-9]+\ndescription: "?База знаний «КР Минздрава»: 1 documents/);
    expect(fs.existsSync(path.join(skill, guide, "07_2.1.md"))).toBe(true);
    expect(fs.existsSync(path.join(skill, ".kady-knowledge"))).toBe(true);
    expect((await view(guide)).doc).toMatchObject({ status: "published" });
    expect((await call("GET", `/groups/${group.id}/publication`)).json).toEqual({ published: true, documents: [guide] });
  });

  it("keeps the published version of a document edited since, and follows deletions and hiding", async () => {
    const { group, upload } = await setup([{ name: "КР тест.pdf", content: "%PDF" }, { name: "заметки.txt", content: "Просто заметки без заголовков." }]);
    const [guide, notes] = upload.added.map((doc) => doc.id) as [string, string];
    fs.mkdirSync(luka(), { recursive: true });
    for (const id of [guide, notes]) await call("PATCH", `/documents/${id}`, { status: "reviewed" });
    await call("POST", `/groups/${group.id}/publish`);
    const file = path.join(luka(), "knowledge", group.id, guide, "07_2.1.md");
    const published = fs.readFileSync(file, "utf-8");

    // Edited after publishing: a draft here, the published version stays in Luka.
    const section = (await view(guide)).sections.find((item) => item.number === "2.1")!;
    await call("PATCH", `/documents/${guide}/sections/${section.id}/recommendations/1`, { grade: "A" });
    expect((await view(guide)).doc.status).toBe("draft");
    await call("DELETE", `/documents/${notes}`);
    await call("PATCH", `/groups/${group.id}`, { hidden: true });
    const result = (await call("POST", `/groups/${group.id}/publish`)).json;
    expect(result).toMatchObject({ published: [], kept: [{ id: guide }], removed: 1, visible: false });
    expect(fs.readFileSync(file, "utf-8")).toBe(published);
    expect(fs.existsSync(path.join(luka(), "knowledge", group.id, `${notes}.md`))).toBe(false);
    expect(fs.existsSync(path.join(luka(), "skills", `kb-${group.id}`))).toBe(false);
    expect(state().groups[0]).toMatchObject({ hidden: true, docs: [expect.objectContaining({ id: guide })] });

    await call("PATCH", `/documents/${guide}`, { status: "reviewed" });
    await call("PATCH", `/groups/${group.id}`, { hidden: false });
    expect((await call("POST", `/groups/${group.id}/publish`)).json).toMatchObject({ published: [{ id: guide }], visible: true });
    expect(fs.readFileSync(file, "utf-8")).toContain("УУР A");
  });

  it("never touches a group or skill it did not create, and unpublishes cleanly", async () => {
    const { group, upload } = await setup();
    const id = upload.added[0]!.id;
    await call("PATCH", `/documents/${id}`, { status: "reviewed" });
    const foreign = path.join(luka(), "knowledge", group.id);
    fs.mkdirSync(foreign, { recursive: true });
    fs.writeFileSync(path.join(foreign, "index.md"), "чужое");
    expect((await call("POST", `/groups/${group.id}/publish`)).status).toBe(409);
    expect(fs.readFileSync(path.join(foreign, "index.md"), "utf-8")).toBe("чужое");
    fs.rmSync(foreign, { recursive: true });

    fs.mkdirSync(path.join(luka(), "knowledge"), { recursive: true });
    fs.writeFileSync(path.join(luka(), "knowledge", "knowledge.json"), JSON.stringify({ version: 1, groups: [{ id: "aaaaaaaaaa", name: "кр минздрава", hidden: false, docs: [] }] }));
    expect((await call("POST", `/groups/${group.id}/publish`)).json.detail).toContain("уже есть другая группа");
    fs.writeFileSync(path.join(luka(), "knowledge", "knowledge.json"), "{ broken");
    expect((await call("POST", `/groups/${group.id}/publish`)).json.detail).toContain("повреждён");
    fs.writeFileSync(path.join(luka(), "knowledge", "knowledge.json"), JSON.stringify({ version: 1, groups: [{ id: "aaaaaaaaaa", name: "Другая", hidden: false, docs: [] }] }));

    expect((await call("DELETE", `/groups/${group.id}/publication`)).status).toBe(409);
    await call("POST", `/groups/${group.id}/publish`);
    expect((await call("DELETE", `/groups/${group.id}/publication`)).status).toBe(200);
    expect(state().groups.map((item) => item.id)).toEqual(["aaaaaaaaaa"]);
    expect(fs.existsSync(foreign)).toBe(false);
    expect(fs.existsSync(path.join(luka(), "skills", `kb-${group.id}`))).toBe(false);
    expect((await view(id)).doc.status).toBe("reviewed");
  });
});

describe("guessMetadata", () => {
  it("reads the year and ICD-10 codes off a guideline's title page", () => {
    const head = "Клинические рекомендации\nРак ротоглотки\nКодирование по Международной статистической классификации\nболезней и проблем, связанных со здоровьем: С01, C09.0, С10\nГод утверждения (частота пересмотра): 2024\n";
    expect(guessMetadata(head)).toEqual({ year: 2024, icd10: ["C01", "C09.0", "C10"], kind: "guideline" });
    expect(guessMetadata("Статья о чём-то")).toEqual({ icd10: [], kind: "other" });
    expect(guessMetadata("Оглавление", "КР Рак носоглотки взр 2024.pdf")).toEqual({ year: 2024, icd10: [], kind: "guideline" });
  });
});
