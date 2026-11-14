"use client";

import { ArrowLeft, Check, CheckCheck, FileText, History, Merge, PanelLeftClose, PanelLeftOpen, PanelRightClose, PanelRightOpen, RotateCcw, Scissors, Trash2 } from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ConfirmDialog, ErrorBanner, FormDialog, Modal, StatusBadge } from "@/components/ui";
import { useStoredFlag } from "@/lib/use-stored-flag";
import { api, groupTree, JOB_LABEL, type Catalog, type DocumentMeta, type DocumentView, type HistoryEntry, type Section } from "@/lib/api";

interface Draft {
  number: string;
  heading: string;
  parentId: string;
  body: string;
}

const draftOf = (section: Section): Draft => ({ number: section.number ?? "", heading: section.heading, parentId: section.parentId ?? "", body: section.body });
const sameDraft = (a: Draft, b: Draft) => a.number === b.number && a.heading === b.heading && a.parentId === b.parentId && a.body === b.body;
const pages = (section: Section) => (section.pageStart === undefined ? "" : section.pageStart === section.pageEnd || section.pageEnd === undefined ? `стр. ${section.pageStart}` : `стр. ${section.pageStart}–${section.pageEnd}`);

type Dialog =
  | { kind: "card" }
  | { kind: "history" }
  | { kind: "split"; offset: number }
  | { kind: "merge" }
  | { kind: "deleteSection" }
  | { kind: "resplit" }
  | { kind: "deleteDoc" }
  | { kind: "leave"; to: string }
  | null;

