export { splitIntoSections, structureRecommendations, type KnowledgeSection, type Recommendation } from "./sections.ts";
export { normalizeBody, parseBody, recommendationsOf, sectionLabel, serializeBody, type BodyBlock, type RecBlock, type TextBlock } from "./recs.ts";
export {
  OKF_VERSION,
  appendLogEntry,
  documentFile,
  frontmatter,
  groupIndexBody,
  okfInstant,
  renderDocument,
  renderGroupIndex,
  renderRootIndex,
  sectionFile,
  skillDescription,
  type OkfDocument,
  type OkfDocumentSummary,
  type OkfGroup,
} from "./bundle.ts";

export { checkBundle } from "./conformance.ts";

import path from "node:path";
import { fileURLToPath } from "node:url";

/** The Python CLI that turns a PDF or DOCX into text: `extract_text.py <path> <pdf|docx>`. */
export const EXTRACT_SCRIPT = path.join(path.dirname(fileURLToPath(import.meta.url)), "..", "python", "extract_text.py");
