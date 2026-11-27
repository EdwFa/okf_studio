import { spawn } from "node:child_process";
import { mkdirSync } from "node:fs";
import path from "node:path";
import { markdownFile, outputFile, pdfFile, repoRoot } from "./parse-files";

const ID = /^\d+_\d+$/;

interface Runner {
  queue: string[];
  current: string | null;
  errors: Record<string, string>;
}

const globalRunner = globalThis as typeof globalThis & { __okfParseRunner?: Runner };

function runner(): Runner {
  if (!globalRunner.__okfParseRunner) {
    globalRunner.__okfParseRunner = { queue: [], current: null, errors: {} };
  }
  return globalRunner.__okfParseRunner;
}

export interface ParseStatus {
  queue: string[];
  current: string | null;
  errors: Record<string, string>;
  ready: string[];
}

export function parseStatus(): ParseStatus {
  const state = runner();
  const busy = new Set(state.queue);
  if (state.current) busy.add(state.current);
  return {
    queue: [...state.queue],
    current: state.current,
    errors: { ...state.errors },
    ready: [],
  };
}

export function readyIds(ids: string[]): string[] {
  const state = runner();
  const busy = new Set(state.queue);
  if (state.current) busy.add(state.current);
  return ids.filter((id) => !busy.has(id) && markdownFile(id));
}

export function enqueueParse(ids: string[]): ParseStatus {
  const state = runner();
  const rejected: string[] = [];
  for (const id of ids) {
    if (!ID.test(id) || !pdfFile(id)) {
      rejected.push(id);
      continue;
    }
    delete state.errors[id];
    if (state.current === id || state.queue.includes(id)) continue;
    state.queue.push(id);
  }
  if (rejected.length && rejected.length === ids.length) {
    throw new Error("Среди выбранных нет PDF");
  }
  pump();
  return parseStatus();
}

function pump(): void {
  const state = runner();
  if (state.current || !state.queue.length) return;
  const id = state.queue.shift()!;
  state.current = id;
  const root = repoRoot();
  const target = outputFile(id);
  mkdirSync(path.dirname(target), { recursive: true });
  const child = spawn("python3", [path.join(root, "scripts", "pdf_to_md.py"), pdfFile(id)!, target], {
    cwd: root,
  });
  let stderr = "";
  child.stderr.on("data", (chunk: Buffer) => {
    stderr = (stderr + chunk.toString()).slice(-4000);
  });
  let settled = false;
  const finish = (failed: string | null) => {
    if (settled) return;
    settled = true;
    if (state.current === id) state.current = null;
    if (failed) state.errors[id] = failed;
    else delete state.errors[id];
    pump();
  };
  child.on("error", (error) => finish(error.message));
  child.on("close", (code) => finish(code === 0 ? null : stderr.trim().split("\n").pop() || `разбор завершился с кодом ${code}`));
}
