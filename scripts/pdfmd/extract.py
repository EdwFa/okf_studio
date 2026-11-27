"""Read one PDF into page blocks. Runs in the project virtualenv (PyMuPDF).

Usage: extract.py <pdf> <assets-dir> <pages.json>
"""

from __future__ import annotations

import json
import os
import pickle
import re
import sys
from pathlib import Path

import numpy as np
import pymupdf

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from layout import (  # noqa: E402
    cell_text,
    clean_text,
    flow,
    heading_level,
    is_toc,
    label_list,
    markdown_table,
    mermaid,
    promote_title,
)
from page_geometry import analyze  # noqa: E402
from symbols import map_symbol  # noqa: E402


def _words(page) -> list[dict]:
    found = []
    for x0, y0, x1, y1, text, *_rest in page.get_text("words"):
        token = clean_text(map_symbol(text))
        if token:
            found.append({"x0": x0, "y0": y0, "x1": x1, "y1": y1, "text": token})
    return found


def _lines(page) -> list[dict]:
    lines = []
    for block in page.get_text("dict")["blocks"]:
        if block.get("type") != 0:
            continue
        for line in block.get("lines", []):
            parts = []
            letters = bold = 0
            for span in line["spans"]:
                raw = span["text"]
                if "Symbol" in span.get("font", "") or any(ord(ch) > 0xF000 for ch in raw):
                    raw = map_symbol(raw)
                parts.append(raw)
                count = sum(ch.isalpha() for ch in raw)
                letters += count
                if span["flags"] & 16:
                    bold += count
            text = clean_text("".join(parts))
            if not text:
                continue
            x0, y0, x1, y1 = line["bbox"]
            lines.append(
                {
                    "text": text,
                    "x": x0,
                    "x1": x1,
                    "y": y0,
                    "y1": y1,
                    "h": max(y1 - y0, 1),
                    "bold": bool(letters) and bold >= letters * 0.6,
                    "italic": "Italic" in "".join(span.get("font", "") for span in line["spans"])
                    and sum(ch.isalpha() for span in line["spans"] if "Italic" in span.get("font", "") for ch in span["text"])
                    >= max(letters, 1) * 0.35,
                }
            )
    lines.sort(key=lambda line: (line["y"], line["x"]))
    return lines


def _inside(line: dict, rect: tuple[float, float, float, float], pad: float = 2) -> bool:
    cx = line["x"] + 8
    cy = (line["y"] + line["y1"]) / 2
    x0, y0, x1, y1 = rect
    return x0 - pad <= cx <= x1 + pad and y0 - pad <= cy <= y1 + pad


def _center_in(word: dict, rect, pad: float = 1.2) -> bool:
    cx = (word["x0"] + word["x1"]) / 2
    cy = (word["y0"] + word["y1"]) / 2
    x0, y0, x1, y1 = rect
    return x0 + pad <= cx <= x1 - pad and y0 + pad <= cy <= y1 - pad


def _strip_tall_fills(text: str) -> str:
    """MuPDF segfaults on tall filled rectangles. They are shading, not rules."""
    lines = text.splitlines(keepends=True)
    out: list[str] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        rect = re.match(r"([0-9.\-]+) ([0-9.\-]+) ([0-9.\-]+) ([0-9.\-]+) re f\*\n", line)
        if rect and abs(float(rect.group(4))) > 18:
            index += 1
            continue
        if re.match(r"[0-9.\-]+ [0-9.\-]+ m\n", line):
            window = lines[index : index + 6]
            fill_at = next((pos for pos, item in enumerate(window) if "f*" in item), None)
            if fill_at is not None:
                ys = [
                    float(y)
                    for item in window[: fill_at + 1]
                    for _, y in re.findall(r"([0-9.\-]+) ([0-9.\-]+) [ml]", item)
                ]
                if ys and max(ys) - min(ys) > 18:
                    index += fill_at + 1
                    continue
        out.append(line)
        index += 1
    return "".join(out)


