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
    garbled_span,
    flow,
    heading_level,
    is_toc,
    label_list,
    markdown_table,
    split_stacked_lines,
    mermaid,
    promote_title,
    tracked_figure,
)
from page_geometry import analyze  # noqa: E402
from symbols import map_symbol  # noqa: E402


def _words(page) -> list[dict]:
    spans = []
    for block in page.get_text("dict")["blocks"]:
        if block.get("type") != 0:
            continue
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                spans.append((span["bbox"], span.get("font", "")))
    found = []
    for x0, y0, x1, y1, text, *_rest in page.get_text("words"):
        font = ""
        cx = (x0 + x1) / 2
        cy = (y0 + y1) / 2
        for bbox, name in spans:
            # The word center, so a Wingdings arrow is not claimed by the text span on its left.
            if bbox[0] - 0.4 <= cx <= bbox[2] + 0.4 and bbox[1] - 1 <= cy <= bbox[3] + 1:
                font = name
                break
        token = clean_text(map_symbol(text, font))
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
                font = span.get("font", "")
                if any(ord(ch) > 0xE000 for ch in raw) or any(
                    name in font for name in ("Symbol", "Wingding", "Webding", "OpenSymbol")
                ):
                    raw = map_symbol(raw, font)
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
                    "garbled": garbled_span(text),
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
        # A hairline rule is a tall fill only a point wide. A shaded cell is wide.
        if rect and abs(float(rect.group(4))) > 18 and abs(float(rect.group(3))) > 3:
            index += 1
            continue
        if re.match(r"[0-9.\-]+ [0-9.\-]+ m\n", line):
            window = lines[index : index + 6]
            fill_at = next((pos for pos, item in enumerate(window) if "f*" in item), None)
            if fill_at is not None:
                xs = [
                    float(x)
                    for item in window[: fill_at + 1]
                    for x, _y in re.findall(r"([0-9.\-]+) ([0-9.\-]+) [ml]", item)
                ]
                ys = [
                    float(y)
                    for item in window[: fill_at + 1]
                    for _x, y in re.findall(r"([0-9.\-]+) ([0-9.\-]+) [ml]", item)
                ]
                wide = xs and max(xs) - min(xs) > 3
                if ys and max(ys) - min(ys) > 18 and wide:
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


def _table_payload(source, strategy: str | None) -> list[dict]:
    kwargs = {}
    if strategy:
        kwargs = {"vertical_strategy": strategy, "horizontal_strategy": strategy}
    payload = []
    for table in source.find_tables(**kwargs).tables:
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
    return payload


def _fork_tables(source, strategy: str | None) -> list[dict]:
    """find_tables segfaults on a few pages. Run it in a child and keep plain cells."""
    read_fd, write_fd = os.pipe()
    pid = os.fork()
    if pid == 0:
        os.close(read_fd)
        try:
            data = pickle.dumps(_table_payload(source, strategy), protocol=4)
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


def _cell_norm(rows: list[list[str]]) -> str:
    return re.sub(r"\s+", "", " ".join(cell or "" for row in rows for cell in row))


def _empty_share(rows: list[list[str]]) -> float:
    total = sum(len(row) for row in rows)
    if not total:
        return 0.0
    empty = sum(1 for row in rows for cell in row if not (cell or "").strip())
    return empty / total


def _region_overlap(a: list[float], b: list[float]) -> float:
    x0, y0, x1, y1 = a
    X0, Y0, X1, Y1 = b
    ix0, iy0 = max(x0, X0), max(y0, Y0)
    ix1, iy1 = min(x1, X1), min(y1, Y1)
    inter = max(0.0, ix1 - ix0) * max(0.0, iy1 - iy0)
    if inter <= 0:
        return 0.0
    area_a = max(0.0, x1 - x0) * max(0.0, y1 - y0)
    area_b = max(0.0, X1 - X0) * max(0.0, Y1 - Y0)
    union = area_a + area_b - inter
    return inter / union if union else 0.0


def _looks_fragmented(table: dict) -> bool:
    rows = table["raw_rows"]
    cols = max((len(row) for row in rows), default=0)
    return len(rows) >= 12 and cols >= 8 and _empty_share(rows) >= 0.5


def _strict_is_real_grid(loose: dict, tight: dict) -> bool:
    """Filled cell backgrounds split one ruled cell into many empty ones.

    lines_strict follows the strokes. Use it only when it is the same region,
    much coarser, and it still holds the same letters.
    """
    if _region_overlap(loose["bbox"], tight["bbox"]) < 0.8:
        return False
    drows, srows = loose["raw_rows"], tight["raw_rows"]
    if len(srows) < 2:
        return False
    dcols = max((len(row) for row in drows), default=0)
    scols = max((len(row) for row in srows), default=0)
    if scols < 2 or dcols < scols + 3 or len(drows) < len(srows) * 3:
        return False
    if _empty_share(drows) < 0.55:
        return False
    dtext, stext = _cell_norm(drows), _cell_norm(srows)
    if not dtext or len(stext) < 0.75 * len(dtext) or len(stext) > 1.35 * len(dtext):
        return False
    return True


def _mupdf_tables(source) -> list[dict]:
    found = _fork_tables(source, None)
    if not found or not any(_looks_fragmented(table) for table in found):
        return found
    strict = _fork_tables(source, "lines_strict")
    if not strict:
        return found
    used: set[int] = set()
    chosen = []
    for table in found:
        replacement = None
        for index, item in enumerate(strict):
            if index in used or not _strict_is_real_grid(table, item):
                continue
            replacement = item
            used.add(index)
            break
        chosen.append(replacement or table)
    return chosen


