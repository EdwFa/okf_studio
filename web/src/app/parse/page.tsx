import { parseDocs } from "@/lib/parse-files";
import { ParseDesk } from "./parse-desk";

export const dynamic = "force-dynamic";

export default function ParsePage() {
  return <ParseDesk docs={parseDocs()} />;
}
