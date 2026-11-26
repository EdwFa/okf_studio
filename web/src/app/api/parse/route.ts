import { NextResponse } from "next/server";
import { parseDocs } from "@/lib/parse-files";
import { enqueueParse, parseStatus, readyIds } from "@/lib/parse-queue";

export const dynamic = "force-dynamic";

export async function GET() {
  const docs = parseDocs();
  const status = parseStatus();
  return NextResponse.json({ ...status, ready: readyIds(docs.map((doc) => doc.id)) });
}

export async function POST(request: Request) {
  const body = (await request.json().catch(() => null)) as { ids?: unknown } | null;
  const ids = Array.isArray(body?.ids) ? body.ids.filter((id): id is string => typeof id === "string") : [];
  if (!ids.length) return NextResponse.json({ detail: "Выберите документы" }, { status: 400 });
  try {
    const status = enqueueParse(ids);
    return NextResponse.json({ ...status, ready: readyIds(parseDocs().map((doc) => doc.id)) });
  } catch (error) {
    return NextResponse.json({ detail: error instanceof Error ? error.message : "Не удалось поставить в очередь" }, { status: 400 });
  }
}