def _table_page(page):
    """Return a page MuPDF can scan, plus a document to close. The original stays intact."""
    raw = page.read_contents() or b""
    text = raw.decode("latin1")
    if _strip_tall_fills(text) == text:
        return page, None
    temp = pymupdf.open()
    temp.insert_pdf(page.parent, from_page=page.number, to_page=page.number)
    copy = temp[0]
    xref = copy.get_contents()[0]
    stream = copy.read_contents().decode("latin1")
    temp.update_stream(xref, _strip_tall_fills(stream).encode("latin1"))
    return temp[0], temp


def _rule_segments(page) -> tuple[list, list]:
    """Axis-aligned hairlines. A stroked line has no area, so the table finder skips it."""
    horizontal, vertical = [], []
    for drawing in page.get_drawings():
        rect = drawing["rect"]
        if rect.width > 80 and rect.height < 1.2:
            horizontal.append(rect)
        elif rect.height > 18 and rect.width < 1.2:
            vertical.append(rect)
    return horizontal, vertical


def _hairline_grids(page) -> list[dict]:
    """A ruled grid whose borders are hairline strokes, not rectangles the finder can see."""
    horizontal, vertical = _rule_segments(page)
    levels: list[float] = []
    for y in sorted({round(rect.y0, 0) for rect in horizontal}):
        if not levels or y - levels[-1] > 2:
            levels.append(float(y))
    lines = []
    for y in levels:
        segs = [rect for rect in horizontal if abs(rect.y0 - y) <= 2]
        if segs:
            lines.append((y, min(rect.x0 for rect in segs), max(rect.x1 for rect in segs)))
    grids = []
    run: list[tuple[float, float, float]] = []

    def flush() -> None:
        if len(run) < 3:
            return
        spans = [item[2] - item[1] for item in run]
        if max(spans) - min(spans) > 40:
            return
        x0, x1 = min(item[1] for item in run), max(item[2] for item in run)
        y0, y1 = run[0][0], run[-1][0]
        if y1 - y0 < 24 or x1 - x0 < 80:
            return
        upright = [
            rect
            for rect in vertical
            if rect.y0 <= y0 + 8 and rect.y1 >= y1 - 8 and x0 - 6 <= rect.x0 <= x1 + 6
        ]
        edges: list[float] = []
        for rect in sorted(upright, key=lambda item: item.x0):
            if not edges or rect.x0 - edges[-1] > 3:
                edges.append(float(rect.x0))
        if len(edges) < 2:
            return
        grids.append({"bbox": (x0, y0, x1, y1), "ys": [item[0] for item in run], "xs": edges})

    for item in lines:
        if run:
            prev = run[-1]
            joined = abs(item[1] - prev[1]) < 20 and abs(item[2] - prev[2]) < 20 and 8 < item[0] - prev[0] < 80
            if not joined:
                flush()
                run = []
        run.append(item)
    flush()
    return grids


def _covered(bbox: tuple[float, float, float, float], taken: list[tuple]) -> bool:
    cx, cy = (bbox[0] + bbox[2]) / 2, (bbox[1] + bbox[3]) / 2
    return any(rect[0] <= cx <= rect[2] and rect[1] <= cy <= rect[3] for rect in taken)


def _grid_table(page_words: list[dict], grid: dict) -> dict | None:
    ys, xs = grid["ys"], grid["xs"]
    rows = []
    for top, bottom in zip(ys, ys[1:]):
        cells = []
        for left, right in zip(xs, xs[1:]):
            chosen = [
                word
                for word in page_words
                if left - 1 <= (word["x0"] + word["x1"]) / 2 <= right + 1
                and top - 2 <= (word["y0"] + word["y1"]) / 2 <= bottom + 2
            ]
            cells.append(cell_text(chosen))
        rows.append(cells)
    text = markdown_table(rows)
    if not text:
        return None
    x0, y0, x1, y1 = grid["bbox"]
    return {"type": "table", "text": text, "y": y0, "bbox": [x0, y0, x1, y1]}


