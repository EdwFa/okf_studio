"use client";

import { ArrowDown, ArrowUp, ChevronDown, ChevronRight, ChevronUp, Download, Folder, Eye, EyeOff, FolderPlus, ListTree, PanelLeftClose, PanelLeftOpen, Pencil, Plus, ScanText, Send, Trash2, Upload } from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ConfirmDialog, ErrorBanner, FormDialog, Modal, StatusBadge } from "@/components/ui";
import { useStoredFlag } from "@/lib/use-stored-flag";
import { api, groupTrail, groupTree, type Catalog, type DocumentMeta, type DomainInfo, type GroupInfo, type PublishResult } from "@/lib/api";

type Dialog =
  | { kind: "newDomain" }
  | { kind: "editDomain"; domain: DomainInfo }
  | { kind: "deleteDomain"; domain: DomainInfo }
  | { kind: "newGroup"; domain: DomainInfo; parentId?: string }
  | { kind: "editGroup"; group: GroupInfo; domain: DomainInfo }
  | { kind: "deleteGroup"; group: GroupInfo; domain: DomainInfo }
  | { kind: "deleteDoc"; doc: DocumentMeta }
  | { kind: "publish"; group: GroupInfo }
  | { kind: "showShelf"; domain: DomainInfo }
  | { kind: "published"; result: PublishResult }
  | { kind: "unpublish"; group: GroupInfo }
  | null;

type SortKey = "title" | "kind" | "year" | "icd10" | "sections" | "recommendations" | "status";
const COLUMNS: { key: SortKey; label: string }[] = [
  { key: "title", label: "Документ" },
  { key: "kind", label: "Тип" },
  { key: "year", label: "Год" },
  { key: "icd10", label: "МКБ-10" },
  { key: "sections", label: "Разделы" },
  { key: "recommendations", label: "Рекомендаций" },
  { key: "status", label: "Статус" },
];
/** Ошибки и разбор — сверху, затем черновики, проверенные, опубликованные. */
const statusRank = (doc: DocumentMeta): number =>
  doc.job.state === "failed" ? 0 : doc.job.state !== "ready" ? 1 : doc.status === "draft" ? 2 : doc.status === "reviewed" ? 3 : 4;

/** Groups a group may be placed into: every group of the domain except itself and what is nested in it. */
function parentOptions(domain: DomainInfo, except?: string): { value: string; label: string }[] {
  const options = [{ value: "", label: "— верхний уровень домена —" }];
  let skipDepth = -1;
  for (const { group, depth } of groupTree(domain.groups)) {
    if (skipDepth >= 0 && depth > skipDepth) continue;
    skipDepth = -1;
    if (group.id === except) {
      skipDepth = depth;
      continue;
    }
    options.push({ value: group.id, label: `${"\u00A0\u00A0\u00A0".repeat(depth)}${group.name}` });
  }
  return options;
}

/** The full order of a domain's groups after moving one among its siblings. */
function reordered(groups: GroupInfo[], id: string, delta: number): string[] {
  const ids = groups.map((group) => group.id);
  const group = groups.find((candidate) => candidate.id === id);
  const siblings = groups.filter((candidate) => candidate.parentId === group?.parentId);
  const other = siblings[siblings.findIndex((candidate) => candidate.id === id) + delta];
  if (!group || !other) return ids;
  const [a, b] = [ids.indexOf(id), ids.indexOf(other.id)];
  [ids[a], ids[b]] = [ids[b]!, ids[a]!];
  return ids;
}

