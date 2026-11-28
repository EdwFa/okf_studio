import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const REPO = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..");

/** Local Minzdrav PDFs, `data/pdf/<id>.pdf`. Override with OKF_PDF_DIR. */
export function pdfDir(): string {
  return process.env.OKF_PDF_DIR || path.join(REPO, "data", "pdf");
}

/** Where the studio keeps its data. Override with OKF_STUDIO_HOME. */
export const DATA_DIR = process.env.OKF_STUDIO_HOME || path.join(os.homedir(), ".okf-studio");
export const PORT = Number(process.env.OKF_STUDIO_PORT) || 8100;
export const WEB_PORT = Number(process.env.OKF_STUDIO_WEB_PORT) || 3100;

/** Interpreter for the text-extraction helper: OKF_PYTHON, the repository's venv, or the system Python. */
export function pythonPath(): string {
  if (process.env.OKF_PYTHON) return process.env.OKF_PYTHON;
  const venv = path.join(REPO, ".venv", "bin", "python");
  return fs.existsSync(venv) ? venv : "python3";
}

/** Luka's agent directory: its knowledge base lives in `knowledge/`, the skills agents see in `skills/`. Override with LUKA_AGENT_DIR. */
export const LUKA_AGENT_DIR = process.env.LUKA_AGENT_DIR || path.join(os.homedir(), ".kady", "pi-agent");
