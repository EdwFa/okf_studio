"""Convert a clinical-recommendation PDF to Markdown.

Text comes from the PDF text layer. Ruled tables become Markdown tables.
A figure is written next to the document and linked from it. A box-and-arrow
scheme also becomes Mermaid when the drawn arrows connect the boxes; otherwise
the picture is kept and the readable labels are listed under it. Pages that
are only a scan, and title pages whose text layer is stamp noise, are read
with Apple Vision.

    python3 scripts/pdf_to_md.py INPUT.pdf OUTPUT.md
    python3 scripts/pdf_to_md.py INPUT.pdf OUTPUT.md --pages 1,11,59

The check report is written beside the Markdown file. Exit code 1 means the
file was written but is not safe to use.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VENV = ROOT / ".venv" / "bin" / "python"
SCRIPTS = Path(__file__).resolve().parent

sys.path.insert(0, str(SCRIPTS / "pdfmd"))

from assemble import assemble  # noqa: E402
from checks import recall, structural  # noqa: E402
from layout import clean_text, flow  # noqa: E402
from ocr import blocks_from_ocr, recognize, restore_mass_numbers, scheme_caption  # noqa: E402


def _fix_italic(page: dict, assets: Path) -> None:
    """Italic spans in some files map ligatures to the wrong letters. Read those lines from the page image."""
    if not page.get("lines") or not page.get("image"):
        return
    if not page.get("italic_fix") and not page.get("line_fix"):
        return
    height = page["page_h"]
    seen = recognize(assets / page["image"])
    patched = []
    for line in page["lines"]:
        replace = line.get("garbled") or (page.get("italic_fix") and line.get("italic"))
        if not replace:
            patched.append(line)
            continue
        center = (line["y"] + line["y1"]) / 2
        best = None
        best_d = 9
        for row in seen:
            dist = abs((row["y"] + row["y1"]) / 2 * height - center)
            if dist < best_d:
                best, best_d = row, dist
        patched.append({**line, "text": clean_text(best["text"])} if best else line)
    prose = flow(patched, height)
    kept = [block for block in page.get("blocks") or [] if block["type"] in {"table", "figure"}]
    page["blocks"] = sorted([*prose, *kept], key=lambda block: block.get("y", 0))
    print(f"italic page {page['page']}", file=sys.stderr)


def _pages_arg(argv: list[str]) -> str | None:
    if "--pages" not in argv:
        return None
    return argv[argv.index("--pages") + 1]


def convert(source: Path, target: Path, pages: str | None = None) -> dict:
    if not VENV.exists():
        raise SystemExit("Нет .venv. Сначала: npm run setup:python и установка pymupdf numpy")
    doc_id = target.stem
    assets = target.parent / "assets" / doc_id
    assets.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as folder:
        payload = Path(folder) / "pages.json"
        command = [str(VENV), str(SCRIPTS / "pdfmd" / "extract.py"), str(source), str(assets), str(payload)]
        if pages:
            command.append(pages)
        result = subprocess.run(command, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(result.stderr[-2000:] or f"extract exited {result.returncode}")
        if result.stderr:
            print(result.stderr, file=sys.stderr, end="")
        extracted = json.loads(payload.read_text(encoding="utf-8"))
    for page in extracted:
        if not page.get("needs_ocr") or page.get("skip"):
            continue
        image = page.get("image")
        if not image:
            continue
        lines = recognize(assets / image)
        lines = restore_mass_numbers(lines, page.get("layer_lines"), page.get("page_h") or 0)
        page["blocks"] = blocks_from_ocr(lines, page.get("geom"), page["page"], image)
        print(f"ocr page {page['page']}", file=sys.stderr)
    for page in extracted:
        _fix_italic(page, assets)
    for page in extracted:
        for block in page.get("blocks") or []:
            geom = block.pop("label_geom", None)
            if not geom or not block.get("file"):
                continue
            caption = scheme_caption(recognize(assets / block["file"]), geom)
            if caption:
                block["text"] = block["text"].rstrip() + "\n\n" + caption
                print(f"scheme page {page['page']}", file=sys.stderr)
    markdown = assemble(extracted, f"assets/{doc_id}")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(markdown, encoding="utf-8")
    errors, warnings = structural(markdown, assets)
    score, recall_error = recall(markdown, source, extracted)
    if recall_error:
        errors.append(recall_error)
    report = {
        "source": str(source),
        "target": str(target),
        "pages": len(extracted),
        "chars": len(markdown),
        "recall": round(score, 3),
        "errors": errors,
        "warnings": warnings,
    }
    target.with_suffix(".report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def main() -> None:
    if len(sys.argv) < 3:
        raise SystemExit("usage: pdf_to_md.py INPUT.pdf OUTPUT.md [--pages 1,2,5]")
    report = convert(Path(sys.argv[1]), Path(sys.argv[2]), _pages_arg(sys.argv))
    print(
        f"{report['target']}: {report['chars']} знаков, страниц {report['pages']}, "
        f"слов слоя {report['recall']:.0%}"
    )
    for warning in report["warnings"]:
        print("предупреждение:", warning)
    for error in report["errors"]:
        print("ошибка:", error)
    if report["errors"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