def _column_cuts(row_boxes: list, verticals: list) -> list[float]:
    """A column rule find_tables stepped over, so two headers share one cell.

    The rule is a hairline inside the cell and it repeats down the grid.
    """
    edges = _column_edges(row_boxes)
    found: list[float] = []
    for rect in verticals:
        x = round(float(rect.x0), 1)
        if any(abs(x - edge) <= 4 for edge in edges):
            continue
        mid = (float(rect.y0) + float(rect.y1)) / 2
        for row in row_boxes:
            if any(
                cell
                and cell[0] + 8 < x < cell[2] - 8
                and cell[1] - 1 <= mid <= cell[3] + 1
                for cell in row
            ):
                found.append(x)
                break
    found.sort()
    grouped: list[list[float]] = []
    for x in found:
        if grouped and abs(x - grouped[-1][0]) <= 2:
            grouped[-1][1] += 1
        else:
            grouped.append([x, 1])
    return [x for x, count in grouped if count >= 2]


def _column_edges(row_boxes: list) -> list[float]:
    raw = []
    for row in row_boxes:
        for cell in row:
            if not cell:
                continue
            raw.extend((float(cell[0]), float(cell[2])))
    if not raw:
        return []
    raw.sort()
    edges = [raw[0]]
    for value in raw[1:]:
        if value - edges[-1] > 3:
            edges.append(value)
    return edges


def _clipped_rows(page, bbox: list[float], row_boxes: list, words: list[dict]) -> tuple[list[list[str]], list[list[str]], list[float]]:
    """A row whose top or bottom border falls off the page is missing from find_tables.

    The rulings still meet the table edge. Read that band back into the grid.
    """
    edges = _column_edges(row_boxes)
    if len(edges) < 2:
        return [], [], bbox
    # Rules are often several rectangles inside one path. The path's union is the whole table.
    horizontal, vertical = _stroke_rules(page)
    x0, y0, x1, y1 = bbox

    def near(rect, edge: float) -> bool:
        return abs(rect.x0 - edge) <= 4

    def band(at_top: bool) -> tuple[float, float] | None:
        picked = []
        for rect in vertical:
            if not any(near(rect, edge) for edge in edges):
                continue
            if at_top and abs(rect.y1 - y0) <= 4 and rect.y0 < y0 - 4:
                picked.append(rect)
            if not at_top and abs(rect.y0 - y1) <= 4 and rect.y1 > y1 + 4:
                picked.append(rect)
        if not any(near(rect, edges[0]) for rect in picked):
            return None
        if not any(near(rect, edges[-1]) for rect in picked):
            return None
        if at_top:
            starts = [rect.y0 for rect in picked]
            start = min(starts) if max(starts) - min(starts) <= 8 else max(starts)
            span = (start, y0)
        else:
            ends = [rect.y1 for rect in picked]
            end = max(ends) if max(ends) - min(ends) <= 8 else min(ends)
            span = (y1, end)
        if not 8 <= span[1] - span[0] <= 160:
            return None
        return span

    def rows_in(top: float, bottom: float) -> list[list[str]]:
        cuts = [top]
        for rect in horizontal:
            mid = (rect.y0 + rect.y1) / 2
            width = edges[-1] - edges[0]
            if top + 6 < mid < bottom - 6 and rect.x1 - rect.x0 > width * 0.6:
                cuts.append(mid)
        cuts.append(bottom)
        cuts = sorted(set(cuts))
        built = []
        for upper, lower in zip(cuts, cuts[1:]):
            if lower - upper < 8:
                continue
            cells = []
            for left, right in zip(edges, edges[1:]):
                chosen = [
                    word
                    for word in words
                    if left - 1 <= (word["x0"] + word["x1"]) / 2 <= right + 1
                    and upper - 1 <= (word["y0"] + word["y1"]) / 2 <= lower + 1
                ]
                cells.append(cell_text(chosen))
            if sum(ch.isalpha() for cell in cells for ch in cell) < 8:
                continue
            built.append(cells)
        return built

    above: list[list[str]] = []
    below: list[list[str]] = []
    grown = list(bbox)
    upper = band(True)
    if upper:
        above = rows_in(*upper)
        if above:
            grown[1] = min(grown[1], upper[0])
    lower = band(False)
    if lower:
        below = rows_in(*lower)
        if below:
            grown[3] = max(grown[3], lower[1])
    return above, below, grown


def _orphan_numbered_grid(page, words: list[dict], taken: list[tuple]) -> dict | None:
    """Rows of a numbered scale whose top border sits above the page.

    find_tables then drops the whole fragment, including the rows that are
    fully on the page under it. A scale that already meets another table is
    handled with that table, not started again here.
    """
    vertical = []
    horizontal = []
    for drawing in page.get_drawings():
        rect = drawing["rect"]
        if rect.width < 1.5 and 8 < rect.height < 80:
            vertical.append(rect)
        elif rect.height < 1.5 and rect.width > 40:
            horizontal.append(rect)
    starters = [rect for rect in vertical if rect.y0 < -1]
    if len(starters) < 2:
        return None
    bottom = max(rect.y1 for rect in starters)
    if any(abs(bottom - rect[1]) <= 6 for rect in taken):
        return None
    top = min(rect.y0 for rect in starters)
    xs = sorted({round(rect.x0, 1) for rect in starters if abs(rect.y1 - bottom) <= 3})
    if len(xs) < 2:
        return None

    def right_of(edge: float) -> float:
        # The rule is often two segments, split by the column line. Take the far end.
        reach = xs[-1]
        for rect in horizontal:
            mid = (rect.y0 + rect.y1) / 2
            if abs(mid - edge) <= 3 and rect.x1 > xs[0] + 20:
                reach = max(reach, rect.x1)
        return reach

    spans = [(top, bottom)]
    cursor = bottom
    while len(spans) < 6:
        following = [
            rect
            for rect in vertical
            if abs(rect.y0 - cursor) <= 4 and rect.y1 > cursor + 8 and any(abs(rect.x0 - edge) <= 4 for edge in xs)
        ]
        if len({round(rect.x0, 1) for rect in following}) < 2:
            break
        nxt = min(rect.y1 for rect in following)
        if any(rect[1] <= (cursor + nxt) / 2 <= rect[3] for rect in taken):
            break
        spans.append((cursor, nxt))
        cursor = nxt
    edges = xs + ([right_of(spans[0][1])] if right_of(spans[0][1]) > xs[-1] + 15 else [])
    rows = []
    for upper, lower in spans:
        cells = []
        for left, right in zip(edges, edges[1:]):
            chosen = [
                word
                for word in words
                if left - 1 <= (word["x0"] + word["x1"]) / 2 <= right + 1
                and upper - 1 <= (word["y0"] + word["y1"]) / 2 <= lower + 1
            ]
            cells.append(cell_text(chosen))
        rows.append(cells)
    if len(rows) < 2 or len(rows[0]) < 2 or not re.fullmatch(r"\d{1,2}", rows[0][0].strip()):
        return None
    if not all(re.fullmatch(r"\d{1,2}", row[0].strip()) for row in rows):
        return None
    grid = markdown_table(rows)
    if not grid:
        return None
    bbox = [edges[0], spans[0][0], edges[-1], spans[-1][1]]
    return {"type": "table", "text": grid, "y": bbox[1], "bbox": bbox}


