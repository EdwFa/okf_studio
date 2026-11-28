/**
 * Shows one classifier shelf to agents and hides the others.
 * Groups without a catalogKey are left as they are, including their publication.
 */
import fs from "node:fs";
import { publication, publishGroup, unpublishGroup } from "../publish.ts";
import { Store, StoreError } from "../store.ts";

export interface ShowShelfResult {
  /** Groups of this shelf whose skill was written. */
  published: number;
  /** Groups of other shelves whose skill was removed. */
  unpublished: number;
  /** Draft documents on this shelf. They stay in the studio and out of the skill. */
  drafts: number;
}

export function showShelfToAgents(store: Store, domainId: string, agentDir: string): ShowShelfResult {
  const catalog = store.catalogView().domains;
  const domain = catalog.find((item) => item.id === domainId);
  if (!domain) throw new StoreError("Домен не найден", 404);
  if (!domain.catalogKey) throw new StoreError("Это не полка каталога. Ручной домен эта команда не меняет.", 409);
  if (!fs.existsSync(agentDir)) throw new StoreError(`Не найдена папка Луки: ${agentDir}`, 409);

  const shown: string[] = [];
  const concealed: string[] = [];
  const updates: { id: string; hidden: boolean }[] = [];
  for (const item of catalog) {
    for (const group of item.groups) {
      if (!group.catalogKey) continue;
      const hidden = item.id !== domain.id;
      if (group.hidden !== hidden) updates.push({ id: group.id, hidden });
      (hidden ? concealed : shown).push(group.id);
    }
  }
  store.setHidden(updates);

  let published = 0;
  let drafts = 0;
  for (const id of shown) {
    const docs = store.documentsOf(id);
    drafts += docs.filter((doc) => doc.status === "draft").length;
    const ready = docs.some((doc) => doc.job.state === "ready" && doc.status !== "draft");
    const wasPublished = publication(id, agentDir).published;
    if (!ready && !wasPublished) continue;
    if (publishGroup(store, id, agentDir).visible) published += 1;
  }
  let unpublished = 0;
  for (const id of concealed) {
    if (!publication(id, agentDir).published) continue;
    unpublishGroup(store, id, agentDir);
    unpublished += 1;
  }
  return { published, unpublished, drafts };
}
