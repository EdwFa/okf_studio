/** Client for the studio server (server/src/app.ts). */

export interface GroupInfo {
  id: string;
  name: string;
  description: string;
  hidden: boolean;
  /** The group this one sits inside; absent at the top level of the domain. */
  parentId?: string;
  documents: number;
  reviewed: number;
  failed: number;
  busy: number;
}

export interface DomainInfo {
  id: string;
  name: string;
  description: string;
  owner: string;
  groups: GroupInfo[];
}

export interface Catalog {
  domains: DomainInfo[];
  kinds: { id: string; label: string }[];
  limits: { documentBytes: number; extensions: string[] };
}

export type DocumentStatus = "draft" | "reviewed" | "published";
export type JobState = "queued" | "processing" | "ready" | "failed";

export interface DocumentMeta {
  id: string;
  groupId: string;
  title: string;
  description: string;
  kind: string;
  sourceName: string;
  origin: string;
  url: string;
  year?: number;
  version: string;
  approvedAt: string;
  reviewDue: string;
  icd10: string[];
  tags: string[];
  status: DocumentStatus;
  job: { state: JobState; error?: string };
  chars: number;
  pages?: number;
  sections: number;
  reviewedSections: number;
  recommendations: number;
  addedAt: string;
  updatedAt: string;
}

export interface Recommendation {
  n: number;
  text: string;
  grade?: string;
  evidence?: string;
  comment?: string;
}

export interface Section {
  id: string;
  number?: string;
  heading: string;
  title: string;
  level: number;
  parentId?: string;
  pageStart?: number;
  pageEnd?: number;
  body: string;
  status: "draft" | "reviewed";
  edited: boolean;
  recommendations: Recommendation[];
}

export interface DocumentView {
  doc: DocumentMeta;
  sections: Section[];
  domain: { id: string; name: string } | null;
  group: { id: string; name: string } | null;
}

export interface HistoryEntry {
  at: string;
  action: string;
  detail?: string;
}

export interface PublishResult {
  published: { id: string; title: string }[];
  kept: { id: string; title: string }[];
  skipped: { id: string; title: string }[];
  removed: number;
  visible: boolean;
}

export function apiBase(): string {
  if (process.env.NEXT_PUBLIC_OKF_API) return process.env.NEXT_PUBLIC_OKF_API;
  const host = typeof window === "undefined" ? "127.0.0.1" : window.location.hostname;
  return `http://${host}:8100`;
}

