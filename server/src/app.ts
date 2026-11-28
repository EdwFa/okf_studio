/**
 * HTTP API of the studio. Every route answers JSON; errors are
 * `{ detail: string }` with a 4xx status and a message meant for the user.
 *
 *   GET    /catalog                                   domains, groups, counts, limits
 *   POST   /catalog/seed                              create missing classifier shelves and hidden groups
 *   GET    /catalog/assignment                        cr id → group name, studio group, placed document
 *   POST   /catalog/place                             { crId } copy the local PDF into that group
 *   POST   /domains                                   { name, description?, owner? }
 *   PATCH  /domains/:id   DELETE /domains/:id         (delete: empty domains only)
 *   PUT    /domains/order                             { order: [domainId…] }
 *   POST   /domains/:id/show-to-agents                show this catalog shelf to agents and hide the others
 *   POST   /domains/:id/groups                        { name, description?, parentId? } — parentId nests the group
 *   PUT    /domains/:id/groups/order                  { order: [groupId…] }
 *   GET    /domains/:id/export                        OKF bundle (zip)
 *   PATCH  /groups/:id    DELETE /groups/:id          { name?, description?, hidden?, parentId?, domainId? }
 *   GET    /groups/:id/documents
 *   POST   /groups/:id/documents                      multipart `files` → { added, failed }
 *   GET    /groups/:id/export                         OKF bundle of one group (zip)
 *   GET    /groups/:id/publication                    { published, documents } — what Luka holds of the group
 *   POST   /groups/:id/publish                        publish checked documents into Luka's knowledge base
 *   DELETE /groups/:id/publication                    remove the group from Luka
 *   GET    /documents/:id                             { doc, sections, domain, group }
 *   PATCH  /documents/:id   DELETE /documents/:id
 *   GET    /documents/:id/source                      the original file
 *   GET    /documents/:id/text                        the extracted text
 *   GET    /documents/:id/history
 *   POST   /documents/:id/reparse                     extract and split again
 *   POST   /documents/:id/resplit                     split the stored text again
 *   PATCH  /documents/:id/sections/:sid               { heading?, number?, parentId?, body?, status?, pageStart?, pageEnd? }
 *   POST   /documents/:id/sections/:sid/split         { offset, heading, number? }
 *   POST   /documents/:id/sections/:sid/merge         join to the previous section
 *   DELETE /documents/:id/sections/:sid
 *   PATCH  /documents/:id/sections/:sid/recommendations/:n   { grade?, evidence?, text?, comment?, remove? }
 */
import fs from "node:fs";
import path from "node:path";
import { pipeline } from "node:stream/promises";
import cors from "@fastify/cors";
import multipart from "@fastify/multipart";
import Fastify, { type FastifyInstance } from "fastify";
import { exportZip, KIND_LABELS } from "./export.ts";
import { catalogAssignment, placeCr } from "./catalog/place.ts";
import { seedCatalog } from "./catalog/seed.ts";
import { showShelfToAgents } from "./catalog/show.ts";
import { extractText, type Extractor } from "./extract.ts";
import { Jobs } from "./jobs.ts";
import { publication, publishGroup, unpublishGroup } from "./publish.ts";
import { DOCUMENT_KINDS, EXTENSIONS, MAX_DOCUMENT_BYTES, Store, StoreError } from "./store.ts";

export interface AppOptions {
  dataDir: string;
  extract?: Extractor;
  /** Luka's agent directory, the target of publishing. */
  lukaAgentDir: string;
  /** Origins allowed to call the API from a browser. */
  origins?: string[];
}

const MIME: Record<string, string> = {
  ".pdf": "application/pdf",
  ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
  ".md": "text/markdown; charset=utf-8",
  ".markdown": "text/markdown; charset=utf-8",
  ".txt": "text/plain; charset=utf-8",
};

const attachment = (name: string): string => `attachment; filename*=UTF-8''${encodeURIComponent(name)}`;

