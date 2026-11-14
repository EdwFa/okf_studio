"use client";

import { useEffect, useState, type ReactNode } from "react";
import type { DocumentMeta } from "@/lib/api";
import { JOB_LABEL, STATUS_LABEL } from "@/lib/api";

export function Modal({ title, onClose, children, wide }: { title: string; onClose: () => void; children: ReactNode; wide?: boolean }) {
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => event.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-black/40 p-6" onMouseDown={(event) => event.target === event.currentTarget && onClose()}>
      <div role="dialog" aria-modal="true" aria-label={title} className={`panel mt-16 w-full p-5 shadow-xl ${wide ? "max-w-2xl" : "max-w-md"}`}>
        <h2 className="mb-4 text-base font-semibold">{title}</h2>
        {children}
      </div>
    </div>
  );
}

export interface FormField {
  name: string;
  label: string;
  value?: string;
  placeholder?: string;
  multiline?: boolean;
  /** A choice instead of free text. */
  options?: { value: string; label: string }[];
  hint?: string;
}

/** A small form in a dialog; `onSubmit` may throw to show its message and keep the dialog open. */
export function FormDialog({ title, fields, submitLabel = "Сохранить", onSubmit, onClose }: { title: string; fields: FormField[]; submitLabel?: string; onSubmit: (values: Record<string, string>) => Promise<void>; onClose: () => void }) {
  const [values, setValues] = useState<Record<string, string>>(() => Object.fromEntries(fields.map((field) => [field.name, field.value ?? ""])));
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  return (
    <Modal title={title} onClose={onClose}>
      <form
        className="space-y-3"
        onSubmit={async (event) => {
          event.preventDefault();
          setBusy(true);
          setError("");
          try {
            await onSubmit(values);
            onClose();
          } catch (exc) {
            setError(exc instanceof Error ? exc.message : String(exc));
            setBusy(false);
          }
        }}
      >
        {fields.map((field, index) => (
          <label key={field.name} className="block">
            <span className="label">{field.label}</span>
            {field.options ? (
              <select className="input" value={values[field.name]} onChange={(event) => setValues({ ...values, [field.name]: event.target.value })}>
                {field.options.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
              </select>
            ) : field.multiline ? (
              <textarea className="input" rows={3} value={values[field.name]} placeholder={field.placeholder} onChange={(event) => setValues({ ...values, [field.name]: event.target.value })} />
            ) : (
              <input className="input" autoFocus={index === 0} value={values[field.name]} placeholder={field.placeholder} onChange={(event) => setValues({ ...values, [field.name]: event.target.value })} />
            )}
            {field.hint && <span className="muted mt-1 block text-xs">{field.hint}</span>}
          </label>
        ))}
        {error && <p className="text-sm" style={{ color: "var(--bad)" }}>{error}</p>}
        <div className="flex justify-end gap-2 pt-1">
          <button type="button" className="btn" onClick={onClose}>Отмена</button>
          <button type="submit" className="btn btn-primary" disabled={busy}>{submitLabel}</button>
        </div>
      </form>
    </Modal>
  );
}

export function ConfirmDialog({ title, text, confirmLabel, danger, onConfirm, onClose }: { title: string; text: string; confirmLabel: string; danger?: boolean; onConfirm: () => Promise<void>; onClose: () => void }) {
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  return (
    <Modal title={title} onClose={onClose}>
      <p className="mb-4 text-sm">{text}</p>
      {error && <p className="mb-3 text-sm" style={{ color: "var(--bad)" }}>{error}</p>}
      <div className="flex justify-end gap-2">
        <button className="btn" onClick={onClose}>Отмена</button>
        <button
          className={`btn ${danger ? "btn-danger" : "btn-primary"}`}
          disabled={busy}
          onClick={async () => {
            setBusy(true);
            try {
              await onConfirm();
              onClose();
            } catch (exc) {
              setError(exc instanceof Error ? exc.message : String(exc));
              setBusy(false);
            }
          }}
        >
          {confirmLabel}
        </button>
      </div>
    </Modal>
  );
}

export function StatusBadge({ doc }: { doc: Pick<DocumentMeta, "status" | "job"> }) {
  if (doc.job.state !== "ready") {
    return <span className={`badge ${doc.job.state === "failed" ? "badge-bad" : "badge-accent"}`} title={doc.job.error}>{JOB_LABEL[doc.job.state]}</span>;
  }
  return <span className={`badge ${doc.status === "draft" ? "badge-warn" : "badge-ok"}`}>{STATUS_LABEL[doc.status]}</span>;
}

export function ErrorBanner({ message, onClose }: { message: string; onClose?: () => void }) {
  if (!message) return null;
  return (
    <div role="alert" className="mb-3 flex items-start justify-between gap-3 rounded-lg px-3 py-2 text-sm" style={{ background: "var(--bad-soft)", color: "var(--bad)" }}>
      <span className="whitespace-pre-line">{message}</span>
      {onClose && <button className="btn-ghost btn" onClick={onClose} aria-label="Закрыть">×</button>}
    </div>
  );
}
