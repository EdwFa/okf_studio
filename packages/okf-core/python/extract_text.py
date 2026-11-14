"""Extract plain text from a document for the knowledge base.

Usage: knowledge_helper.py <path> <kind>   (kind: pdf | docx)
Prints one JSON object: {"text": str, "pages": int | null}. Exits non-zero
with a short message on stderr when the file cannot be read.
"""
import json
import sys
import zipfile


def pdf_text(path):
    from pypdf import PdfReader

    reader = PdfReader(path)
    if reader.is_encrypted:
        try:
            reader.decrypt("")
        except Exception:
            raise SystemExit("PDF is password-protected")
    pages = []
    for number, page in enumerate(reader.pages, 1):
        text = (page.extract_text() or "").strip()
        if text:
            pages.append(f"<!-- page {number} -->\n{text}")
    return "\n\n".join(pages), len(reader.pages)


W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def docx_text(path):
    from lxml import etree

    with zipfile.ZipFile(path) as archive:
        if "word/document.xml" not in archive.namelist():
            raise SystemExit("Not a Word document")
        if archive.getinfo("word/document.xml").file_size > 200 * 1024 * 1024:
            raise SystemExit("Document is too large")
        root = etree.fromstring(archive.read("word/document.xml"), etree.XMLParser(resolve_entities=False, no_network=True))
    body = root.find(f"{W}body")
    blocks = []
    for node in body if body is not None else []:
        if node.tag == f"{W}p":
            line = paragraph(node)
            if line:
                blocks.append(line)
        elif node.tag == f"{W}tbl":
            rows = []
            for row in node.iter(f"{W}tr"):
                cells = [" ".join(filter(None, (paragraph(p, plain=True) for p in cell.iter(f"{W}p")))) for cell in row.findall(f"{W}tc")]
                rows.append("| " + " | ".join(cell.replace("|", "/") for cell in cells) + " |")
            if rows:
                width = rows[0].count("|") - 1
                rows.insert(1, "|" + " --- |" * max(width, 1))
                blocks.append("\n".join(rows))
    return "\n\n".join(blocks), None


def paragraph(node, plain=False):
    parts = []
    for item in node.iter():
        if item.tag == f"{W}t":
            parts.append(item.text or "")
        elif item.tag in (f"{W}tab",):
            parts.append("\t")
        elif item.tag in (f"{W}br", f"{W}cr"):
            parts.append("\n")
    text = "".join(parts).strip()
    if not text or plain:
        return text
    style = node.find(f"{W}pPr/{W}pStyle")
    name = (style.get(f"{W}val") if style is not None else "") or ""
    digits = "".join(ch for ch in name if ch.isdigit())
    if name.lower().startswith(("heading", "заголовок")) or name in {"1", "2", "3", "4"}:
        level = min(int(digits or "1"), 5)
        return "#" * (level + 1) + " " + text.replace("\n", " ")
    if name.lower() == "title":
        return "## " + text.replace("\n", " ")
    return text


def main():
    if len(sys.argv) != 3 or sys.argv[2] not in ("pdf", "docx"):
        raise SystemExit("usage: knowledge_helper.py <path> <pdf|docx>")
    text, pages = (pdf_text if sys.argv[2] == "pdf" else docx_text)(sys.argv[1])
    json.dump({"text": text, "pages": pages}, sys.stdout, ensure_ascii=False)


if __name__ == "__main__":
    main()
