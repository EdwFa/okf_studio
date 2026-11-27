import Link from "next/link";
import { notFound } from "next/navigation";
import { readFileSync } from "node:fs";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { prepareClinrecMarkdown } from "@/lib/clinrec-md";
import { markdownFile } from "@/lib/parse-files";
import "../../clinrec/[id]/clinrec.css";

const ID = /^\d+_\d+$/;

export const dynamic = "force-dynamic";

export default async function ParseResultPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  if (!ID.test(id)) notFound();
  const file = markdownFile(id);
  if (!file) notFound();
  const text = readFileSync(file, "utf8");
  return (
    <main className="mx-auto max-w-4xl px-6 py-8">
      <p className="mb-6 text-sm">
        <Link href="/parse">← Разбор</Link>
        <a className="ml-4" href={`/pdf/${id}`} target="_blank" rel="noreferrer">PDF</a>
      </p>
      <article className="md-body">
        <ReactMarkdown
          remarkPlugins={[remarkGfm]}
          components={{
            img: ({ src, alt }) => {
              const file = (src || "").split("/").pop() || "";
              if (!/^[\w.-]+$/.test(file)) return null;
              return <img src={`/parse-asset/${id}/${file}`} alt={alt || ""} />;
            },
          }}
        >
          {prepareClinrecMarkdown(text)}
        </ReactMarkdown>
      </article>
    </main>
  );
}