def _mupdf_tables(source) -> list[dict]:
    """find_tables segfaults on a few pages. Run it in a child and keep plain cells."""
    read_fd, write_fd = os.pipe()
    pid = os.fork()
    if pid == 0:
        os.close(read_fd)
        try:
            payload = []
            for table in source.find_tables().tables:
                raw_rows = [
                    [cell if isinstance(cell, str) else "" for cell in (row or [])]
                    for row in (table.extract() or [])
                ]
                row_boxes = [
                    [[float(value) for value in cell] if cell else None for cell in row.cells]
                    for row in table.rows
                ]
                tops = [float(cell[1]) for cell in table.cells if cell]
                payload.append(
                    {
                        "raw_rows": raw_rows,
                        "row_boxes": row_boxes,
                        "y0": min(tops) if tops else float(table.bbox[1]),
                        "bbox": [float(value) for value in table.bbox],
                    }
                )
            data = pickle.dumps(payload, protocol=4)
            while data:
                sent = os.write(write_fd, data)
                data = data[sent:]
            os.close(write_fd)
            os._exit(0)
        except Exception:
            os.close(write_fd)
            os._exit(1)
    os.close(write_fd)
    chunks = []
    try:
        while True:
            chunk = os.read(read_fd, 1 << 20)
            if not chunk:
                break
            chunks.append(chunk)
    finally:
        os.close(read_fd)
    _, status = os.waitpid(pid, 0)
    if not os.WIFEXITED(status) or os.WEXITSTATUS(status) != 0 or not chunks:
        return []
    try:
        return pickle.loads(b"".join(chunks))
    except Exception:
        return []


def _tables(page, words: list[dict]) -> list[dict]:
    blocks = []
    source, temp = _table_page(page)
    try:
        for table in _mupdf_tables(source):
            raw_rows = table["raw_rows"]
            flat = " ".join(cell or "" for row in raw_rows for cell in row)
            if "оглавление" in flat.lower() or flat.count("....") >= 4 or len(re.findall(r"…{2,}", flat)) >= 4:
                continue
            rows = []
            for raw, boxes in zip(raw_rows, table["row_boxes"]):
                cells = []
                for index, raw_cell in enumerate(raw):
                    box = boxes[index] if index < len(boxes) else None
                    chosen = [word for word in words if box is not None and _center_in(word, box)]
                    cells.append(cell_text(chosen) if chosen else clean_text(raw_cell or ""))
                rows.append(cells)
            grid = markdown_table(rows)
            if not grid:
                continue
            blocks.append({"type": "table", "text": grid, "y": table["y0"], "bbox": table["bbox"]})
        taken = [tuple(block["bbox"]) for block in blocks]
        for grid in _hairline_grids(page):
            if _covered(grid["bbox"], taken):
                continue
            block = _grid_table(words, grid)
            if block is None:
                continue
            blocks.append(block)
            taken.append(tuple(block["bbox"]))
        return blocks
    finally:
        if temp is not None:
            temp.close()


def _content_images(page) -> list[dict]:
    images = []
    area = page.rect.width * page.rect.height
    for info in page.get_image_info():
        box = info["bbox"]
        width = box[2] - box[0]
        height = box[3] - box[1]
        if width < 70 or height < 70:
            continue
        if width * height > area * 0.82:
            continue
        # A card frame runs the full page height but stays under the area cutoff, then hides the text.
        if height > page.rect.height * 0.92:
            continue
        images.append({"bbox": [float(v) for v in box], "y": float(box[1])})
    return _join_tiles(images)


