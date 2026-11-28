"""Read a page image with Apple Vision and lay the lines out like the text layer."""

from __future__ import annotations

import re
from pathlib import Path

from layout import clean_text, flow, garbage_line, is_toc, promote_title

CYR = set("абвгдеёжзийклмнопрстуфхцчшщъыьэюя")
ROW = re.compile(r"^\d{1,2}$")


def recognize(path: Path) -> list[dict]:
    import Vision
    from Foundation import NSURL

    def once(languages: list[str]) -> list[dict]:
        request = Vision.VNRecognizeTextRequest.alloc().init()
        request.setRecognitionLevel_(0)
        request.setRecognitionLanguages_(languages)
        request.setUsesLanguageCorrection_(True)
        url = NSURL.fileURLWithPath_(str(path))
        handler = Vision.VNImageRequestHandler.alloc().initWithURL_options_(url, None)
        ok, err = handler.performRequests_error_([request], None)
        if not ok:
            raise RuntimeError(err)
        lines = []
        for obs in request.results() or []:
            box = obs.boundingBox()
            cand = obs.topCandidates_(1)[0]
            text = cand.string().strip()
            if not text:
                continue
            letters = [ch for ch in text if ch.isalpha()]
            ratio = sum(ch.lower() in CYR for ch in letters) / len(letters) if letters else 0
            keep = text in {"Да", "Нет", "да", "нет"} or ROW.fullmatch(text)
            if not keep and cand.confidence() < 0.35 and (len(text) < 20 or ratio < 0.4):
                continue
            if re.search(r"\.{3,}|и{8,}", text):
                continue
            y = 1 - box.origin.y - box.size.height
            lines.append(
                {
                    "text": text,
                    "x": box.origin.x,
                    "y": y,
                    "y1": y + box.size.height,
                    "h": box.size.height,
                    "w": box.size.width,
                    "bold": False,
                    "conf": cand.confidence(),
                }
            )
        lines.sort(key=lambda line: (line["y"], line["x"]))
        return lines

    russian = once(["ru-RU", "en-US"])
    letters = [ch for line in russian for ch in line["text"] if ch.isalpha()]
    cyr = sum(ch.lower() in CYR for ch in letters) / len(letters) if letters else 1
    if cyr >= 0.75:
        return russian
    english = once(["en-US", "ru-RU"])
    latin = 1 - (
        sum(ch.lower() in CYR for line in english for ch in line["text"] if ch.isalpha())
        / max(1, sum(ch.isalpha() for line in english for ch in line["text"]))
    )
    mean = lambda rows: sum(row["conf"] for row in rows) / len(rows) if rows else 0
    if latin > 0.55 and mean(english) >= mean(russian) - 0.05:
        return english
    return russian


def _hits(lines: list[dict], rect: list[int], width: int, height: int) -> list[dict]:
    chosen = []
    x0, y0, x1, y1 = rect
    for line in lines:
        cx = (line["x"] + line["w"] / 2) * width
        cy = (line["y"] + line["h"] / 2) * height
        if x0 - 4 <= cx <= x1 + 4 and y0 - 4 <= cy <= y1 + 4:
            chosen.append(line)
    chosen.sort(key=lambda line: (line["y"], line["x"]))
    return chosen


def scheme_caption(lines: list[dict], geom: dict) -> str:
    """The picture is the scheme. OCR of the boxes invents arrows the drawing does not have."""
    del lines, geom
    return ""


_ELEMENT = re.compile(r"^(?:Ga|Lu|Tc|In|Cu|Zr|Yb|Ac)-")


def restore_mass_numbers(lines: list[dict], layer: list[dict] | None, page_h: float) -> list[dict]:
    """A superscript mass number is in the text layer and often missing from OCR.

    «68Оа-…» on the baseline and «Ga-DOTATATE» from the scan are one name.
    """
    for line in lines:
        text = re.sub(
            r"(\d{2,3})\s+(Ga|Lu|Tc|In|Cu|Zr|Yb|Ac)(?=\s*-)",
            r"\1\2",
            line["text"],
        )
        if text != line["text"]:
            line["text"] = text
        if re.match(r"^\d", text) or not layer or not page_h or not _ELEMENT.match(text):
            continue
        center = (line["y"] + line.get("y1", line["y"] + line.get("h", 0))) / 2 * page_h
        best = None
        best_d = 14.0
        for item in layer:
            mid = (item["y"] + item["y1"]) / 2
            dist = abs(mid - center)
            if dist < best_d:
                best, best_d = item, dist
        if best is None:
            continue
        mass = re.match(r"\s*(\d{2,3})(?=[^\d\s])", best["text"])
        if mass:
            line["text"] = mass.group(1) + text
    return lines


def blocks_from_ocr(lines: list[dict], geom: dict | None, page_no: int, image_name: str | None) -> list[dict]:
    if lines and is_toc([line["text"] for line in lines]):
        return []
    if not lines and image_name:
        return [{"type": "figure", "text": f"![Страница {page_no}]({image_name})", "y": 0}]
    width = geom["w"] if geom else 1
    height = geom["h"] if geom else 1
    used = [False] * len(lines)
    blocks: list[dict] = []

    def take(rect) -> str:
        picked = _hits(lines, rect, width, height)
        for line in picked:
            used[lines.index(line)] = True
        return clean_text(" ".join(line["text"] for line in picked)).replace("|", "/")

    if geom:
        for table in geom["tables"]:
            rows = [[take(cell) for cell in row] for row in table]
            from layout import markdown_table

            grid = markdown_table(rows)
            if grid:
                blocks.append({"type": "table", "text": grid, "y": table[0][0][1] / height})
        for node in geom["nodes"]:
            take(node)
        # The picture is the scheme. A graph built from OCR adds arrows the drawing does not have.
        if image_name and geom["nodes"]:
            top = min(node[1] for node in geom["nodes"]) / height
            blocks.append(
                {"type": "figure", "text": f"![Схема, страница {page_no}]({image_name})", "y": top}
            )

    rest = []
    for index, line in enumerate(lines):
        if used[index] or garbage_line(line["text"]):
            continue
        rest.append({**line, "text": clean_text(line["text"])})
    prose = flow(rest, 1.0)
    # A page that is only a picture yields a few stamp words. Keep the picture.
    letters = sum(ch.isalpha() for block in prose for ch in block["text"])
    if letters < 40 and image_name and not any(block["type"] == "figure" for block in blocks):
        blocks.append({"type": "figure", "text": f"![Страница {page_no}]({image_name})", "y": 0})
        return promote_title(blocks)
    blocks.extend(prose)
    blocks.sort(key=lambda block: block["y"])
    return promote_title(blocks)
