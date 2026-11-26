import { existsSync, readFileSync } from "node:fs";
import path from "node:path";
import { NextResponse } from "next/server";

const ID = /^\d+_\d+$/;

function pdfPath(id: string) {
  const name = `${id}.pdf`;
  return [process.cwd(), path.join(process.cwd(), "..")]
    .map((dir) => path.join(dir, "data", "pdf", name))
    .find((candidate) => existsSync(candidate));
}

export async function GET(_request: Request, context: { params: Promise<{ id: string }> }) {
  const { id } = await context.params;
  if (!ID.test(id)) return new NextResponse("Не найдено", { status: 404 });
  const file = pdfPath(id);
  if (!file) return new NextResponse("Не найдено", { status: 404 });
  const bytes = readFileSync(file);
  return new NextResponse(bytes, {
    headers: {
      "Content-Type": "application/pdf",
      "Content-Disposition": `inline; filename="${id}.pdf"`,
      "Content-Length": String(bytes.length),
    },
  });
}