def _join_tiles(images: list[dict], gap: float = 1.5) -> list[dict]:
    """Bands of one figure are stored as separate images. Keep them as one picture."""
    groups = [{"bbox": list(image["bbox"]), "y": image["y"]} for image in images]
    changed = True
    while changed:
        changed = False
        index = 0
        while index < len(groups):
            other = index + 1
            while other < len(groups):
                left, right = groups[index]["bbox"], groups[other]["bbox"]
                apart = (
                    left[2] < right[0] - gap
                    or right[2] < left[0] - gap
                    or left[3] < right[1] - gap
                    or right[3] < left[1] - gap
                )
                if apart:
                    other += 1
                    continue
                groups[index]["bbox"] = [
                    min(left[0], right[0]),
                    min(left[1], right[1]),
                    max(left[2], right[2]),
                    max(left[3], right[3]),
                ]
                groups[index]["y"] = groups[index]["bbox"][1]
                groups.pop(other)
                changed = True
            index += 1
    return groups


def _node_cover(nodes: list, width: int, height: int) -> float:
    if not nodes:
        return 0.0
    x0 = min(node[0] for node in nodes)
    y0 = min(node[1] for node in nodes)
    x1 = max(node[2] for node in nodes)
    y1 = max(node[3] for node in nodes)
    return (x1 - x0) * (y1 - y0) / max(width * height, 1)


def _scattered_labels(lines: list[dict]) -> bool:
    """Short labels sitting in many columns are a flowchart, not a paragraph."""
    rows: list[list[dict]] = []
    for line in sorted(lines, key=lambda item: (item["y"], item["x"])):
        text = clean_text(line["text"])
        if not text or re.fullmatch(r"\d{1,3}", text):
            continue
        if rows and abs(line["y"] - rows[-1][0]["y"]) <= 3.5:
            rows[-1].append({**line, "text": text})
        else:
            rows.append([{**line, "text": text}])
    short = long = 0
    gaps = []
    for row in rows:
        row.sort(key=lambda item: item["x"])
        groups = [[row[0]]]
        for prev, nxt in zip(row, row[1:]):
            if nxt["x"] - prev.get("x1", prev["x"]) > 28:
                groups.append([nxt])
                gaps.append((prev.get("x1", prev["x"]) + nxt["x"]) / 2)
            else:
                groups[-1].append(nxt)
        for group in groups:
            if len(" ".join(item["text"] for item in group)) <= 48:
                short += 1
            else:
                long += 1
    buckets = len({round(gap / 30) * 30 for gap in gaps})
    codes = len(re.findall(r"\d{4}/\d", " ".join(line["text"] for line in lines)))
    return short >= 18 and long <= 12 and buckets >= 3 and codes < 4 and short > long * 3


def _scheme_page(page, lines: list[dict]) -> bool:
    if _scattered_labels(lines):
        return True
    texts = [clean_text(line["text"]) for line in lines if clean_text(line["text"])]
    texts = [text for text in texts if not re.fullmatch(r"\d{1,3}", text)]
    if not 8 <= len(texts) <= 24:
        return False
    ordered = sorted(len(text) for text in texts)
    if ordered[len(ordered) // 2] > 22:
        return False
    pix = page.get_pixmap(dpi=110, colorspace=pymupdf.csGRAY, alpha=False)
    gray = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.h, pix.w)
    return len(analyze(gray)["nodes"]) >= 3


def _pixmap_gray(doc, page) -> np.ndarray | None:
    images = page.get_images()
    pix = None
    if len(images) == 1:
        pix = pymupdf.Pixmap(doc, images[0][0])
        if pix.w < 600 or pix.h < 600:
            pix = None
    if pix is None and _content_images(page):
        return None
    if pix is None:
        if len(page.get_text("words")) > 40:
            return None
        pix = page.get_pixmap(dpi=140, colorspace=pymupdf.csGRAY)
    if pix.alpha:
        pix = pymupdf.Pixmap(pix, 0)
    if pix.n > 1:
        pix = pymupdf.Pixmap(pymupdf.csGRAY, pix)
    return np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.h, pix.w)