function Home() {
  const router = useRouter();
  const params = useSearchParams();
  const groupId = params.get("g");
  const domainId = params.get("d");
  const [catalog, setCatalog] = useState<Catalog | null>(null);
  const [docs, setDocs] = useState<DocumentMeta[]>([]);
  const [inLuka, setInLuka] = useState<{ published: boolean; documents: string[] }>({ published: false, documents: [] });
  const [error, setError] = useState("");
  const [dialog, setDialog] = useState<Dialog>(null);
  const [uploading, setUploading] = useState(false);
  const [collapsed, setCollapsed] = useStoredFlag("okf-studio.sidebar-collapsed");
  const [sort, setSort] = useState<{ key: SortKey; desc: boolean }>({ key: "title", desc: false });
  const [dragging, setDragging] = useState(false);
  const [seeding, setSeeding] = useState(false);
  const [notice, setNotice] = useState("");
  const [closed, setClosed] = useState<Set<string>>(new Set());
  const toggle = (id: string) => setClosed((current) => {
    const next = new Set(current);
    if (!next.delete(id)) next.add(id);
    return next;
  });
  const fileInput = useRef<HTMLInputElement>(null);

  const refresh = useCallback(async () => {
    try {
      const next = await api.catalog();
      setCatalog(next);
      if (groupId && next.domains.some((domain) => domain.groups.some((group) => group.id === groupId))) {
        setDocs((await api.documents(groupId)).documents);
        setInLuka(await api.publication(groupId));
      } else {
        setDocs([]);
        setInLuka({ published: false, documents: [] });
      }
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc));
    }
  }, [groupId]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  // While documents are being parsed, keep the list fresh.
  const busy = docs.some((doc) => doc.job.state === "queued" || doc.job.state === "processing");
  useEffect(() => {
    if (!busy) return;
    const timer = setInterval(() => void refresh(), 1500);
    return () => clearInterval(timer);
  }, [busy, refresh]);

  const fillFromClassifier = async () => {
    setSeeding(true);
    setError("");
    try {
      const result = await api.seedCatalog();
      const created = result.created.domains + result.created.groups;
      setNotice(
        created
          ? `Создано доменов: ${result.created.domains}, групп: ${result.created.groups}. Группы скрыты от агентов, пока полку не покажут.`
          : `Каталог уже заполнен: ${result.existing.domains} доменов и ${result.existing.groups} групп. Повторное заполнение ничего не дублирует.`,
      );
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc));
    }
    setSeeding(false);
    await refresh();
  };

  const run = async (action: () => Promise<unknown>) => {
    setError("");
    try {
      await action();
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc));
    }
    await refresh();
  };

  const domains = catalog?.domains ?? [];
  const groupDomain = domains.find((domain) => domain.groups.some((group) => group.id === groupId));
  const group = groupDomain?.groups.find((candidate) => candidate.id === groupId);
  const domain = groupDomain ?? domains.find((candidate) => candidate.id === domainId);
  const kindLabel = (id: string) => catalog?.kinds.find((kind) => kind.id === id)?.label ?? id;
  const trail = domain && group ? groupTrail(domain.groups, group.id) : [];
  const subgroups = domain && group ? domain.groups.filter((candidate) => candidate.parentId === group.id) : [];
  const siblingCount = (item: GroupInfo) => (domain ? domain.groups.filter((candidate) => candidate.parentId === item.parentId) : []);

  const sortedDocs = useMemo(() => {
    const kinds = new Map(catalog?.kinds.map((kind) => [kind.id, kind.label]));
    const value = (doc: DocumentMeta): string | number | undefined => {
      switch (sort.key) {
        case "title": return doc.title;
        case "kind": return kinds.get(doc.kind) ?? doc.kind;
        case "year": return doc.year;
        case "icd10": return doc.icd10.join(", ") || undefined;
        case "sections": return doc.job.state === "ready" ? doc.sections : undefined;
        case "recommendations": return doc.job.state === "ready" ? doc.recommendations : undefined;
        case "status": return statusRank(doc);
      }
    };
    return [...docs].sort((a, b) => {
      const [x, y] = [value(a), value(b)];
      // Пустые значения всегда внизу, в какую бы сторону ни шла сортировка.
      if (x === undefined || y === undefined) return x === y ? a.title.localeCompare(b.title, "ru") : x === undefined ? 1 : -1;
      const order = typeof x === "number" && typeof y === "number" ? x - y : String(x).localeCompare(String(y), "ru", { numeric: true });
      return (sort.desc ? -order : order) || a.title.localeCompare(b.title, "ru");
    });
  }, [docs, sort, catalog]);

  const upload = async (files: File[]) => {
    if (!group || !files.length) return;
    setUploading(true);
    await run(async () => {
      const result = await api.upload(group.id, files);
      if (result.failed.length) throw new Error(result.failed.map((item) => `${item.name}: ${item.detail}`).join("\n"));
    });
    setUploading(false);
  };

  return (
    <div className="flex h-screen">
      {collapsed && (
        <aside className="flex w-11 shrink-0 flex-col items-center border-r py-3" style={{ borderColor: "var(--line)", background: "var(--panel)" }}>
          <Link href="/nosology" className="btn btn-ghost" aria-label="Классификатор" data-tip="Классификатор" data-tip-side="right"><ListTree size={16} /></Link>
          <Link href="/parse" className="btn btn-ghost" aria-label="Разбор PDF" data-tip="Разбор PDF" data-tip-side="right"><ScanText size={16} /></Link>
          <button className="btn btn-ghost" onClick={() => setCollapsed(false)} aria-label="Развернуть панель доменов" data-tip="Развернуть" data-tip-side="right"><PanelLeftOpen size={16} /></button>
        </aside>
      )}
      <aside hidden={collapsed} className={`${collapsed ? "" : "flex"} w-72 shrink-0 flex-col border-r`} style={{ borderColor: "var(--line)", background: "var(--panel)" }}>
        <div className="flex items-center justify-between gap-2 py-3 pl-4 pr-2">
          <Link href="/" className="text-base font-semibold">OKF Studio</Link>
          <span className="flex items-center gap-1">
            <button className="btn btn-ghost" onClick={() => setDialog({ kind: "newDomain" })} aria-label="Создать домен" data-tip="Создать домен"><Plus size={16} /></button>
            <button className="btn btn-ghost" onClick={() => setCollapsed(true)} aria-label="Свернуть панель доменов" data-tip="Свернуть" data-tip-side="left"><PanelLeftClose size={16} /></button>
          </span>
        </div>
        <div className="px-2 pb-2">
          <Link href="/nosology" className="row-hover flex items-center gap-2 rounded-md px-2 py-1.5 text-sm">
            <ListTree size={15} /> Классификатор
          </Link>
          <Link href="/parse" className="row-hover flex items-center gap-2 rounded-md px-2 py-1.5 text-sm">
            <ScanText size={15} /> Разбор PDF
          </Link>
          <button className="btn mt-1 w-full justify-start text-left" style={{ whiteSpace: "normal" }} disabled={seeding} onClick={() => void fillFromClassifier()}>
            {seeding ? "Заполняю…" : "Заполнить из классификатора"}
          </button>
        </div>
        <nav className="flex-1 overflow-y-auto px-2 pb-4" aria-label="Домены и группы">
          {catalog && !domains.length && <p className="muted px-2 py-3 text-sm">Доменов пока нет. Создайте первый — например, «Онкология головы и шеи».</p>}
          {domains.map((item) => (
            <div key={item.id} className="mb-2">
              <Link href={`/?d=${item.id}`} className={`row-hover block rounded-md px-2 py-1.5 font-medium ${!group && domain?.id === item.id ? "row-active" : ""}`}>
                {item.name}
              </Link>
              {(() => {
                // A closed group hides everything nested in it.
                let hideBelow = -1;
                return groupTree(item.groups).map(({ group: child, depth }) => {
                  if (hideBelow >= 0 && depth > hideBelow) return null;
                  hideBelow = closed.has(child.id) ? depth : -1;
                  const hasChildren = item.groups.some((candidate) => candidate.parentId === child.id);
                  return (
                    <div key={child.id} className={`row-hover flex items-center rounded-md ${child.id === groupId ? "row-active" : ""}`} style={{ marginLeft: 8 + depth * 14 }}>
                      {hasChildren ? (
                        <button className="shrink-0 p-1" onClick={() => toggle(child.id)} aria-label={closed.has(child.id) ? `Развернуть «${child.name}»` : `Свернуть «${child.name}»`} aria-expanded={!closed.has(child.id)}>
                          {closed.has(child.id) ? <ChevronRight size={14} /> : <ChevronDown size={14} />}
                        </button>
                      ) : (
                        <span className="w-[22px] shrink-0" />
                      )}
                      <Link href={`/?g=${child.id}`} className="flex min-w-0 flex-1 items-center justify-between gap-2 py-1 pr-2">
                        <span className="truncate">{child.name}</span>
                        <span className="muted flex shrink-0 items-center gap-1 text-xs">
                          {child.hidden && <EyeOff size={12} aria-label="скрыта" />}
                          {child.documents}
                        </span>
                      </Link>
                    </div>
                  );
                });
              })()}
              {!item.groups.length && <p className="muted ml-5 py-1 text-xs">нет групп</p>}
            </div>
          ))}
        </nav>
      </aside>

      <main className="min-w-0 flex-1 overflow-y-auto p-6">
        <ErrorBanner message={error} onClose={() => setError("")} />
        {notice && <p className="mb-3 text-sm">{notice}</p>}

        {catalog && !domain && (
          <div className="panel mx-auto mt-16 max-w-xl p-8 text-center">
            <h1 className="mb-2 text-lg font-semibold">Базы знаний в формате OKF</h1>
            <p className="muted mb-5">
              Домен — область знаний. В домене — группы документов, в группе — документы: клинические рекомендации, стандарты, статьи.
              Документ после загрузки разбивается на разделы, которые можно проверить и поправить.
            </p>
            <div className="flex flex-wrap justify-center gap-2">
              <button className="btn btn-primary" onClick={() => setDialog({ kind: "newDomain" })}><Plus size={14} /> Создать домен</button>
              <button className="btn" disabled={seeding} onClick={() => void fillFromClassifier()}>{seeding ? "Заполняю…" : "Заполнить из классификатора"}</button>
            </div>
            <p className="muted mt-4 text-sm">Группы из классификатора скрыты от агентов, пока полку не покажут.</p>
          </div>
        )}

        {domain && !group && (
          <section>
            <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
              <div>
                <h1 className="text-xl font-semibold">{domain.name}</h1>
                <p className="muted mt-1">{domain.description || "Описание не задано"}{domain.owner ? ` · Ответственный: ${domain.owner}` : ""}</p>
              </div>
              <div className="flex flex-wrap gap-2">
                <button className="btn" onClick={() => setDialog({ kind: "editDomain", domain })}><Pencil size={14} /> Изменить</button>
                {domain.catalogKey && <button className="btn btn-primary" onClick={() => setDialog({ kind: "showShelf", domain })}>Показать агентам только эту полку</button>}
                <a className="btn" href={api.exportDomainUrl(domain.id)}><Download size={14} /> Выгрузить OKF</a>
                <button className="btn btn-danger" onClick={() => setDialog({ kind: "deleteDomain", domain })}><Trash2 size={14} /> Удалить</button>
              </div>
            </div>
            <div className="panel">
              <div className="flex items-center justify-between px-4 py-3">
                <h2 className="font-medium">Группы документов</h2>
                <button className="btn btn-primary" onClick={() => setDialog({ kind: "newGroup", domain })}><FolderPlus size={14} /> Группа</button>
              </div>
              {!domain.groups.length ? (
                <p className="muted px-4 pb-4">Групп пока нет. Группа — папка с документами одной темы; в группе могут быть подгруппы. Агенты Луки получают каждую группу с документами как один навык.</p>
              ) : (
                <table className="grid-table">
                  <thead><tr><th>Группа</th><th>Документов</th><th>Проверено</th><th>Агентам</th><th className="w-24">Порядок</th></tr></thead>
                  <tbody>
                    {groupTree(domain.groups).map(({ group: item, depth }) => (
                      <tr key={item.id}>
                        <td style={{ paddingLeft: 10 + depth * 22 }}><Link className="font-medium hover:underline" href={`/?g=${item.id}`}>{item.name}</Link>{item.description && <div className="muted text-xs">{item.description}</div>}</td>
                        <td>{item.documents}{item.failed > 0 && <span className="badge badge-bad ml-2">ошибок: {item.failed}</span>}</td>
                        <td>{item.reviewed} из {item.documents}</td>
                        <td>{item.hidden ? <span className="badge">скрыта</span> : <span className="badge badge-ok">видна</span>}</td>
                        <td>
                          <button className="btn btn-ghost" aria-label="Выше" disabled={siblingCount(item)[0]?.id === item.id} onClick={() => run(() => api.reorderGroups(domain.id, reordered(domain.groups, item.id, -1)))}><ChevronUp size={14} /></button>
                          <button className="btn btn-ghost" aria-label="Ниже" disabled={siblingCount(item).at(-1)?.id === item.id} onClick={() => run(() => api.reorderGroups(domain.id, reordered(domain.groups, item.id, 1)))}><ChevronDown size={14} /></button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          </section>
        )}

        {domain && group && (
          <section
            onDragOver={(event) => {
              event.preventDefault();
              setDragging(true);
            }}
            onDragLeave={() => setDragging(false)}
            onDrop={(event) => {
              event.preventDefault();
              setDragging(false);
              void upload([...event.dataTransfer.files]);
            }}
          >
            <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
              <div>
                <p className="muted text-xs">
                  <Link className="hover:underline" href={`/?d=${domain.id}`}>{domain.name}</Link> /
                  {trail.slice(0, -1).map((item) => <span key={item.id}> <Link className="hover:underline" href={`/?g=${item.id}`}>{item.name}</Link> /</span>)}
                </p>
                <h1 className="text-xl font-semibold">{group.name}</h1>
                <p className="muted mt-1">{group.description || "Описание не задано"}</p>
              </div>
              <div className="flex flex-wrap gap-2">
                <button className="btn btn-primary" disabled={uploading} onClick={() => fileInput.current?.click()} aria-label="Загрузить документы" data-tip={uploading ? "Загрузка…" : "Загрузить документы"}><Upload size={16} /></button>
                <input ref={fileInput} type="file" multiple hidden accept={catalog?.limits.extensions.join(",")} onChange={(event) => { void upload([...(event.target.files ?? [])]); event.target.value = ""; }} />
                <button className="btn" onClick={() => setDialog({ kind: "newGroup", domain, parentId: group.id })} aria-label="Создать подгруппу" data-tip="Подгруппа"><FolderPlus size={16} /></button>
                <button className="btn" onClick={() => setDialog({ kind: "editGroup", group, domain })} aria-label="Изменить группу" data-tip="Изменить"><Pencil size={16} /></button>
                <button className="btn" onClick={() => run(() => api.updateGroup(group.id, { hidden: !group.hidden }))} aria-label={group.hidden ? "Показать агентам" : "Скрыть от агентов"} data-tip={group.hidden ? "Показать агентам" : "Скрыть от агентов"}>
                  {group.hidden ? <Eye size={16} /> : <EyeOff size={16} />}
                </button>
                <a className="btn" href={api.exportGroupUrl(group.id)} aria-label="Выгрузить OKF" data-tip="Выгрузить OKF"><Download size={16} /></a>
                <button className="btn" onClick={() => setDialog({ kind: "publish", group })} aria-label="Опубликовать в Луку" data-tip="Опубликовать в Луку"><Send size={16} /></button>
                <button className="btn btn-danger" onClick={() => setDialog({ kind: "deleteGroup", group, domain })} aria-label="Удалить группу" data-tip="Удалить" data-tip-side="left"><Trash2 size={16} /></button>
              </div>
            </div>
            {subgroups.length > 0 && (
              <div className="mb-3 flex flex-wrap gap-2" aria-label="Подгруппы">
                {subgroups.map((item) => (
                  <Link key={item.id} href={`/?g=${item.id}`} className="btn"><Folder size={14} /> {item.name} <span className="muted text-xs">{item.documents}</span></Link>
                ))}
              </div>
            )}
            <p className="mb-3 text-sm">
              {inLuka.published ? (
                <>
                  <span className="badge badge-ok mr-2">В Луке: {inLuka.documents.length} документов</span>
                  {group.hidden ? "Группа скрыта — после следующей публикации агенты перестанут её видеть." : "Агенты Луки видят опубликованную версию в новых чатах."}{" "}
                  Правки и удаления попадут в Луку после новой публикации.{" "}
                  <button className="underline" onClick={() => setDialog({ kind: "unpublish", group })}>Снять с публикации</button>
                </>
              ) : (
                <span className="muted">Группа ещё не опубликована в Луке: агенты её не видят.</span>
              )}
            </p>
            <div className="panel" style={dragging ? { outline: "2px dashed var(--accent)" } : undefined}>
              {!docs.length ? (
                <p className="muted p-8 text-center">Документов пока нет. Перетащите сюда файлы или нажмите «Загрузить документы».<br />Подходят: {catalog?.limits.extensions.join(", ")}</p>
              ) : (
                <table className="grid-table">
                  <thead>
                    <tr>
                      {COLUMNS.map((column) => {
                        const active = sort.key === column.key;
                        return (
                          <th key={column.key} aria-sort={active ? (sort.desc ? "descending" : "ascending") : "none"}>
                            <button
                              className="inline-flex items-center gap-1 hover:underline"
                              style={active ? { color: "var(--text)" } : undefined}
                              title="Сортировать по этому столбцу"
                              onClick={() => setSort({ key: column.key, desc: active ? !sort.desc : false })}
                            >
                              {column.label}
                              {active && (sort.desc ? <ArrowDown size={12} /> : <ArrowUp size={12} />)}
                            </button>
                          </th>
                        );
                      })}
                      <th />
                    </tr>
                  </thead>
                  <tbody>
                    {sortedDocs.map((doc) => (
                      <tr key={doc.id}>
                        <td className="max-w-md">
                          <Link className="font-medium hover:underline" href={`/doc?id=${doc.id}`}>{doc.title}</Link>
                          <div className="muted truncate text-xs">{doc.job.state === "failed" ? doc.job.error : doc.sourceName}</div>
                        </td>
                        <td>{kindLabel(doc.kind)}</td>
                        <td>{doc.year ?? "—"}</td>
                        <td>{doc.icd10.join(", ") || "—"}</td>
                        <td>{doc.job.state === "ready" ? `${doc.reviewedSections} из ${doc.sections} проверено` : "—"}</td>
                        <td>{doc.job.state === "ready" ? doc.recommendations : "—"}</td>
                        <td>
                          <StatusBadge doc={doc} />
                          {doc.status === "draft" && inLuka.documents.includes(doc.id) && <div className="muted mt-1 text-xs">в Луке — прежняя версия</div>}
                        </td>
                        <td><button className="btn btn-ghost btn-danger" aria-label={`Удалить ${doc.title}`} onClick={() => setDialog({ kind: "deleteDoc", doc })}><Trash2 size={14} /></button></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          </section>
        )}
      </main>

      {dialog?.kind === "newDomain" && (
        <FormDialog
          title="Новый домен"
          submitLabel="Создать"
          fields={[{ name: "name", label: "Название", placeholder: "Онкология головы и шеи" }, { name: "description", label: "Описание", multiline: true }, { name: "owner", label: "Ответственный" }]}
          onClose={() => setDialog(null)}
          onSubmit={async (values) => {
            const created = await api.createDomain({ name: values.name!, description: values.description, owner: values.owner });
            await refresh();
            router.push(`/?d=${created.id}`);
          }}
        />
      )}
      {dialog?.kind === "editDomain" && (
        <FormDialog
          title="Домен"
          fields={[{ name: "name", label: "Название", value: dialog.domain.name }, { name: "description", label: "Описание", value: dialog.domain.description, multiline: true }, { name: "owner", label: "Ответственный", value: dialog.domain.owner }]}
          onClose={() => setDialog(null)}
          onSubmit={async (values) => {
            await api.updateDomain(dialog.domain.id, values);
            await refresh();
          }}
        />
      )}
      {dialog?.kind === "showShelf" && (
        <ConfirmDialog
          title="Показать агентам только эту полку?"
          text={`Группы полки «${dialog.domain.name}» станут видны. Остальные полки каталога агенты перестанут видеть после публикации. Группы без ключа каталога не изменятся. Черновики в навык не попадут.`}
          confirmLabel="Показать"
          onClose={() => setDialog(null)}
          onConfirm={async () => {
            const result = await api.showToAgents(dialog.domain.id);
            setNotice(`Опубликовано групп: ${result.published}. Снято с публикации: ${result.unpublished}. Черновиков на этой полке: ${result.drafts}.`);
            await refresh();
          }}
        />
      )}
      {dialog?.kind === "deleteDomain" && (
        <ConfirmDialog
          title="Удалить домен?"
          text={`Домен «${dialog.domain.name}» будет удалён. Это возможно, только если в нём нет групп.`}
          confirmLabel="Удалить"
          danger
          onClose={() => setDialog(null)}
          onConfirm={async () => {
            await api.deleteDomain(dialog.domain.id);
            await refresh();
            router.push("/");
          }}
        />
      )}
      {dialog?.kind === "newGroup" && (
        <FormDialog
          title={`Новая группа в домене «${dialog.domain.name}»`}
          submitLabel="Создать"
          fields={[
            { name: "name", label: "Название", placeholder: "Клинические рекомендации Минздрава" },
            { name: "parentId", label: "Входит в группу", value: dialog.parentId ?? "", options: parentOptions(dialog.domain) },
            { name: "description", label: "Описание", multiline: true },
          ]}
          onClose={() => setDialog(null)}
          onSubmit={async (values) => {
            const created = await api.createGroup(dialog.domain.id, { name: values.name!, description: values.description, parentId: values.parentId });
            await refresh();
            router.push(`/?g=${created.id}`);
          }}
        />
      )}
      {dialog?.kind === "editGroup" && (
        <FormDialog
          title="Группа"
          fields={[
            { name: "name", label: "Название", value: dialog.group.name },
            { name: "parentId", label: "Входит в группу", value: dialog.group.parentId ?? "", options: parentOptions(dialog.domain, dialog.group.id), hint: "Подгруппы и документы переносятся вместе с группой." },
            { name: "description", label: "Описание", value: dialog.group.description, multiline: true },
          ]}
          onClose={() => setDialog(null)}
          onSubmit={async (values) => {
            await api.updateGroup(dialog.group.id, values);
            await refresh();
          }}
        />
      )}
      {dialog?.kind === "deleteGroup" && (
        <ConfirmDialog
          title="Удалить группу?"
          text={`Группа «${dialog.group.name}» будет удалена. Это возможно, только если в ней нет документов и подгрупп.`}
          confirmLabel="Удалить"
          danger
          onClose={() => setDialog(null)}
          onConfirm={async () => {
            await api.deleteGroup(dialog.group.id);
            await refresh();
            router.push(dialog.group.parentId ? `/?g=${dialog.group.parentId}` : `/?d=${dialog.domain.id}`);
          }}
        />
      )}
      {dialog?.kind === "publish" && (
        <ConfirmDialog
          title="Опубликовать группу в Луку?"
          text={(() => {
            const ready = docs.filter((doc) => doc.job.state === "ready" && doc.status !== "draft").length;
            const drafts = docs.length - ready;
            return `В базу знаний Луки попадут документы со статусом «проверено» или «опубликовано»: ${ready} из ${docs.length}.${drafts ? ` Черновики (${drafts}) не публикуются; если черновик был опубликован раньше, в Луке останется прежняя версия.` : ""}${group?.hidden ? " Группа скрыта от агентов: файлы будут записаны, но агенты её не увидят." : " Агенты увидят изменения в новых чатах."}`;
          })()}
          confirmLabel="Опубликовать"
          onClose={() => setDialog(null)}
          onConfirm={async () => {
            const result = await api.publish(dialog.group.id);
            await refresh();
            setTimeout(() => setDialog({ kind: "published", result }), 0);
          }}
        />
      )}
      {dialog?.kind === "published" && (
        <Modal title="Группа опубликована в Луку" onClose={() => setDialog(null)}>
          <ul className="mb-4 space-y-1 text-sm">
            <li>Опубликовано документов: {dialog.result.published.length}</li>
            {dialog.result.kept.length > 0 && <li>Оставлена прежняя версия (сейчас черновики): {dialog.result.kept.map((doc) => doc.title).join("; ")}</li>}
            {dialog.result.skipped.length > 0 && <li>Не опубликованы (не проверены): {dialog.result.skipped.map((doc) => doc.title).join("; ")}</li>}
            {dialog.result.removed > 0 && <li>Убрано из Луки: {dialog.result.removed}</li>}
            <li>{dialog.result.visible ? "Агенты Луки увидят группу в новых чатах." : "Агенты группу не видят: она скрыта или в ней нет опубликованных документов."}</li>
          </ul>
          <div className="flex justify-end"><button className="btn btn-primary" onClick={() => setDialog(null)}>Понятно</button></div>
        </Modal>
      )}
      {dialog?.kind === "unpublish" && (
        <ConfirmDialog
          title="Снять группу с публикации?"
          text={`Группа «${dialog.group.name}» будет удалена из базы знаний Луки, агенты перестанут её видеть. Здесь, в OKF Studio, документы и правки останутся.`}
          confirmLabel="Снять с публикации"
          danger
          onClose={() => setDialog(null)}
          onConfirm={async () => {
            await api.unpublish(dialog.group.id);
            await refresh();
          }}
        />
      )}
      {dialog?.kind === "deleteDoc" && (
        <ConfirmDialog
          title="Удалить документ?"
          text={`«${dialog.doc.title}» будет удалён вместе с исходным файлом, разделами и всеми правками. Вернуть его будет нельзя.`}
          confirmLabel="Удалить навсегда"
          danger
          onClose={() => setDialog(null)}
          onConfirm={async () => {
            await api.deleteDocument(dialog.doc.id);
            await refresh();
          }}
        />
      )}
    </div>
  );
}

export default function Page() {
  return (
    <Suspense>
      <Home />
    </Suspense>
  );
}