export async function buildApp(options: AppOptions): Promise<{ app: FastifyInstance; store: Store; jobs: Jobs }> {
  const store = new Store(options.dataDir);
  const jobs = new Jobs(store, options.extract ?? extractText);
  const app = Fastify({ bodyLimit: 16 * 1024 * 1024 });
  await app.register(cors, { origin: options.origins ?? true, methods: ["GET", "POST", "PATCH", "PUT", "DELETE"] });
  await app.register(multipart, { limits: { fileSize: MAX_DOCUMENT_BYTES, files: 200 } });

  app.setErrorHandler((error, _req, reply) => {
    if (error instanceof StoreError) return reply.code(error.status).send({ detail: error.message });
    const status = typeof (error as { statusCode?: number }).statusCode === "number" ? (error as { statusCode: number }).statusCode : 500;
    if (status >= 500) app.log.error(error);
    return reply.code(status).send({ detail: status >= 500 ? "Внутренняя ошибка сервера" : (error as Error).message });
  });

  type Id = { Params: { id: string } };
  type Sid = { Params: { id: string; sid: string } };

  app.get("/catalog", () => ({
    ...store.catalogView(),
    kinds: DOCUMENT_KINDS.map((id) => ({ id, label: KIND_LABELS[id] })),
    limits: { documentBytes: MAX_DOCUMENT_BYTES, extensions: [...EXTENSIONS] },
  }));
  app.post("/catalog/seed", () => seedCatalog(store));
  app.get("/catalog/assignment", () => catalogAssignment(store));
  app.post<{ Body: { crId?: unknown } }>("/catalog/place", (req) => {
    const placed = placeCr(store, req.body?.crId);
    if (placed.created) jobs.add(placed.documentId);
    return placed;
  });

  app.post("/domains", (req) => store.createDomain(req.body));
  app.put<{ Body: { order?: unknown } }>("/domains/order", (req) => {
    store.reorderDomains(req.body?.order);
    return { ok: true };
  });
  app.patch<Id>("/domains/:id", (req) => store.updateDomain(req.params.id, req.body));
  app.delete<Id>("/domains/:id", (req) => {
    store.deleteDomain(req.params.id);
    return { ok: true };
  });
  app.post<Id>("/domains/:id/show-to-agents", (req) => showShelfToAgents(store, req.params.id, options.lukaAgentDir));
  app.post<Id>("/domains/:id/groups", (req) => store.createGroup(req.params.id, req.body));
  app.put<Id & { Body: { order?: unknown } }>("/domains/:id/groups/order", (req) => {
    store.reorderGroups(req.params.id, req.body?.order);
    return { ok: true };
  });
  app.get<Id>("/domains/:id/export", (req, reply) => {
    const domain = store.catalogView().domains.find((candidate) => candidate.id === req.params.id);
    if (!domain) throw new StoreError("Домен не найден", 404);
    return reply.header("content-type", "application/zip").header("content-disposition", attachment(`${domain.name}.okf.zip`)).send(exportZip(store, domain));
  });

  app.patch<Id>("/groups/:id", (req) => store.updateGroup(req.params.id, req.body));
  app.delete<Id>("/groups/:id", (req) => {
    store.deleteGroup(req.params.id);
    return { ok: true };
  });
  app.get<Id>("/groups/:id/documents", (req) => ({ documents: store.documentsOf(req.params.id) }));
  app.get<Id>("/groups/:id/export", (req, reply) => {
    const place = store.findGroup(req.params.id);
    if (!place) throw new StoreError("Группа не найдена", 404);
    return reply.header("content-type", "application/zip").header("content-disposition", attachment(`${place.group.name}.okf.zip`)).send(exportZip(store, place.domain, place.group));
  });

  app.get<Id>("/groups/:id/publication", (req) => publication(req.params.id, options.lukaAgentDir));
  app.post<Id>("/groups/:id/publish", (req) => publishGroup(store, req.params.id, options.lukaAgentDir));
  app.delete<Id>("/groups/:id/publication", (req) => {
    unpublishGroup(store, req.params.id, options.lukaAgentDir);
    return { ok: true };
  });

  app.post<Id>("/groups/:id/documents", async (req) => {
    if (!store.findGroup(req.params.id)) throw new StoreError("Группа не найдена", 404);
    const tmpDir = path.join(store.root, "tmp");
    fs.mkdirSync(tmpDir, { recursive: true, mode: 0o700 });
    const added: unknown[] = [];
    const failed: { name: string; detail: string }[] = [];
    let index = 0;
    for await (const part of req.files()) {
      const tmp = path.join(tmpDir, `${process.pid}-${Date.now()}-${index++}`);
      const name = part.filename || "document";
      try {
        await pipeline(part.file, fs.createWriteStream(tmp, { mode: 0o600 }));
        if (part.file.truncated) throw new StoreError(`Файл больше ${Math.round(MAX_DOCUMENT_BYTES / 1024 / 1024)} МБ`, 413);
        const doc = store.addDocument(req.params.id, tmp, name);
        jobs.add(doc.id);
        added.push(store.doc(doc.id));
      } catch (error) {
        fs.rmSync(tmp, { force: true });
        if (!(error instanceof StoreError)) throw error;
        failed.push({ name, detail: error.message });
      }
    }
    if (!added.length && !failed.length) throw new StoreError("Файлы не получены");
    return { added, failed };
  });

  app.get<Id>("/documents/:id", (req) => store.view(req.params.id));
  app.patch<Id>("/documents/:id", (req) => store.updateDocument(req.params.id, req.body));
  app.delete<Id>("/documents/:id", (req) => {
    store.deleteDocument(req.params.id);
    return { ok: true };
  });
  app.get<Id>("/documents/:id/source", (req, reply) => {
    const doc = store.doc(req.params.id);
    const file = store.sourcePath(doc);
    if (!fs.existsSync(file)) throw new StoreError("Исходный файл не найден", 404);
    const type = MIME[path.extname(doc.sourceName).toLowerCase()] ?? "application/octet-stream";
    return reply
      .header("content-type", type)
      .header("content-disposition", `inline; filename*=UTF-8''${encodeURIComponent(doc.sourceName)}`)
      .header("x-content-type-options", "nosniff")
      .send(fs.createReadStream(file));
  });
  app.get<Id>("/documents/:id/text", (req) => ({ text: store.text(req.params.id) }));
  app.get<Id>("/documents/:id/history", (req) => ({ history: store.history(req.params.id) }));
  app.post<Id>("/documents/:id/reparse", (req) => {
    store.doc(req.params.id);
    jobs.add(req.params.id);
    return store.view(req.params.id);
  });
  app.post<Id>("/documents/:id/resplit", (req) => store.resplit(req.params.id));

  app.patch<Sid>("/documents/:id/sections/:sid", (req) => store.updateSection(req.params.id, req.params.sid, req.body));
  app.post<Sid>("/documents/:id/sections/:sid/split", (req) => store.splitSection(req.params.id, req.params.sid, req.body));
  app.post<Sid>("/documents/:id/sections/:sid/merge", (req) => store.mergeSection(req.params.id, req.params.sid));
  app.delete<Sid>("/documents/:id/sections/:sid", (req) => store.deleteSection(req.params.id, req.params.sid));
  app.patch<{ Params: { id: string; sid: string; n: string } }>("/documents/:id/sections/:sid/recommendations/:n", (req) =>
    store.updateRecommendation(req.params.id, req.params.sid, Number(req.params.n), req.body),
  );

  jobs.resume();
  return { app, store, jobs };
}