def _figure_gray(doc, page, bbox: list[float]) -> np.ndarray:
    clip = pymupdf.Rect(bbox)
    pix = page.get_pixmap(dpi=120, clip=clip, colorspace=pymupdf.csGRAY, alpha=False)
    gray = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.h, pix.w)
    # Figure strokes are often lighter than body text. Pull them into the detector range.
    return np.clip(gray.astype(np.int16) - 80, 0, 255).astype(np.uint8)


def _save_clip(page, bbox, path: Path, pad: float = 6) -> None:
    rect = pymupdf.Rect(bbox)
    rect.x0 = max(page.rect.x0, rect.x0 - pad)
    rect.y0 = max(page.rect.y0, rect.y0 - pad)
    rect.x1 = min(page.rect.x1, rect.x1 + pad)
    rect.y1 = min(page.rect.y1, rect.y1 + pad)
    pix = page.get_pixmap(dpi=140, clip=rect, alpha=False)
    pix.save(path)


def _grow_figure(page, bbox: list[float]) -> list[float]:
    """A flowchart is often one image plus the boxes drawn under it. Keep both."""
    box = [float(v) for v in bbox]
    page_area = page.rect.width * page.rect.height
    changed = True
    while changed:
        changed = False
        for drawing in page.get_drawings():
            rect = drawing["rect"]
            if rect.width < 10 or rect.height < 10 or rect.width * rect.height > page_area * 0.45:
                continue
            if rect.x1 < box[0] - 8 or rect.x0 > box[2] + 8 or rect.y1 < box[1] - 8 or rect.y0 > box[3] + 8:
                continue
            grown = [min(box[0], rect.x0), min(box[1], rect.y0), max(box[2], rect.x1), max(box[3], rect.y1)]
            if grown != box:
                box = grown
                changed = True
    box[0] = max(page.rect.x0, box[0])
    box[1] = max(page.rect.y0, box[1])
    box[2] = min(page.rect.x1, box[2])
    box[3] = min(page.rect.y1, box[3])
    return box


def _diagram(doc, page, words, lines, assets: Path, page_no: int, gray: np.ndarray, origin, scale, clip=None) -> dict | None:
    geom = analyze(gray)
    nodes = geom["nodes"]
    edges = geom["edges"]
    if len(nodes) < 3 or not edges:
        return None
    sx, sy = scale
    ox, oy = origin

    def to_pdf(box):
        return (box[0] / sx + ox, box[1] / sy + oy, box[2] / sx + ox, box[3] / sy + oy)

    pdf_nodes = [to_pdf(node) for node in nodes]
    labels = []
    for rect in pdf_nodes:
        chosen = [word for word in words if _center_in(word, rect, pad=0)]
        labels.append(cell_text(chosen))
    long = [label for label in labels if len(label) > 180]
    if long or sum(len(label) > 40 for label in labels) > len(labels) / 2:
        return None
    graph = mermaid(labels, [tuple(edge) for edge in edges])
    caption = label_list(labels) if not graph else ""
    if not graph and not caption:
        return None
    union = [
        min(rect[0] for rect in pdf_nodes),
        min(rect[1] for rect in pdf_nodes),
        max(rect[2] for rect in pdf_nodes),
        max(rect[3] for rect in pdf_nodes),
    ]
    # A partial crop drops branches. The whole figure is the scheme.
    if clip is not None:
        clip_area = max((clip[2] - clip[0]) * (clip[3] - clip[1]), 1)
        cover = (union[2] - union[0]) * (union[3] - union[1]) / clip_area
        if cover < 0.72:
            return None
        union = list(clip)
    else:
        union = [page.rect.x0, page.rect.y0, page.rect.x1, page.rect.y1]
    name = f"p{page_no:03d}-scheme.png"
    _save_clip(page, union, assets / name, pad=10)
    pieces = [f"![Схема, страница {page_no}]({name})"]
    if graph:
        pieces.append(graph)
    elif caption:
        pieces.append(caption)
    return {
        "type": "figure",
        "text": "\n\n".join(pieces),
        "y": union[1],
        "bbox": union,
        "file": name,
    }


