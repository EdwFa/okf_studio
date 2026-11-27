import { existsSync, readFileSync } from "node:fs";
import path from "node:path";
import { NextResponse } from "next/server";

const ID = /^\d+_\d+$/;
const NAME = /^[\w.-]+\.(png|jpe?g|webp)$/i;

const TYPES: Record<string, string> = {
  ".png": "image/png",
  ".jpg": "image/jpeg",
  ".jpeg": "image/jpeg",
  ".webp": "image/webp",
};

function assetPath(id: string, name: string) {
  return [process.cwd(), path.join(process.cwd(), "..")]
    .map((dir) => path.join(dir, "data", "md", "assets", id, name))
    .find((candidate) => existsSync(candidate));
}

export async function GET(_request: Request, context: { params: Promise<{ id: string; name: string }> }) {
  const { id, name } = await context.params;
  if (!ID.test(id) || !NAME.test(name)) return new NextResponse("Не найдено", { status: 404 });
  const file = assetPath(id, name);
  if (!file) return new NextResponse("Не найдено", { status: 404 });
  const bytes = readFileSync(file);
  return new NextResponse(bytes, {
    headers: {
      "Content-Type": TYPES[path.extname(name).toLowerCase()] || "application/octet-stream",
      "Content-Length": String(bytes.length),
      "Cache-Control": "no-store",
    },
  });
}
