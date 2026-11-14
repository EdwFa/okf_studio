/** Turning an uploaded file into text. PDF and DOCX go through okf-core's Python helper. */
import { execFile } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { EXTRACT_SCRIPT } from "okf-core";
import { pythonPath } from "./config.ts";
import { StoreError } from "./store.ts";

export interface ExtractedText {
  text: string;
  pages?: number;
}

export type Extractor = (file: string) => Promise<ExtractedText>;

const TIMEOUT_MS = 5 * 60 * 1000;

function stripFrontmatter(raw: string): string {
  if (!raw.startsWith("---")) return raw;
  const end = raw.indexOf("\n---", 3);
  return end >= 0 ? raw.slice(raw.indexOf("\n", end + 1) + 1) : raw;
}

function runHelper(file: string, kind: "pdf" | "docx"): Promise<ExtractedText> {
  return new Promise((resolve, reject) => {
    execFile(pythonPath(), ["-I", EXTRACT_SCRIPT, file, kind], { timeout: TIMEOUT_MS, maxBuffer: 256 * 1024 * 1024 }, (error, stdout, stderr) => {
      if (error) {
        const reason = error.killed ? "разбор занял слишком много времени" : stderr.trim().split("\n").pop() || error.message;
        reject(new StoreError(`Не удалось прочитать файл: ${reason}`, 422));
        return;
      }
      try {
        const parsed = JSON.parse(stdout) as { text?: unknown; pages?: unknown };
        resolve({ text: typeof parsed.text === "string" ? parsed.text : "", ...(typeof parsed.pages === "number" ? { pages: parsed.pages } : {}) });
      } catch {
        reject(new StoreError("Не удалось прочитать файл: помощник вернул непонятный ответ", 422));
      }
    });
  });
}

export const extractText: Extractor = async (file) => {
  const ext = path.extname(file).toLowerCase();
  if (ext === ".pdf") return runHelper(file, "pdf");
  if (ext === ".docx") return runHelper(file, "docx");
  const raw = await fs.promises.readFile(file, "utf-8");
  return { text: ext === ".txt" ? raw : stripFrontmatter(raw) };
};