def _mark_scan(doc, page, assets: Path, page_no: int, record: dict) -> None:
    record["needs_ocr"] = True
    name = f"p{page_no:03d}-page.png"
    page.get_pixmap(dpi=140, alpha=False).save(assets / name)
    record["image"] = name
    gray = _pixmap_gray(doc, page)
    if gray is not None:
        record["geom"] = analyze(gray)


def _vector_glyphs(page, bbox: list[float]) -> bool:
    """Many drawings inside a table usually means digits drawn as vectors, not text."""
    x0, y0, x1, y1 = bbox
    count = 0
    for drawing in page.get_drawings():
        rect = drawing["rect"]
        if rect.x0 >= x0 - 2 and rect.y0 >= y0 - 2 and rect.x1 <= x1 + 2 and rect.y1 <= y1 + 2:
            count += 1
            if count > 60:
                return True
    return False


def _full_image(page) -> bool:
    area = page.rect.width * page.rect.height
    return any(
        (info["bbox"][2] - info["bbox"][0]) * (info["bbox"][3] - info["bbox"][1]) > area * 0.82
        for info in page.get_image_info()
    )


def extract_page(doc, index: int, assets: Path) -> dict:
    page = doc[index]
    page_no = index + 1
    words = _words(page)
    lines = _lines(page)
    record = {
        "page": page_no,
        "skip": None,
        "needs_ocr": False,
        "blocks": [],
        "image": None,
    }
    if is_toc([line["text"] for line in lines]):
        # The abbreviation list sometimes starts under the contents on the same page.
        idx = None
        for i, line in enumerate(lines):
            name = clean_text(line["text"]).lower().replace("ё", "е")
            if name.startswith("список сокращений") and not re.search(r"\.{4,}|…", line["text"]):
                idx = i
                break
        tail = lines[idx + 1 :] if idx is not None else []
        definitions = sum(
            1
            for line in tail
            if re.search(r"\s[-–—]\s", line["text"]) and not re.search(r"\.{4,}|…", line["text"])
        )
        if definitions < 2:
            record["skip"] = "toc"
            return record
        lines = lines[idx:]

    mixed = sum(
        1
        for word in words
        if len(word["text"]) >= 4 and any(ch.isdigit() for ch in word["text"]) and any(ch.isalpha() for ch in word["text"])
    )
    # Bibliography whose font maps Latin letters onto Cyrillic.
    if mixed >= 12 and _full_image(page):
        _mark_scan(doc, page, assets, page_no, record)
        return record

    # Title pages carry the approval stamps in the text layer. Read the scan instead.
    if _full_image(page) and any("год утверждения" in line["text"].lower() for line in lines):
        _mark_scan(doc, page, assets, page_no, record)
        return record

    good = [word for word in words if len(word["text"]) >= 3]
    tables = _tables(page, words) if good else []
    taken = [tuple(table["bbox"]) for table in tables]
    snapshot = 0
    for table in tables:
        if len(page.get_drawings()) > 150 and _vector_glyphs(page, table["bbox"]):
            snapshot += 1
            name = f"p{page_no:03d}-table{snapshot}.png"
            _save_clip(page, table["bbox"], assets / name, pad=2)
            table["text"] = f"![Таблица, страница {page_no}]({name})\n\n" + table["text"]
            table["file"] = name

    figures = []
    for image in _content_images(page):
        bbox = _grow_figure(page, image["bbox"])
        gray = _figure_gray(doc, page, bbox)
        sx = gray.shape[1] / max(bbox[2] - bbox[0], 1)
        sy = gray.shape[0] / max(bbox[3] - bbox[1], 1)
        diagram = _diagram(
            doc, page, words, lines, assets, page_no, gray, (bbox[0], bbox[1]), (sx, sy), clip=bbox
        )
        if diagram:
            figures.append(diagram)
            taken.append(tuple(diagram["bbox"]))
            continue
        geom = analyze(gray)
        kind = "Схема" if len(geom["nodes"]) >= 3 and geom["edges"] and not geom["tables"] else "Рисунок"
        name = f"p{page_no:03d}-fig{len(figures) + 1}.png"
        _save_clip(page, bbox, assets / name, pad=8)
        block = {
            "type": "figure",
            "text": f"![{kind}, страница {page_no}]({name})",
            "y": bbox[1],
            "bbox": bbox,
            "file": name,
        }
        # Mermaid only when the detected boxes cover the picture. A fragment is not the scheme.
        if (
            len(geom["nodes"]) >= 4
            and len(geom["edges"]) >= len(geom["nodes"]) - 1
            and _node_cover(geom["nodes"], gray.shape[1], gray.shape[0]) >= 0.72
        ):
            block["label_geom"] = geom
        figures.append(block)
        taken.append(tuple(bbox))

    if not figures and _full_image(page) and not tables and len(good) >= 12:
        gray = _pixmap_gray(doc, page)
        if gray is not None:
            sx = gray.shape[1] / page.rect.width
            sy = gray.shape[0] / page.rect.height
            diagram = _diagram(doc, page, words, lines, assets, page_no, gray, (0, 0), (sx, sy))
            if diagram:
                figures.append(diagram)
                taken.append(tuple(diagram["bbox"]))

    if not figures and not tables and _full_image(page) and _scheme_page(page, lines):
        name = f"p{page_no:03d}-scheme.png"
        page.get_pixmap(dpi=130, alpha=False).save(assets / name)
        figures.append(
            {
                "type": "figure",
                "text": f"![Схема, страница {page_no}]({name})",
                "y": page.rect.height * 0.2,
                "file": name,
            }
        )
        lines = [line for line in lines if heading_level(line["text"], False) is not None]

    if len(good) < 12 and not figures and not tables:
        _mark_scan(doc, page, assets, page_no, record)
        return record

    kept = [line for line in lines if not any(_inside(line, rect) for rect in taken)]
    italic_noise = re.compile(r"эю|профш|чъ|мч\b|тяж\s+е")
    if any(line.get("italic") and italic_noise.search(line["text"]) for line in kept):
        record["italic_fix"] = True
        record["page_h"] = page.rect.height
        record["image"] = f"p{page_no:03d}-page.png"
        page.get_pixmap(dpi=140, alpha=False).save(assets / record["image"])
        record["lines"] = [
            {
                "text": line["text"],
                "x": line["x"],
                "y": line["y"],
                "y1": line["y1"],
                "h": line["h"],
                "bold": line.get("bold", False),
                "italic": bool(line.get("italic")),
            }
            for line in kept
        ]
    blocks = flow(kept, page.rect.height)
    blocks.extend(tables)
    blocks.extend(figures)
    blocks.sort(key=lambda block: block["y"])
    for block in blocks:
        block.pop("bbox", None)
    record["blocks"] = promote_title(blocks)
    return record


def main() -> None:
    source, assets, target = sys.argv[1:4]
    folder = Path(assets)
    folder.mkdir(parents=True, exist_ok=True)
    doc = pymupdf.open(source)
    if doc.is_encrypted:
        doc.authenticate("")
    pages = []
    only = {int(item) for item in sys.argv[4].split(",")} if len(sys.argv) > 4 else None
    for index in range(doc.page_count):
        if only and index + 1 not in only:
            continue
        pages.append(extract_page(doc, index, folder))
        print(f"extract {index + 1}/{doc.page_count}", file=sys.stderr)
    Path(target).write_text(json.dumps(pages, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    main()