def _code_box(page, words: list[dict], taken: list[tuple]) -> dict | None:
    """A framed list of names and ICD-O codes with no internal rules.

    The names and the codes share a line but sit in two columns, so a plain
    reading joins them into one paragraph.
    """
    vertical = []
    horizontal = []
    for drawing in page.get_drawings():
        rect = drawing["rect"]
        if rect.width < 1.5 and rect.height > 80:
            vertical.append(rect)
        elif rect.height < 1.5 and rect.width > 200:
            horizontal.append(rect)
    boxes = []
    for left in vertical:
        for right in vertical:
            if right.x0 < left.x0 + 180:
                continue
            if abs(left.y0 - right.y0) > 4 or abs(left.y1 - right.y1) > 4:
                continue
            top = next(
                (
                    rect
                    for rect in horizontal
                    if abs(rect.y0 - left.y0) <= 4 and rect.x0 <= left.x0 + 4 and rect.x1 >= right.x0 - 4
                ),
                None,
            )
            if top is None:
                continue
            boxes.append((left.x0, left.y0, right.x0, left.y1))
    for x0, y0, x1, y1 in boxes:
        inside = [
            word
            for word in words
            if x0 - 2 <= (word["x0"] + word["x1"]) / 2 <= x1 + 2 and y0 - 2 <= word["y0"] <= y1
        ]
        codes = [word for word in inside if re.fullmatch(r"\d{4}/\d", word["text"])]
        if len(codes) < 4:
            continue
        code_x = sorted(word["x0"] for word in codes)[len(codes) // 2]
        if sum(abs(word["x0"] - code_x) < 25 for word in codes) < 4:
            continue
        bbox = [x0, y0, x1, y1]
        if _covered(bbox, taken):
            continue
        heights = sorted(word["y0"] for word in inside)
        tol = 3.0
        lines: list[list[dict]] = []
        for word in sorted(inside, key=lambda item: (item["y0"], item["x0"])):
            if lines and abs(word["y0"] - lines[-1][0]["y0"]) <= tol:
                lines[-1].append(word)
            else:
                lines.append([word])
        rows = []
        for line in lines:
            line.sort(key=lambda item: item["x0"])
            right = max(item["x1"] for item in line)
            has_code = any(re.fullmatch(r"\d{4}/\d", item["text"]) for item in line)
            if not has_code and right > x1 - 40:
                break
            name = cell_text(
                [
                    item
                    for item in line
                    if item["text"] not in {"ICD-O", "code"} and not re.fullmatch(r"\d{4}/\d", item["text"])
                ]
            )
            code = " ".join(item["text"] for item in line if re.fullmatch(r"\d{4}/\d", item["text"]))
            if not name and not code:
                continue
            rows.append([name, code])
            last_y = max(item["y1"] for item in line)
        if sum(bool(row[1]) for row in rows) < 4:
            continue
        grid = markdown_table([["Опухоль", "ICD-O"], *rows])
        if not grid:
            return None
        return {"type": "table", "text": grid, "y": y0, "bbox": [x0, y0, x1, last_y + 2]}
    return None


def _ruled_rows(page, words: list[dict], taken: list[tuple]) -> list[dict]:
    """One ruled row that find_tables skips because a table needs two rows.

    The first cell is a number, so a numbered scale can take the row back.
    """
    vertical = []
    horizontal = []
    for drawing in page.get_drawings():
        rect = drawing["rect"]
        if rect.width < 1.5 and 12 < rect.height < 90:
            vertical.append(rect)
        elif rect.height < 1.5 and rect.width > 80:
            horizontal.append(rect)
    groups: list[list] = []
    for rect in vertical:
        for group in groups:
            if abs(rect.y0 - group[0].y0) <= 3 and abs(rect.y1 - group[0].y1) <= 3:
                group.append(rect)
                break
        else:
            groups.append([rect])
    found = []
    for group in groups:
        if len(group) < 3:
            continue
        top = min(rect.y0 for rect in group)
        bottom = max(rect.y1 for rect in group)
        xs = sorted({round(rect.x0, 1) for rect in group})
        if xs[-1] - xs[0] < 120:
            continue
        span = xs[-1] - xs[0]

        def closed(edge: float) -> bool:
            return any(
                abs((rect.y0 + rect.y1) / 2 - edge) <= 3 and rect.x1 - rect.x0 > span * 0.5
                for rect in horizontal
            )

        if not closed(top) or not closed(bottom):
            continue
        bbox = [xs[0], top, xs[-1], bottom]
        if _covered(bbox, taken):
            continue
        cells = []
        for left, right in zip(xs, xs[1:]):
            chosen = [
                word
                for word in words
                if left - 1 <= (word["x0"] + word["x1"]) / 2 <= right + 1
                and top - 1 <= (word["y0"] + word["y1"]) / 2 <= bottom + 1
            ]
            cells.append(cell_text(chosen))
        if not re.fullmatch(r"\d{1,2}\.?", cells[0].strip()):
            continue
        if sum(ch.isalpha() for cell in cells for ch in cell) < 8:
            continue
        text = "| " + " | ".join(cells) + " |\n| " + " | ".join(["---"] * len(cells)) + " |"
        found.append({"type": "table", "text": text, "y": top, "bbox": bbox})
    return found


def _collapse_unruled_band(page, bbox: list[float], rows: list[list[str]]) -> list[str] | None:
    """find_tables splits one ruled row into a line per text line when the row has no inner rules.

    That happens to the row that starts at the top edge of the next page. Join the lines back.
    """
    if len(rows) < 2:
        return None
    x0, y0, x1, y1 = bbox
    verticals = []
    for drawing in page.get_drawings():
        rect = drawing["rect"]
        if rect.width < 1.5 and rect.height > 20:
            if rect.y0 <= y0 + 8 and rect.y1 >= y1 - 8 and x0 - 12 <= rect.x0 <= x1 + 12:
                verticals.append(rect)
        elif rect.height < 1.5 and rect.width > (x1 - x0) * 0.5:
            mid = (rect.y0 + rect.y1) / 2
            if y0 + 6 < mid < y1 - 6:
                return None
    if len(verticals) < 3 or min(rect.y0 for rect in verticals) > 8:
        return None
    width = max(len(row) for row in rows)
    joined = []
    for col in range(width):
        parts = [row[col].strip() for row in rows if col < len(row) and row[col].strip()]
        joined.append(" ".join(parts))
    if sum(len(cell) for cell in joined) < 8:
        return None
    return joined


def _lone_markdown(row: list[str]) -> str:
    cells = [cell.replace("\n", " ").strip() for cell in row]
    if sum(bool(cell) for cell in cells) < 2:
        return ""
    head = "| " + " | ".join(cells) + " |"
    sep = "| " + " | ".join(["---"] * len(cells)) + " |"
    return head + "\n" + sep


def _stroke_rules(page) -> tuple[list, list]:
    """Hairlines stored as several rectangles inside one drawing."""
    horizontal, vertical = [], []
    for drawing in page.get_drawings():
        rects = [item[1] for item in drawing.get("items") or [] if item[0] == "re"]
        if not rects:
            rects = [drawing["rect"]]
        for rect in rects:
            # A column rule splits the horizontal into a short left piece and a long one.
            if rect.width > 20 and rect.height < 1.5:
                horizontal.append(rect)
            elif 12 < rect.height < 100 and rect.width < 1.5:
                vertical.append(rect)
    return horizontal, vertical


def _open_ruled_table(page, words: list[dict], taken: list[tuple]) -> dict | None:
    """A scale whose last row has no bottom rule, and whose lines are grouped into one path.

    find_tables skips it. The left column is a short grade (УУР, A, B, C).
    """
    horizontal, vertical = _stroke_rules(page)
    bands: list[list[float]] = []
    for rect in sorted(horizontal, key=lambda item: item.y0):
        y = float(rect.y0)
        if bands and abs(y - bands[-1][0]) < 3:
            bands[-1][1] = min(bands[-1][1], float(rect.x0))
            bands[-1][2] = max(bands[-1][2], float(rect.x1))
            continue
        bands.append([y, float(rect.x0), float(rect.x1)])
    built = []
    for index, (y, x0, x1) in enumerate(bands):
        if x1 - x0 < 200:
            continue
        hanging = [
            rect
            for rect in vertical
            if abs(rect.y0 - y) <= 3.5 and x0 - 6 <= rect.x0 <= x1 + 6
        ]
        if len(hanging) < 3:
            continue
        ends = [float(rect.y1) for rect in hanging]
        if max(ends) - min(ends) > 4:
            continue
        end = max(ends)
        nxt = bands[index + 1][0] if index + 1 < len(bands) else None
        if nxt is not None and abs(nxt - end) <= 6:
            bottom = nxt
        elif nxt is None or nxt > end + 4:
            bottom = end
        else:
            continue
        if not 14 <= bottom - y <= 90:
            continue
        edges: list[float] = []
        for value in sorted(float(rect.x0) for rect in hanging):
            if not edges or value - edges[-1] > 3:
                edges.append(value)
        if len(edges) < 3 or edges[-1] - edges[0] < 120:
            continue
        built.append((y, bottom, edges))
    groups: list[list[tuple]] = []
    for row in built:
        if groups and abs(row[2][0] - groups[-1][-1][2][0]) < 4 and abs(row[0] - groups[-1][-1][1]) < 8:
            if len(row[2]) == len(groups[-1][-1][2]):
                groups[-1].append(row)
                continue
        groups.append([row])
    for group in groups:
        if len(group) < 2:
            continue
        edges = group[0][2]
        rows = []
        for top, bottom, _edges in group:
            cells = []
            for left, right in zip(edges, edges[1:]):
                chosen = [
                    word
                    for word in words
                    if left - 1 <= (word["x0"] + word["x1"]) / 2 <= right + 1
                    and top - 1 <= (word["y0"] + word["y1"]) / 2 <= bottom + 1
                ]
                cells.append(cell_text(chosen))
            rows.append(cells)
        if not rows or any(len(row[0]) > 16 for row in rows):
            continue
        if not any(re.fullmatch(r"(?:УУР|УДД|[A-DАВСД])", row[0]) for row in rows):
            continue
        bbox = [edges[0], group[0][0], max(edges[-1], group[-1][2][-1]), group[-1][1]]
        if _covered(tuple(bbox), taken):
            continue
        text = markdown_table(rows)
        if not text:
            continue
        return {"type": "table", "text": text, "y": bbox[1], "bbox": bbox}
    return None


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
            cuts = _column_cuts(table["row_boxes"], _stroke_rules(page)[1])
            for raw, boxes in zip(raw_rows, table["row_boxes"]):
                stacked = split_stacked_lines(raw)
                if stacked is not None:
                    rows.extend(stacked)
                    continue
                cells = []
                for index, raw_cell in enumerate(raw):
                    box = boxes[index] if index < len(boxes) else None
                    if box is None:
                        cells.append("")
                        continue
                    inner = [x for x in cuts if box[0] + 8 < x < box[2] - 8]
                    # A narrow cell is one missed rule («1 год» and «2-й год»). A wide cell is a span.
                    if inner and box[2] - box[0] <= 140:
                        bounds = [box[0], *inner, box[2]]
                        for left, right in zip(bounds, bounds[1:]):
                            chosen = [
                                word
                                for word in words
                                if _center_in(word, (left, box[1], right, box[3]), pad=0.4)
                            ]
                            cells.append(cell_text(chosen))
                        continue
                    chosen = [word for word in words if _center_in(word, box)]
                    cells.append(cell_text(chosen) if chosen else clean_text(raw_cell or ""))
                    if inner:
                        cells.extend([""] * len(inner))
                rows.append(cells)
            above, below, bbox = _clipped_rows(page, table["bbox"], table["row_boxes"], words)
            rows = above + rows + below
            band = _collapse_unruled_band(page, table["bbox"], rows)
            grid = _lone_markdown(band) if band is not None else markdown_table(rows)
            if not grid:
                continue
            blocks.append({"type": "table", "text": grid, "y": bbox[1], "bbox": bbox})
        taken = [tuple(block["bbox"]) for block in blocks]
        for grid in _hairline_grids(page):
            if _covered(grid["bbox"], taken):
                continue
            block = _grid_table(words, grid)
            if block is None:
                continue
            blocks.append(block)
            taken.append(tuple(block["bbox"]))
        orphan = _orphan_numbered_grid(page, words, taken)
        if orphan is not None and not _covered(orphan["bbox"], taken):
            blocks.append(orphan)
            taken.append(tuple(orphan["bbox"]))
        for row in _ruled_rows(page, words, taken):
            blocks.append(row)
            taken.append(tuple(row["bbox"]))
        coded = _code_box(page, words, taken)
        if coded is not None:
            blocks.append(coded)
            taken.append(tuple(coded["bbox"]))
        opened = _open_ruled_table(page, words, taken)
        if opened is not None:
            blocks.append(opened)
        return blocks
    finally:
        if temp is not None:
            temp.close()


def _content_images(page) -> list[dict]:
    images = []
    area = page.rect.width * page.rect.height
    raw = []
    for info in page.get_image_info():
        box = info["bbox"]
        width = box[2] - box[0]
        height = box[3] - box[1]
        if width * height > area * 0.82:
            continue
        # A card frame runs the full page height but stays under the area cutoff, then hides the text.
        if height > page.rect.height * 0.92:
            continue
        raw.append({"bbox": [float(v) for v in box], "y": float(box[1]), "w": width, "h": height})
    kept = [item for item in raw if item["w"] >= 70 and item["h"] >= 48]
    for item in raw:
        if item["h"] >= 70 or item["w"] < 70 or item["h"] < 8:
            continue
        # The last band of a sliced figure is shorter than the others and used to be dropped.
        box = item["bbox"]
        for other in kept:
            side = other["bbox"]
            same_x = abs(box[0] - side[0]) < 4 and abs(box[2] - side[2]) < 4
            adjacent = abs(box[1] - side[3]) <= 2 or abs(side[1] - box[3]) <= 2
            if same_x and adjacent:
                kept.append(item)
                break
    images = [{"bbox": item["bbox"], "y": item["y"]} for item in kept]
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
    blob = " ".join(line["text"] for line in lines).lower()
    codes = len(re.findall(r"\d{4}/\d", blob))
    # A toxicity grid repeats «степень» down the columns. That is a table, not a flowchart.
    if blob.count("степень") >= 4 and "блок-схема" not in blob:
        return False
    return short >= 18 and long <= 12 and buckets >= 3 and codes < 4 and short > long * 3


def _caption_scheme(page, lines: list[dict]) -> bool:
    """A flowchart page whose labels are not in the text layer, only the caption is."""
    if len(page.get_text("words")) > 40:
        return False
    blob = " ".join(line["text"] for line in lines).lower()
    return "схем" in blob


def _vector_scheme(page, lines: list[dict]) -> bool:
    """A flowchart drawn as boxes, with a «Схема» label and no table."""
    texts = [clean_text(line["text"]) for line in lines if clean_text(line["text"])]
    texts = [text for text in texts if not re.fullmatch(r"\d{1,3}", text)]
    if not any(text.lower() == "схема" or text.lower().startswith("схема ") for text in texts):
        return False
    # A recommendation page mentions «схема» and has rules under the lines. It stays text.
    if sum(len(text) for text in texts) > 800:
        return False
    # Thin strokes are invisible to the box detector. The caption is the only real text.
    raw = sum(len(text) for text in texts)
    if raw < 500 and any("блок-схема" in text.lower() for text in texts) and not _content_images(page):
        return True
    short = [text for text in texts if len(text) <= 28]
    if len(short) < 8:
        return False
    boxes = 0
    for drawing in page.get_drawings():
        rect = drawing["rect"]
        if 12 < rect.width < page.rect.width * 0.8 and 8 < rect.height < 70:
            boxes += 1
            if boxes >= 8:
                return True
    return False


def _figure_cluster(page, images: list[dict], lines: list[dict]) -> list[float] | None:
    """Many small frames of one flowchart. One clip keeps the arrows between them."""
    if len(images) < 4:
        return None
    boxes = [image["bbox"] for image in images]
    if any(
        box[2] - box[0] > page.rect.width * 0.72 or box[3] - box[1] > page.rect.height * 0.4
        for box in boxes
    ):
        return None

    def _close(one, other) -> bool:
        gap_x = max(0, max(one[0], other[0]) - min(one[2], other[2]))
        gap_y = max(0, max(one[1], other[1]) - min(one[3], other[3]))
        return gap_x < 180 and gap_y < 100

    seen = {0}
    stack = [0]
    while stack:
        current = stack.pop()
        for index, box in enumerate(boxes):
            if index not in seen and _close(boxes[current], box):
                seen.add(index)
                stack.append(index)
    if len(seen) != len(boxes):
        return None
    union = [
        min(box[0] for box in boxes),
        min(box[1] for box in boxes),
        max(box[2] for box in boxes),
        max(box[3] for box in boxes),
    ]
    # Pathway titles and side captions sit just outside the image boxes.
    x0, y0, x1, y1 = union
    for line in lines:
        text = clean_text(line["text"])
        if not text or len(text) > 42 or text.endswith("."):
            continue
        if heading_level(text, False) is not None:
            continue
        if line["y1"] < y0 - 40 or line["y"] > y1 + 24:
            continue
        if line["x1"] < x0 - 80 or line["x"] > x1 + 80:
            continue
        x0, y0 = min(x0, line["x"]), min(y0, line["y"])
        x1, y1 = max(x1, line["x1"]), max(y1, line["y1"])
    union = [x0, y0, x1, y1]
    # A title page of logos is not a flowchart. Its lines are sentences, not box labels.
    if union[3] - union[1] > page.rect.height * 0.55:
        inside = [
            clean_text(line["text"])
            for line in lines
            if union[1] - 4 <= line.get("y", 0) <= union[3] + 4 and clean_text(line["text"])
        ]
        if len(inside) >= 4:
            lengths = sorted(len(text) for text in inside)
            if lengths[len(lengths) // 2] > 36:
                return None
    return union


def _ink_gap(page, lines: list[dict]) -> list[float] | None:
    """A drawing with no text layer, sitting in a tall gap between two paragraphs."""
    ordered = [line for line in sorted(lines, key=lambda item: item["y"]) if clean_text(line["text"])]
    for left, right in zip(ordered, ordered[1:]):
        gap = right["y"] - left["y1"]
        if gap < 180 or gap > page.rect.height * 0.72:
            continue
        clip = pymupdf.Rect(page.rect.x0, left["y1"] + 2, page.rect.x1, right["y"] - 2)
        pix = page.get_pixmap(dpi=28, clip=clip, colorspace=pymupdf.csGRAY, alpha=False)
        gray = np.frombuffer(pix.samples, dtype=np.uint8)
        # A light page background is under 240. A drawing has strokes darker than that.
        if float((gray < 200).mean()) < 0.02:
            continue
        return [page.rect.x0, left["y1"] + 2, page.rect.x1, right["y"] - 2]
    return None


def flowchart_column_is_a_table(lefts: list[float]) -> bool:
    """Many cells sharing a left edge are a table column, not flowchart boxes."""
    bins: dict[int, int] = {}
    for left in lefts:
        key = round(left / 8) * 8
        bins[key] = bins.get(key, 0) + 1
    return bool(bins) and max(bins.values()) >= 8


def flowchart_labels_are_a_table(texts: list[str]) -> bool:
    """Evidence scales and class tables are not a flowchart, even when cells are boxes."""
    blob = " ".join(texts).lower().replace("ё", "е")
    if "достоверности доказательств" in blob or "классы показаний" in blob:
        return True
    return any(text.lower().startswith("таблица") for text in texts)


def _flowchart_span(page, lines: list[dict]) -> tuple[float, float] | None:
    """Boxes of a vector flowchart. The clip is the scheme; prose outside it stays."""
    boxes = []
    for drawing in page.get_drawings():
        rect = drawing["rect"]
        if 12 < rect.width < page.rect.width * 0.96 and 8 < rect.height < 240:
            boxes.append(rect)
    if len(boxes) < 6:
        return None
    # A table row is almost as wide as the page. A flowchart still has several narrower boxes.
    narrow = [rect for rect in boxes if rect.width < page.rect.width * 0.72]
    if len(narrow) < 6:
        return None
    # A table column is many cells with the same left edge. Flowchart boxes do not line up that way.
    if flowchart_column_is_a_table([rect.x0 for rect in narrow]):
        return None
    # A highlighted list is a bar behind every line. Those bars are one text line tall.
    if max(rect.height for rect in boxes) <= 28:
        return None
    # One line of caption sits above the first box and under the last one.
    y0 = min(rect.y0 for rect in boxes) - 22
    y1 = max(rect.y1 for rect in boxes) + 18
    inside = [
        clean_text(line["text"])
        for line in lines
        if y0 <= line["y"] <= y1 and clean_text(line["text"])
    ]
    inside = [text for text in inside if not re.fullmatch(r"\d{1,3}", text)]
    if len(inside) < 6:
        # The box labels are drawn as paths. The caption is the only text, so keep the clip.
        caption = " ".join(clean_text(line["text"]) for line in lines).lower()
        if len(boxes) >= 6 and any(word in caption for word in ("рис.", "схема", "алгоритм")):
            return y0, y1
        return None
    # A box label is often a whole sentence. Count it as short up to one line.
    if sum(len(text) <= 72 for text in inside) < len(inside) * 0.5:
        return None
    # «т.ч.» and «м.ж.» are abbreviations inside a box, not the end of a paragraph.
    if sum(1 for text in inside if re.search(r"[А-Яа-яA-Za-z]{4,}\.$", text)) >= 3:
        return None
    blob = " ".join(inside).lower()
    if "год утверждения" in blob or "клинические рекомендации" in blob:
        return None
    # Cell borders of a criteria table are boxes. «Да/Нет» is a cell, not a branch.
    if blob.count("да/нет") >= 3:
        return None
    # An evidence scale and a class table are grids, even when the cells look like boxes.
    if flowchart_labels_are_a_table(inside):
        return None
    # A footnote that starts inside the last box continues a line below the clip.
    for line in sorted(lines, key=lambda item: item["y"]):
        if line["y"] < y1 - 2:
            continue
        if line["y"] > y1 + 20:
            break
        text = clean_text(line["text"])
        if not text or re.fullmatch(r"\d{1,3}", text) or heading_level(text, False) is not None:
            break
        # The next table's caption is not a footnote of the flowchart.
        if re.match(r"Таблица\b", text):
            break
        y1 = line["y1"] + 2
    return y0, y1


def _figure_above_text(page, lines: list[dict]) -> list[float] | None:
    """A scheme drawn on a scan, with the real paragraph starting underneath it."""
    body = [line for line in lines if len(clean_text(line["text"])) > 24]
    if not body:
        return None
    top = min(line["y"] for line in body)
    if top < 200:
        return None
    above = [
        line
        for line in lines
        if line["y1"] < top - 8 and len(clean_text(line["text"])) > 2
    ]
    if len(above) > 4:
        return None
    pix = page.get_pixmap(dpi=30, colorspace=pymupdf.csGRAY, alpha=False)
    gray = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.h, pix.w)
    cut = max(1, min(pix.h - 1, int(top / page.rect.height * pix.h)))
    band = gray[:cut]
    if float((band < 245).mean()) < 0.08:
        return None
    return [page.rect.x0, page.rect.y0 + 28, page.rect.x1, top - 6]


def _scheme_page(page, lines: list[dict]) -> bool:
    # An approval title is not a flowchart, even when the stamp image fills the page.
    blob = " ".join(clean_text(line["text"]) for line in lines).lower()
    if "утверждено" in blob and "алгоритм" not in blob:
        return False
    if _scattered_labels(lines):
        return True
    texts = [clean_text(line["text"]) for line in lines if clean_text(line["text"])]
    texts = [text for text in texts if not re.fullmatch(r"\d{1,3}", text)]
    # A scanned flowchart splits every box into its own line, so the cap is loose.
    # The picture still has to contain boxes; a prose scan does not.
    if not 5 <= len(texts) <= 40:
        return False
    ordered = sorted(len(text) for text in texts)
    middle = ordered[len(ordered) // 2]
    # A scanned flowchart often has no vector boxes for the detector. Short labels and
    # «да» / «нет» are enough; a prose scan has sentences.
    periods = sum(text.endswith(".") for text in texts)
    answers = sum(text.lower() in {"да", "нет"} for text in texts)
    if middle <= 28 and periods < 2 and answers >= 2:
        return True
    # The title says this page is the algorithm, and the text layer is only short labels.
    blob = " ".join(texts).lower()
    if "алгоритм" in blob and periods < 2 and middle <= 40 and len(texts) <= 36:
        return True
    # A scanned algorithm page keeps its footnotes in the text layer. The picture is the page.
    if "алгоритм" in blob and "рисунок" in blob and middle <= 55 and len(texts) <= 50:
        return True
    if middle > 22:
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
            # The next box of the same flowchart can sit a line below the image.
            if rect.x1 < box[0] - 8 or rect.x0 > box[2] + 8 or rect.y1 < box[1] - 8 or rect.y0 > box[3] + 32:
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
    if (assets / name).exists():
        name = f"p{page_no:03d}-scheme2.png"
    _save_clip(page, union, assets / name, pad=10)
    pieces = [f"![Схема, страница {page_no}]({name})"]
    if graph:
        pieces.append(graph)
    return {
        "type": "figure",
        "text": "\n\n".join(pieces),
        "y": union[1],
        "bbox": union,
        "file": name,
    }


def _mark_scan(doc, page, assets: Path, page_no: int, record: dict, lines: list[dict] | None = None) -> None:
    record["needs_ocr"] = True
    name = f"p{page_no:03d}-page.png"
    page.get_pixmap(dpi=140, alpha=False).save(assets / name)
    record["image"] = name
    record["page_h"] = page.rect.height
    if lines:
        record["layer_lines"] = [
            {"text": line["text"], "y": line["y"], "y1": line["y1"]} for line in lines
        ]
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


def _sparse_ink(page) -> bool:
    """Blank page or one leftover line. A figure has a picture or real drawings."""
    if _content_images(page):
        return False
    drawn = 0
    for drawing in page.get_drawings():
        rect = drawing["rect"]
        if rect.width <= 8 or rect.height <= 8:
            continue
        fill = drawing.get("fill")
        color = drawing.get("color")

        def _light(ink) -> bool:
            return ink is not None and all(channel >= 0.9 for channel in ink[:3])

        # A white or near-white fill is the page background, not a figure.
        if _light(fill) and (color is None or _light(color)):
            continue
        if fill is None and _light(color):
            continue
        drawn += 1
        if drawn > 3:
            return False
    pix = page.get_pixmap(dpi=24, colorspace=pymupdf.csGRAY, alpha=False)
    gray = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.h, pix.w)
    return float((gray < 200).mean()) < 0.0022


def _stamp_only(page) -> bool:
    """A full-page scan whose only extra image is a small approval stamp.

    The stamp is not the page. Read the scan.
    """
    if not _full_image(page) or page.get_text("words"):
        return False
    images = _content_images(page)
    if not images:
        return False
    area = page.rect.width * page.rect.height
    return all(
        (image["bbox"][2] - image["bbox"][0]) * (image["bbox"][3] - image["bbox"][1]) < area * 0.08
        for image in images
    )


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
    if is_toc([line["text"] for line in lines]) and not _content_images(page):
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
        _mark_scan(doc, page, assets, page_no, record, lines)
        return record

    # Title pages carry the approval stamps in the text layer. Read the scan instead.
    # A page that is already Russian, with one stamp-font word, keeps the text layer.
    if _full_image(page) and any("год утверждения" in line["text"].lower() for line in lines):
        letters = [ch for line in lines for ch in line["text"] if ch.isalpha()]
        cyr = sum(ch.lower() in "абвгдеёжзийклмнопрстуфхцчшщъыьэюя" for ch in letters) / len(letters) if letters else 0
        bad = sum(1 for line in lines if line.get("garbled"))
        if cyr < 0.9 or bad > 2:
            _mark_scan(doc, page, assets, page_no, record, lines)
            return record

    if not words and _stamp_only(page):
        _mark_scan(doc, page, assets, page_no, record, lines)
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
    images = _content_images(page)
    cluster = _figure_cluster(page, images, lines)
    if cluster is not None:
        name = f"p{page_no:03d}-scheme.png"
        _save_clip(page, cluster, assets / name, pad=10)
        figures.append(
            {
                "type": "figure",
                "text": f"![Схема, страница {page_no}]({name})",
                "y": cluster[1],
                "file": name,
            }
        )
        y0, y1 = cluster[1], cluster[3]
        lines = [
            line
            for line in lines
            if not (y0 - 2 <= line["y"] <= y1) or heading_level(line["text"], False) is not None
        ]
        images = []
    for image in images:
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

    if not tables and _full_image(page) and tracked_figure(words):
        # Letter-spaced labels on a scan. The small images are slices of the same figure.
        name = f"p{page_no:03d}-scheme.png"
        page.get_pixmap(dpi=130, alpha=False).save(assets / name)
        figures = [
            {
                "type": "figure",
                "text": f"![Схема, страница {page_no}]({name})",
                "y": page.rect.height * 0.2,
                "file": name,
            }
        ]
        lines = [line for line in lines if heading_level(line["text"], False) is not None]
    elif not figures and _full_image(page) and (band := _figure_above_text(page, lines)):
        name = f"p{page_no:03d}-scheme.png"
        _save_clip(page, band, assets / name, pad=4)
        figures.append(
            {
                "type": "figure",
                "text": f"![Схема, страница {page_no}]({name})",
                "y": band[1],
                "file": name,
            }
        )
    elif not figures and (
        (
            _full_image(page)
            and (tracked_figure(words) or _scheme_page(page, lines) or _caption_scheme(page, lines))
        )
        or (not tables and _vector_scheme(page, lines))
    ):
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
        # The scan already shows the table. A second reading of the same page is a broken copy.
        tables = []
    elif (span := _flowchart_span(page, lines)) and not any(
        table.get("bbox") and table["bbox"][1] < span[1] - 8 and table["bbox"][3] > span[0] + 8
        for table in tables
    ) and not any(
        figure.get("bbox") and figure["bbox"][1] < span[1] - 8 and figure["bbox"][3] > span[0] + 8
        for figure in figures
    ):
        y0, y1 = span
        name = f"p{page_no:03d}-scheme.png"
        if any(figure.get("file") == name for figure in figures):
            name = f"p{page_no:03d}-scheme2.png"
        _save_clip(page, [page.rect.x0, y0, page.rect.x1, y1], assets / name, pad=4)
        figures.append(
            {
                "type": "figure",
                "text": f"![Схема, страница {page_no}]({name})",
                "y": y0,
                "bbox": [page.rect.x0, y0, page.rect.x1, y1],
                "file": name,
            }
        )
        lines = [
            line
            for line in lines
            if not (y0 - 2 <= line["y"] <= y1) or heading_level(line["text"], False) is not None
        ]
    elif not figures and (band := _ink_gap(page, lines)):
        name = f"p{page_no:03d}-scheme.png"
        _save_clip(page, band, assets / name, pad=2)
        figures.append(
            {
                "type": "figure",
                "text": f"![Схема, страница {page_no}]({name})",
                "y": band[1],
                "file": name,
            }
        )

    if len(good) < 12 and not figures and not tables:
        coded = any(re.search(r"[А-ЯA-Z]\d{2}\.\d{2}\.\d{3}", line["text"]) for line in lines)
        if _sparse_ink(page):
            if not lines:
                record["skip"] = "blank"
                return record
        elif _full_image(page):
            # The page is the scheme. OCR of the boxes becomes a wrong caption, so keep the picture
            # and the text layer that is already there.
            name = f"p{page_no:03d}-scheme.png"
            page.get_pixmap(dpi=130, alpha=False).save(assets / name)
            figures.append(
                {
                    "type": "figure",
                    "text": f"![Схема, страница {page_no}]({name})",
                    "y": page.rect.height * 0.25,
                    "file": name,
                }
            )
        elif not coded:
            _mark_scan(doc, page, assets, page_no, record, lines)
            return record

    kept = [line for line in lines if not any(_inside(line, rect) for rect in taken)]
    italic_noise = re.compile(r"эю|профш|чъ|мч\b|тяж\s+е")
    noisy = any(line.get("italic") and italic_noise.search(line["text"]) for line in kept)
    garbled = any(line.get("garbled") for line in kept) and _full_image(page)
    if noisy or garbled:
        if noisy:
            record["italic_fix"] = True
        if garbled:
            record["line_fix"] = True
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
                "garbled": bool(line.get("garbled")),
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