export class ApiError extends Error {}

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${apiBase()}${path}`, {
      method,
      ...(body instanceof FormData ? { body } : body === undefined ? {} : { body: JSON.stringify(body), headers: { "content-type": "application/json" } }),
    });
  } catch {
    throw new ApiError("Сервер OKF Studio не отвечает. Проверьте, что он запущен.");
  }
  const data = (await res.json().catch(() => ({}))) as { detail?: string };
  if (!res.ok) throw new ApiError(data.detail || `Ошибка ${res.status}`);
  return data as T;
}

export const api = {
  catalog: () => request<Catalog>("GET", "/catalog"),
  createDomain: (body: { name: string; description?: string; owner?: string }) => request<DomainInfo>("POST", "/domains", body),
  updateDomain: (id: string, body: Partial<Pick<DomainInfo, "name" | "description" | "owner">>) => request("PATCH", `/domains/${id}`, body),
  deleteDomain: (id: string) => request("DELETE", `/domains/${id}`),
  reorderDomains: (order: string[]) => request("PUT", "/domains/order", { order }),
  createGroup: (domainId: string, body: { name: string; description?: string; parentId?: string }) => request<GroupInfo>("POST", `/domains/${domainId}/groups`, body),
  updateGroup: (id: string, body: { name?: string; description?: string; hidden?: boolean; parentId?: string; domainId?: string }) => request("PATCH", `/groups/${id}`, body),
  deleteGroup: (id: string) => request("DELETE", `/groups/${id}`),
  reorderGroups: (domainId: string, order: string[]) => request("PUT", `/domains/${domainId}/groups/order`, { order }),
  documents: (groupId: string) => request<{ documents: DocumentMeta[] }>("GET", `/groups/${groupId}/documents`),
  upload: (groupId: string, files: File[]) => {
    const form = new FormData();
    for (const file of files) form.append("files", file, file.name);
    return request<{ added: DocumentMeta[]; failed: { name: string; detail: string }[] }>("POST", `/groups/${groupId}/documents`, form);
  },
  publication: (groupId: string) => request<{ published: boolean; documents: string[] }>("GET", `/groups/${groupId}/publication`),
  publish: (groupId: string) => request<PublishResult>("POST", `/groups/${groupId}/publish`),
  unpublish: (groupId: string) => request("DELETE", `/groups/${groupId}/publication`),
  document: (id: string) => request<DocumentView>("GET", `/documents/${id}`),
  updateDocument: (id: string, body: Record<string, unknown>) => request<DocumentView>("PATCH", `/documents/${id}`, body),
  deleteDocument: (id: string) => request("DELETE", `/documents/${id}`),
  text: (id: string) => request<{ text: string }>("GET", `/documents/${id}/text`),
  history: (id: string) => request<{ history: HistoryEntry[] }>("GET", `/documents/${id}/history`),
  reparse: (id: string) => request<DocumentView>("POST", `/documents/${id}/reparse`),
  resplit: (id: string) => request<DocumentView>("POST", `/documents/${id}/resplit`),
  updateSection: (id: string, sid: string, body: Record<string, unknown>) => request<DocumentView>("PATCH", `/documents/${id}/sections/${sid}`, body),
  splitSection: (id: string, sid: string, body: { offset: number; heading: string; number?: string }) => request<DocumentView>("POST", `/documents/${id}/sections/${sid}/split`, body),
  mergeSection: (id: string, sid: string) => request<DocumentView>("POST", `/documents/${id}/sections/${sid}/merge`),
  deleteSection: (id: string, sid: string) => request<DocumentView>("DELETE", `/documents/${id}/sections/${sid}`),
  updateRecommendation: (id: string, sid: string, n: number, body: Record<string, unknown>) => request<DocumentView>("PATCH", `/documents/${id}/sections/${sid}/recommendations/${n}`, body),
  sourceUrl: (id: string) => `${apiBase()}/documents/${id}/source`,
  exportDomainUrl: (id: string) => `${apiBase()}/domains/${id}/export`,
  exportGroupUrl: (id: string) => `${apiBase()}/groups/${id}/export`,
};

export const STATUS_LABEL: Record<DocumentStatus, string> = { draft: "Черновик", reviewed: "Проверено", published: "Опубликовано" };
export const JOB_LABEL: Record<JobState, string> = { queued: "В очереди", processing: "Разбирается…", ready: "Готов", failed: "Ошибка разбора" };

/** Groups of a domain in tree order (a group, then everything nested in it), with their depth. */
export function groupTree(groups: GroupInfo[]): { group: GroupInfo; depth: number }[] {
  const out: { group: GroupInfo; depth: number }[] = [];
  const walk = (parentId: string | undefined, depth: number) => {
    for (const group of groups) {
      if (group.parentId !== parentId) continue;
      out.push({ group, depth });
      walk(group.id, depth + 1);
    }
  };
  walk(undefined, 0);
  return out;
}

/** The group and its ancestors, top first. */
export function groupTrail(groups: GroupInfo[], id: string): GroupInfo[] {
  const byId = new Map(groups.map((group) => [group.id, group]));
  const trail: GroupInfo[] = [];
  for (let at = byId.get(id); at && !trail.includes(at); at = at.parentId ? byId.get(at.parentId) : undefined) trail.unshift(at);
  return trail;
}