function DocumentPage() {
  const router = useRouter();
  const id = useSearchParams().get("id") ?? "";
  const [view, setView] = useState<DocumentView | null>(null);
  const [catalog, setCatalog] = useState<Catalog | null>(null);
  const [selectedId, setSelectedId] = useState("");
  const [draft, setDraft] = useState<Draft | null>(null);
  const [tab, setTab] = useState<"sections" | "recs">("sections");
  const [showSource, setShowSource] = useState(true);
  const [listCollapsed, setListCollapsed] = useStoredFlag("okf-studio.sections-collapsed");
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  const [dialog, setDialog] = useState<Dialog>(null);
  const textarea = useRef<HTMLTextAreaElement>(null);

  const load = useCallback(async () => {
    try {
      setView(await api.document(id));
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc));
    }
  }, [id]);

  useEffect(() => {
    void load();
    api.catalog().then(setCatalog).catch(() => undefined);
  }, [load]);

  const parsing = view ? view.doc.job.state === "queued" || view.doc.job.state === "processing" : false;
  useEffect(() => {
    if (!parsing) return;
    const timer = setInterval(() => void load(), 1500);
    return () => clearInterval(timer);
  }, [parsing, load]);

  const sections = useMemo(() => view?.sections ?? [], [view]);
  const selected = sections.find((section) => section.id === selectedId) ?? sections[0];
  const selectedIndex = selected ? sections.indexOf(selected) : -1;

  // The editor follows the saved section; unsaved edits are guarded by `dirty` before anything replaces them.
  useEffect(() => {
    setDraft(selected ? draftOf(selected) : null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selected?.id, selected?.body, selected?.heading, selected?.number, selected?.parentId]);

  const dirty = Boolean(selected && draft && !sameDraft(draft, draftOf(selected)));

  useEffect(() => {
    if (!dirty) return;
    const warn = (event: BeforeUnloadEvent) => event.preventDefault();
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty]);

  const apply = async (action: () => Promise<DocumentView>): Promise<boolean> => {
    setError("");
    setSaving(true);
    try {
      setView(await action());
      return true;
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc));
      return false;
    } finally {
      setSaving(false);
    }
  };

  const select = (sectionId: string) => {
    if (sectionId === selected?.id) return;
    if (dirty) setDialog({ kind: "leave", to: sectionId });
    else setSelectedId(sectionId);
  };

  const save = () => (selected && draft ? apply(() => api.updateSection(id, selected.id, { ...draft })) : Promise.resolve(false));

  const markSelection = () => {
    const area = textarea.current;
    if (!area || !draft || !selected) return;
    const { selectionStart: from, selectionEnd: to } = area;
    if (from === to) {
      setError("Выделите в тексте раздела формулировку рекомендации, затем нажмите кнопку ещё раз.");
      return;
    }
    const label = selected.number || selected.heading.split(/[.:]/)[0];
    const statement = draft.body.slice(from, to).replace(/\s*\n\s*/g, " ").trim();
    const body = `${draft.body.slice(0, from).trimEnd()}\n\n### Рекомендация ${label}/0 · УУР — · УДД —\n\n${statement}\n\n${draft.body.slice(to).trimStart()}`;
    setDraft({ ...draft, body: body.trim() });
  };

  if (!view) {
    return (
      <div className="p-6">
        <ErrorBanner message={error} />
        {!error && <p className="muted">Загрузка…</p>}
        <Link className="btn mt-3" href="/"><ArrowLeft size={14} /> К списку</Link>
      </div>
    );
  }

  const { doc } = view;
  const ready = doc.job.state === "ready";
  const isPdf = doc.sourceName.toLowerCase().endsWith(".pdf");
  const allRecs = sections.flatMap((section) => section.recommendations.map((rec) => ({ section, rec })));

  return (
    <div className="flex h-screen flex-col">
      <header className="flex flex-wrap items-center gap-3 border-b px-4 py-2.5" style={{ borderColor: "var(--line)", background: "var(--panel)" }}>
        <Link className="btn btn-ghost" href={view.group ? `/?g=${view.group.id}` : "/"} aria-label="К группе"><ArrowLeft size={16} /></Link>
        <div className="min-w-0 flex-1">
          <p className="muted truncate text-xs">{view.domain?.name} / {view.group?.name}</p>
          <h1 className="truncate text-base font-semibold">{doc.title}</h1>
        </div>
        <StatusBadge doc={doc} />
        {ready && <span className="muted text-xs">{doc.reviewedSections} из {doc.sections} разделов проверено</span>}
        {ready && doc.status === "draft" && (
          <button className="btn btn-primary" disabled={saving || dirty} onClick={() => apply(() => api.updateDocument(id, { status: "reviewed" }))}><Check size={14} /> Документ проверен</button>
        )}
        {ready && doc.status !== "draft" && (
          <button className="btn" disabled={saving} onClick={() => apply(() => api.updateDocument(id, { status: "draft" }))}>Вернуть в черновики</button>
        )}
        <button className="btn" onClick={() => setDialog({ kind: "card" })}><FileText size={14} /> Карточка</button>
        <button className="btn" onClick={() => setDialog({ kind: "history" })}><History size={14} /> Журнал</button>
        <button className="btn btn-danger" onClick={() => setDialog({ kind: "deleteDoc" })} aria-label="Удалить документ"><Trash2 size={14} /></button>
      </header>

      <div className="px-4 pt-3"><ErrorBanner message={error} onClose={() => setError("")} /></div>

      {!ready ? (
        <div className="panel m-6 p-8 text-center">
          <p className="mb-2 font-medium">{JOB_LABEL[doc.job.state]}</p>
          {doc.job.state === "failed" ? (
            <>
              <p className="mb-4" style={{ color: "var(--bad)" }}>{doc.job.error}</p>
              <button className="btn" onClick={() => apply(() => api.reparse(id))}><RotateCcw size={14} /> Попробовать ещё раз</button>
            </>
          ) : (
            <p className="muted">Из файла извлекается текст и разбивается на разделы. Страница обновится сама.</p>
          )}
        </div>
      ) : (
        <>
          <div className="flex items-center gap-2 px-4 pb-2">
            {tab === "sections" && (
              <button className="btn" onClick={() => setListCollapsed(!listCollapsed)} aria-label={listCollapsed ? "Показать список разделов" : "Свернуть список разделов"} data-tip={listCollapsed ? "Развернуть список разделов" : "Свернуть список разделов"} data-tip-side="right">
                {listCollapsed ? <PanelLeftOpen size={14} /> : <PanelLeftClose size={14} />}
              </button>
            )}
            <div role="tablist" className="flex gap-1">
              <button role="tab" aria-selected={tab === "sections"} className={`btn ${tab === "sections" ? "row-active" : ""}`} onClick={() => setTab("sections")}>Разделы · {sections.length}</button>
              <button role="tab" aria-selected={tab === "recs"} className={`btn ${tab === "recs" ? "row-active" : ""}`} onClick={() => setTab("recs")}>Рекомендации · {allRecs.length}</button>
            </div>
            <div className="flex-1" />
            {tab === "sections" && (
              <>
                <button className="btn" disabled={saving || dirty} onClick={() => apply(() => api.updateDocument(id, { sectionsStatus: "reviewed" }))}><CheckCheck size={14} /> Отметить все разделы</button>
                <button className="btn" disabled={saving} onClick={() => setDialog({ kind: "resplit" })}><RotateCcw size={14} /> Разбить заново</button>
                <button className="btn" onClick={() => setShowSource(!showSource)}>{showSource ? <><PanelRightClose size={14} /> Скрыть оригинал</> : <><PanelRightOpen size={14} /> Показать оригинал</>}</button>
              </>
            )}
          </div>

          {tab === "sections" && selected && draft && (
            <div className="flex min-h-0 flex-1 gap-3 px-4 pb-4">
              <nav hidden={listCollapsed} className="panel w-72 shrink-0 overflow-y-auto py-1" aria-label="Разделы документа">
                {sections.map((section) => (
                  <button
                    key={section.id}
                    onClick={() => select(section.id)}
                    className={`row-hover flex w-full items-start gap-1.5 py-1.5 pr-2 text-left ${section.id === selected.id ? "row-active" : ""}`}
                    style={{ paddingLeft: 8 + (section.level - 1) * 14 }}
                    aria-current={section.id === selected.id}
                  >
                    <span className="mt-0.5 w-3.5 shrink-0" style={{ color: "var(--ok)" }} title={section.status === "reviewed" ? "Проверен" : "Черновик"}>{section.status === "reviewed" && <Check size={14} />}</span>
                    <span className="min-w-0 flex-1">
                      <span className="line-clamp-2 text-[13px] leading-snug">{section.title}</span>
                      <span className="muted text-[11px]">
                        {[pages(section), section.recommendations.length ? `рекомендаций: ${section.recommendations.length}` : "", section.edited ? "изменён" : ""].filter(Boolean).join(" · ")}
                      </span>
                    </span>
                  </button>
                ))}
              </nav>

              <section className="panel flex min-w-0 flex-1 flex-col p-3" aria-label="Редактор раздела">
                <div className="mb-2 grid grid-cols-[90px_1fr] gap-2">
                  <label><span className="label">Номер</span><input className="input" value={draft.number} placeholder="2.4.1" onChange={(event) => setDraft({ ...draft, number: event.target.value })} /></label>
                  <label><span className="label">Заголовок</span><input className="input" value={draft.heading} onChange={(event) => setDraft({ ...draft, heading: event.target.value })} /></label>
                </div>
                <label className="mb-2 block">
                  <span className="label">Входит в раздел</span>
                  <select className="input" value={draft.parentId} onChange={(event) => setDraft({ ...draft, parentId: event.target.value })}>
                    <option value="">— верхний уровень —</option>
                    {sections.slice(0, selectedIndex).map((section) => <option key={section.id} value={section.id}>{"  ".repeat(section.level - 1)}{section.title}</option>)}
                  </select>
                </label>
                <span className="label">Текст раздела (дословно, как в документе){pages(selected) ? ` · ${pages(selected)}` : ""}</span>
                <textarea
                  ref={textarea}
                  className="input min-h-0 flex-1 resize-none font-mono leading-relaxed"
                  style={{ fontSize: 12.5 }}
                  spellCheck={false}
                  value={draft.body}
                  onChange={(event) => setDraft({ ...draft, body: event.target.value })}
                  aria-label="Текст раздела"
                />
                <div className="mt-2 flex flex-wrap items-center gap-2">
                  <button className="btn btn-primary" disabled={!dirty || saving} onClick={() => void save()}>Сохранить</button>
                  {dirty && <button className="btn" onClick={() => setDraft(draftOf(selected))}>Отменить правки</button>}
                  <button
                    className={`btn ${selected.status === "reviewed" ? "badge-ok" : ""}`}
                    disabled={saving}
                    onClick={() => apply(() => api.updateSection(id, selected.id, { ...draft, status: selected.status === "reviewed" && !dirty ? "draft" : "reviewed" }))}
                  >
                    <Check size={14} /> {selected.status === "reviewed" && !dirty ? "Проверен — снять отметку" : dirty ? "Сохранить и отметить проверенным" : "Раздел проверен"}
                  </button>
                  <div className="flex-1" />
                  <button className="btn" title="Оформить выделенный текст как рекомендацию" onClick={markSelection}>Выделенное — рекомендация</button>
                  <button
                    className="btn"
                    disabled={dirty || saving}
                    title={dirty ? "Сначала сохраните правки" : "Поставьте курсор в текст там, где должен начаться новый раздел"}
                    onClick={() => {
                      const offset = textarea.current?.selectionStart ?? 0;
                      if (offset <= 0 || offset >= selected.body.length) setError("Поставьте курсор внутри текста раздела — там, где должен начаться новый раздел, — и нажмите «Разделить» ещё раз.");
                      else setDialog({ kind: "split", offset });
                    }}
                  >
                    <Scissors size={14} /> Разделить по курсору
                  </button>
                  <button className="btn" disabled={dirty || saving || selectedIndex === 0} onClick={() => setDialog({ kind: "merge" })}><Merge size={14} /> Объединить с предыдущим</button>
                  <button className="btn btn-danger" disabled={saving || sections.length === 1} onClick={() => setDialog({ kind: "deleteSection" })} aria-label="Удалить раздел"><Trash2 size={14} /></button>
                </div>
                {selected.recommendations.length > 0 && (
                  <div className="mt-3 max-h-56 overflow-y-auto border-t pt-2" style={{ borderColor: "var(--line)" }}>
                    <p className="label">Рекомендации раздела{dirty ? " — сохраните текст, чтобы менять уровни" : ""}</p>
                    <RecRows id={id} items={selected.recommendations.map((rec) => ({ section: selected, rec }))} disabled={dirty || saving} apply={apply} />
                  </div>
                )}
              </section>

              {showSource && (
                <section className="panel min-w-0 flex-1 overflow-hidden" aria-label="Оригинал документа">
                  {isPdf ? (
                    <iframe key={selected.pageStart ?? 1} title="Оригинал" className="h-full w-full" src={`${api.sourceUrl(id)}#page=${selected.pageStart ?? 1}&navpanes=0`} />
                  ) : (
                    <SourceText id={id} />
                  )}
                </section>
              )}
            </div>
          )}

          {tab === "recs" && (
            <div className="min-h-0 flex-1 overflow-y-auto px-4 pb-4">
              <div className="panel">
                {allRecs.length ? (
                  <RecRows id={id} items={allRecs} disabled={saving || dirty} apply={apply} showSection onOpen={(sectionId) => { setTab("sections"); select(sectionId); }} />
                ) : (
                  <p className="muted p-6">В документе не найдено рекомендаций с уровнями убедительности и доказательности. Их можно отметить вручную: выделите формулировку в тексте раздела и нажмите «Выделенное — рекомендация».</p>
                )}
              </div>
            </div>
          )}
        </>
      )}

      {dialog?.kind === "card" && catalog && <CardDialog doc={doc} catalog={catalog} onClose={() => setDialog(null)} onSave={async (values) => setView(await api.updateDocument(id, values))} />}
      {dialog?.kind === "history" && <HistoryDialog id={id} onClose={() => setDialog(null)} />}
      {dialog?.kind === "split" && selected && (
        <FormDialog
          title="Новый раздел с места курсора"
          submitLabel="Разделить"
          fields={[{ name: "number", label: "Номер (необязательно)", placeholder: "2.4.2" }, { name: "heading", label: "Заголовок нового раздела", hint: `Текст после курсора (${selected.body.length - dialog.offset} знаков) перейдёт в новый раздел.` }]}
          onClose={() => setDialog(null)}
          onSubmit={async (values) => {
            const next = await api.splitSection(id, selected.id, { offset: dialog.offset, heading: values.heading!, number: values.number });
            setView(next);
            const created = next.sections[next.sections.findIndex((section) => section.id === selected.id) + 1];
            if (created) setSelectedId(created.id);
          }}
        />
      )}
      {dialog?.kind === "merge" && selected && (
        <ConfirmDialog
          title="Объединить разделы?"
          text={`Текст раздела «${selected.title}» будет добавлен в конец раздела «${sections[selectedIndex - 1]?.title}». Заголовок останется в тексте отдельной строкой.`}
          confirmLabel="Объединить"
          onClose={() => setDialog(null)}
          onConfirm={async () => {
            const previous = sections[selectedIndex - 1];
            setView(await api.mergeSection(id, selected.id));
            if (previous) setSelectedId(previous.id);
          }}
        />
      )}
      {dialog?.kind === "deleteSection" && selected && (
        <ConfirmDialog
          title="Удалить раздел?"
          text={`Раздел «${selected.title}» и его текст будут удалены из базы знаний. Подразделы поднимутся на уровень выше. Вернуть раздел можно только кнопкой «Разбить заново», которая сбрасывает все ручные правки.`}
          confirmLabel="Удалить раздел"
          danger
          onClose={() => setDialog(null)}
          onConfirm={async () => setView(await api.deleteSection(id, selected.id))}
        />
      )}
      {dialog?.kind === "resplit" && (
        <ConfirmDialog
          title="Разбить документ заново?"
          text="Разделы будут построены автоматически из извлечённого текста. Все ручные правки разделов, рекомендаций и отметки о проверке пропадут."
          confirmLabel="Сбросить правки и разбить"
          danger
          onClose={() => setDialog(null)}
          onConfirm={async () => {
            setView(await api.resplit(id));
            setSelectedId("");
          }}
        />
      )}
      {dialog?.kind === "deleteDoc" && (
        <ConfirmDialog
          title="Удалить документ?"
          text={`«${doc.title}» будет удалён вместе с исходным файлом, разделами и всеми правками. Вернуть его будет нельзя.`}
          confirmLabel="Удалить навсегда"
          danger
          onClose={() => setDialog(null)}
          onConfirm={async () => {
            await api.deleteDocument(id);
            router.push(view.group ? `/?g=${view.group.id}` : "/");
          }}
        />
      )}
      {dialog?.kind === "leave" && (
        <ConfirmDialog
          title="Несохранённые правки"
          text="В этом разделе есть несохранённые правки. Сохранить их перед переходом?"
          confirmLabel="Сохранить и перейти"
          onClose={() => setDialog(null)}
          onConfirm={async () => {
            if (!(await save())) throw new Error("Не удалось сохранить. Закройте окно и исправьте ошибку.");
            setSelectedId(dialog.to);
          }}
        />
      )}
    </div>
  );
}

