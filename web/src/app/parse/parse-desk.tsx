"use client";

import { ScanText } from "lucide-react";
import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import type { ParseDoc } from "@/lib/parse-files";

interface Status {
  queue: string[];
  current: string | null;
  errors: Record<string, string>;
  ready: string[];
}

function badge(id: string, status: Status, ready: Set<string>): { label: string; className: string } {
  if (status.current === id) return { label: "Разбирается", className: "badge badge-warn" };
  if (status.queue.includes(id)) return { label: "В очереди", className: "badge badge-accent" };
  if (status.errors[id]) return { label: "Ошибка", className: "badge badge-bad" };
  if (ready.has(id)) return { label: "Готов", className: "badge badge-ok" };
  return { label: "Не разобран", className: "badge" };
}

export function ParseDesk({ docs }: { docs: ParseDoc[] }) {
  const [query, setQuery] = useState("");
  const [picked, setPicked] = useState<Set<string>>(new Set());
  const [status, setStatus] = useState<Status>({ queue: [], current: null, errors: {}, ready: [] });
  const [ready, setReady] = useState<Set<string>>(() => new Set(docs.filter((doc) => doc.ready).map((doc) => doc.id)));
  const [sending, setSending] = useState(false);
  const [error, setError] = useState("");

  const shown = useMemo(() => {
    const needle = query.trim().toLowerCase();
    if (!needle) return docs;
    return docs.filter((doc) => `${doc.name} ${doc.id} ${doc.codes} ${doc.age} ${doc.year}`.toLowerCase().includes(needle));
  }, [docs, query]);

  const busy = Boolean(status.current || status.queue.length);

  useEffect(() => {
    let stop = false;
    const pull = async () => {
      const response = await fetch("/api/parse");
      if (!response.ok || stop) return;
      const next = (await response.json()) as Status;
      if (stop) return;
      setStatus(next);
      setReady(new Set(next.ready));
    };
    void pull();
    if (!busy) return;
    const timer = setInterval(() => void pull(), 2000);
    return () => {
      stop = true;
      clearInterval(timer);
    };
  }, [busy]);

  const toggle = (id: string) => {
    setPicked((current) => {
      const next = new Set(current);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const shownIds = shown.map((doc) => doc.id);
  const canMarkShown = shownIds.length > 0 && shownIds.length <= 30;
  const allShown = canMarkShown && shownIds.every((id) => picked.has(id));

  const toggleShown = () => {
    setPicked((current) => {
      const next = new Set(current);
      if (allShown) for (const id of shownIds) next.delete(id);
      else for (const id of shownIds) next.add(id);
      return next;
    });
  };

  const start = async () => {
    setSending(true);
    setError("");
    try {
      const response = await fetch("/api/parse", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ ids: [...picked] }),
      });
      const body = (await response.json()) as Status & { detail?: string };
      if (!response.ok) throw new Error(body.detail || "Не удалось поставить в очередь");
      setStatus(body);
      setReady(new Set(body.ready));
      setPicked(new Set());
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Не удалось поставить в очередь");
    } finally {
      setSending(false);
    }
  };

  return (
    <main className="mx-auto flex h-screen max-w-6xl flex-col px-6 py-6">
      <p className="mb-3 text-sm">
        <Link href="/">← OKF Studio</Link>
        <Link className="ml-4" href="/nosology">Классификатор</Link>
      </p>
      <div className="mb-4 flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="flex items-center gap-2 text-xl font-semibold"><ScanText size={20} /> Разбор PDF</h1>
          <p className="muted mt-1 text-sm">В разбор уходят только отмеченные документы. Готовый текст открывается отдельно.</p>
        </div>
        <button className="btn btn-primary" disabled={!picked.size || sending} onClick={() => void start()}>
          Разобрать выбранные{picked.size ? ` (${picked.size})` : ""}
        </button>
      </div>
      {error && <p className="mb-3 text-sm" style={{ color: "var(--bad)" }}>{error}</p>}
      <input className="input mb-3" placeholder="Название, код МКБ, номер" value={query} onChange={(event) => setQuery(event.target.value)} />
      <p className="muted mb-2 text-sm">Показано {shown.length} из {docs.length}. В очереди {status.queue.length}{status.current ? ", один разбирается" : ""}.</p>
      <div className="panel min-h-0 flex-1 overflow-auto">
        <table className="grid-table">
          <thead>
            <tr>
              <th style={{ width: 36 }}>
                <input type="checkbox" checked={allShown} disabled={!canMarkShown} onChange={toggleShown} aria-label="Отметить показанные" title={canMarkShown ? "Отметить показанные" : "Сначала сузьте список до 30 документов"} />
              </th>
              <th>Документ</th>
              <th>Возраст</th>
              <th>Год</th>
              <th>Разбор</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {shown.map((doc) => {
              const state = badge(doc.id, status, ready);
              return (
                <tr key={doc.id}>
                  <td>
                    <input type="checkbox" checked={picked.has(doc.id)} onChange={() => toggle(doc.id)} aria-label={`Выбрать ${doc.name}`} />
                  </td>
                  <td>
                    <div>{doc.name}</div>
                    <div className="muted text-xs">{doc.id}{doc.codes ? ` · ${doc.codes}` : ""}</div>
                    {status.errors[doc.id] && <div className="mt-1 text-xs" style={{ color: "var(--bad)" }}>{status.errors[doc.id]}</div>}
                  </td>
                  <td className="muted">{doc.age}</td>
                  <td className="muted">{doc.year}</td>
                  <td><span className={state.className}>{state.label}</span></td>
                  <td className="text-right whitespace-nowrap">
                    {ready.has(doc.id) && status.current !== doc.id && <Link className="mr-3" href={`/parse/${doc.id}`}>Смотреть</Link>}
                    <a href={`/pdf/${doc.id}`} target="_blank" rel="noreferrer">PDF</a>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </main>
  );
}
