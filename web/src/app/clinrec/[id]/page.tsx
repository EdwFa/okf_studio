import { readFileSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import Link from "next/link";
import { notFound } from "next/navigation";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { prepareClinrecMarkdown } from "@/lib/clinrec-md";
import "./clinrec.css";

const ID = /^\d+_\d+$/;

export default async function ClinRecTextPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  if (!ID.test(id)) notFound();
  const file = path.join(os.homedir(), "ClinRec", "data", "text", `${id}.md`);
  let text = "";
  try {
    text = readFileSync(file, "utf8");
  } catch {
    notFound();
  }
  return (
    <main className="mx-auto max-w-4xl px-6 py-8">
      <p className="mb-6 text-sm">
        <Link href="/nosology">← Классификатор</Link>
        <a className="ml-4" href={`https://cr.minzdrav.gov.ru/preview-cr/${id}`} target="_blank" rel="noreferrer">карточка Минздрава</a>
      </p>
      <article className="md-body">
        <ReactMarkdown remarkPlugins={[remarkGfm]}>{prepareClinrecMarkdown(text)}</ReactMarkdown>
      </article>
    </main>
  );
}