function RecRows({ id, items, disabled, apply, showSection, onOpen }: {
  id: string;
  items: { section: Section; rec: Section["recommendations"][number] }[];
  disabled: boolean;
  apply: (action: () => Promise<DocumentView>) => Promise<boolean>;
  showSection?: boolean;
  onOpen?: (sectionId: string) => void;
}) {
  return (
    <table className="grid-table">
      <thead><tr><th className="w-20">№</th>{showSection && <th className="w-64">Раздел</th>}<th className="w-20">УУР</th><th className="w-20">УДД</th><th>Рекомендация</th><th className="w-10" /></tr></thead>
      <tbody>
        {items.map(({ section, rec }) => {
          const label = `${section.number || section.heading.split(/[.:]/)[0]}/${rec.n}`;
          const change = (body: Record<string, unknown>) => apply(() => api.updateRecommendation(id, section.id, rec.n, body));
          return (
            <tr key={`${section.id}-${rec.n}`}>
              <td className="whitespace-nowrap">{label}</td>
              {showSection && <td><button className="text-left hover:underline" onClick={() => onOpen?.(section.id)}>{section.title}</button></td>}
              <td>
                <select className="input" aria-label={`УУР рекомендации ${label}`} disabled={disabled} value={rec.grade ?? ""} onChange={(event) => void change({ grade: event.target.value })}>
                  <option value="">—</option>{["A", "B", "C"].map((grade) => <option key={grade}>{grade}</option>)}
                </select>
              </td>
              <td>
                <select className="input" aria-label={`УДД рекомендации ${label}`} disabled={disabled} value={rec.evidence ?? ""} onChange={(event) => void change({ evidence: event.target.value })}>
                  <option value="">—</option>{["1", "2", "3", "4", "5"].map((level) => <option key={level}>{level}</option>)}
                </select>
              </td>
              <td>{rec.text}{rec.comment && <div className="muted mt-1 line-clamp-2 text-xs">Комментарий: {rec.comment}</div>}</td>
              <td><button className="btn btn-ghost" disabled={disabled} title="Снять разметку: вернуть в обычный текст" aria-label={`Снять разметку рекомендации ${label}`} onClick={() => void change({ remove: true })}>×</button></td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

function SourceText({ id }: { id: string }) {
  const [text, setText] = useState<string | null>(null);
  useEffect(() => {
    api.text(id).then((result) => setText(result.text)).catch(() => setText(""));
  }, [id]);
  return <pre className="h-full overflow-auto whitespace-pre-wrap p-3 text-xs leading-relaxed">{text ?? "Загрузка…"}</pre>;
}

function HistoryDialog({ id, onClose }: { id: string; onClose: () => void }) {
  const [rows, setRows] = useState<HistoryEntry[] | null>(null);
  useEffect(() => {
    api.history(id).then((result) => setRows(result.history)).catch(() => setRows([]));
  }, [id]);
  return (
    <Modal title="Журнал правок" onClose={onClose} wide>
      <div className="max-h-[60vh] overflow-y-auto">
        {rows === null ? <p className="muted">Загрузка…</p> : !rows.length ? <p className="muted">Записей нет.</p> : (
          <ul className="space-y-2">
            {rows.map((row, index) => (
              <li key={index} className="text-sm">
                <span className="muted mr-2 text-xs">{new Date(row.at).toLocaleString("ru-RU")}</span>
                {row.action}{row.detail ? <span className="muted"> — {row.detail}</span> : null}
              </li>
            ))}
          </ul>
        )}
      </div>
      <div className="mt-4 flex justify-end"><button className="btn" onClick={onClose}>Закрыть</button></div>
    </Modal>
  );
}

function CardDialog({ doc, catalog, onSave, onClose }: { doc: DocumentMeta; catalog: Catalog; onSave: (values: Record<string, unknown>) => Promise<void>; onClose: () => void }) {
  const [values, setValues] = useState({
    title: doc.title,
    description: doc.description,
    kind: doc.kind,
    origin: doc.origin,
    url: doc.url,
    year: doc.year === undefined ? "" : String(doc.year),
    version: doc.version,
    approvedAt: doc.approvedAt,
    reviewDue: doc.reviewDue,
    icd10: doc.icd10.join(", "),
    tags: doc.tags.join(", "),
    groupId: doc.groupId,
  });
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const field = (name: keyof typeof values, label: string, props: { type?: string; placeholder?: string } = {}) => (
    <label className="block">
      <span className="label">{label}</span>
      <input className="input" type={props.type ?? "text"} placeholder={props.placeholder} value={values[name]} onChange={(event) => setValues({ ...values, [name]: event.target.value })} />
    </label>
  );
  return (
    <Modal title="Карточка документа" onClose={onClose} wide>
      <form
        className="space-y-3"
        onSubmit={async (event) => {
          event.preventDefault();
          setBusy(true);
          setError("");
          try {
            await onSave(values);
            onClose();
          } catch (exc) {
            setError(exc instanceof Error ? exc.message : String(exc));
            setBusy(false);
          }
        }}
      >
        {field("title", "Название")}
        <label className="block">
          <span className="label">Когда читать этот документ (по этой строке агент выбирает документ)</span>
          <textarea className="input" rows={2} value={values.description} onChange={(event) => setValues({ ...values, description: event.target.value })} />
        </label>
        <div className="grid grid-cols-2 gap-3">
          <label className="block">
            <span className="label">Тип</span>
            <select className="input" value={values.kind} onChange={(event) => setValues({ ...values, kind: event.target.value })}>
              {catalog.kinds.map((kind) => <option key={kind.id} value={kind.id}>{kind.label}</option>)}
            </select>
          </label>
          <label className="block">
            <span className="label">Группа</span>
            <select className="input" value={values.groupId} onChange={(event) => setValues({ ...values, groupId: event.target.value })}>
              {catalog.domains.flatMap((domain) => groupTree(domain.groups).map(({ group, depth }) => <option key={group.id} value={group.id}>{domain.name} / {"\u00A0\u00A0".repeat(depth)}{group.name}</option>))}
            </select>
          </label>
          {field("origin", "Источник", { placeholder: "Минздрав России, АОР" })}
          {field("url", "Ссылка", { placeholder: "https://…" })}
          {field("year", "Год", { placeholder: "2024" })}
          {field("version", "Версия")}
          {field("approvedAt", "Дата утверждения", { type: "date" })}
          {field("reviewDue", "Срок пересмотра", { type: "date" })}
          {field("icd10", "Коды МКБ-10 (через запятую)", { placeholder: "C10, C09.1" })}
          {field("tags", "Теги (через запятую)")}
        </div>
        <p className="muted text-xs">Файл: {doc.sourceName}{doc.pages ? ` · страниц: ${doc.pages}` : ""} · знаков: {doc.chars.toLocaleString("ru-RU")}. Год, тип и коды МКБ-10 подставлены автоматически с титульной страницы — проверьте их.</p>
        {error && <p className="text-sm" style={{ color: "var(--bad)" }}>{error}</p>}
        <div className="flex justify-end gap-2">
          <button type="button" className="btn" onClick={onClose}>Отмена</button>
          <button type="submit" className="btn btn-primary" disabled={busy}>Сохранить</button>
        </div>
      </form>
    </Modal>
  );
}

export default function Page() {
  return (
    <Suspense>
      <DocumentPage />
    </Suspense>
  );
}
