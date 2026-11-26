"""Trial conversion of one clinical-recommendation PDF to Markdown.

Each page image is read with Apple Vision. Russian is the first language;
a page that comes back mostly in Latin is read again with English first
(the bibliography). Approval stamps, the table of contents and page numbers
are left out. The quality-criteria grid becomes a Markdown table. The
action diagram becomes Mermaid: boxes are the text that was read, and an
arrow is drawn only when both of its boxes were found.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

import Vision
from Foundation import NSURL

PY = "/Users/edwfa/okf-studio/.venv/bin/python"
HEAD = re.compile(r"^(\d{1,2}(?:\.\d{1,2})*)\.?\s+(\S.*)$")
CHAPTER = re.compile(
    r"^(?:Краткая|Диагностика|Лечение|Медицинская|Профилактика|Организация|Дополнительная)"
)
EDGE = re.compile(r"^(?:да|нет)$", re.I)
ROW = re.compile(r"^\d{1,2}$")
CYR = set("абвгдеёжзийклмнопрстуфхцчшщъыьэюя")
SPLIT = re.compile(
    r"\s+(?=[1-7]\.\s+(?:Краткая|Диагностика|Лечение|Медицинская|Профилактика|Организация|Дополнительная)\b)"
)
CHAPTER_BODY = re.compile(
    r"^([1-7]\. (?:Краткая информация по заболеванию или состоянию \(группе заболеваний или состояний\)"
    r"|Диагностика заболевания или состояния \(группы заболеваний или состояний\), медицинские показания и противопоказания к применению методов диагностики"
    r"|Лечение, включая .{0,80}?методов лечения"
    r"|Медицинская реабилитация .{0,160}?факторов"
    r"|Профилактика и диспансерное наблюдение .{0,120}?профилактики"
    r"|Организация оказания медицинской помощи"
    r"|Дополнительная информация \(в том числе факторы, влияющие на исход заболевания или состояния\)))"
    r"\s+([А-ЯA-Z].*)$"
)


def render(pdf: Path, folder: Path) -> int:
    script = f"""
import json, sys
import numpy as np
import pymupdf
from pathlib import Path
sys.path.insert(0, {str(Path(__file__).resolve().parent)!r})
from page_geometry import analyze
src = pymupdf.open({str(pdf)!r})
out = Path({str(folder)!r})
for i, page in enumerate(src):
    images = page.get_images()
    if images:
        pix = pymupdf.Pixmap(src, images[0][0])
        if pix.n > 1:
            pix = pymupdf.Pixmap(pymupdf.csGRAY, pix)
    else:
        pix = page.get_pixmap(dpi=200, colorspace=pymupdf.csGRAY)
    pix.save(out / f"{{i:03d}}.png")
    gray = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.h, pix.w)
    (out / f"{{i:03d}}.geom.json").write_text(json.dumps(analyze(gray), ensure_ascii=False))
    words = [{{"x": w[0], "y": w[1], "t": w[4]}} for w in page.get_text("words")]
    (out / f"{{i:03d}}.json").write_text(json.dumps(words, ensure_ascii=False))
print(src.page_count)
"""
    result = subprocess.run([PY, "-c", script], check=True, capture_output=True, text=True)
    return int(result.stdout.strip().splitlines()[-1])


def recognize(path: Path, languages: list[str]) -> list[dict]:
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
        cyr = sum(ch.lower() in CYR for ch in letters)
        ratio = cyr / len(letters) if letters else 0
        keep_token = text in {"Да", "Нет", "да", "нет"} or ROW.fullmatch(text)
        short_ok = cand.confidence() >= 0.3 and ratio > 0.6 and len(text) >= 4
        short_label = len(text) <= 6 and cand.confidence() >= 0.4 and ratio >= 0.5
        if (
            not keep_token
            and not short_ok
            and not short_label
            and cand.confidence() < 0.5
            and (len(text) < 25 or ratio < 0.45)
        ):
            continue
        y = 1 - box.origin.y - box.size.height
        if ROW.fullmatch(text) and (y > 0.9 or box.origin.x > 0.4):
            continue
        if re.search(r"\.{3,}|и{8,}", text):
            continue
        lines.append(
            {
                "text": text,
                "x": box.origin.x,
                "y": y,
                "w": box.size.width,
                "h": box.size.height,
                "conf": cand.confidence(),
            }
        )
    lines.sort(key=lambda line: (round(line["y"], 3), line["x"]))
    return lines


def read_page(path: Path) -> list[dict]:
    russian = recognize(path, ["ru-RU", "en-US"])
    letters = [ch for line in russian for ch in line["text"] if ch.isalpha()]
    cyr = sum(ch.lower() in CYR for ch in letters) / len(letters) if letters else 1
    if cyr >= 0.75:
        return russian
    english = recognize(path, ["en-US", "ru-RU"])
    latin = 1 - (
        sum(ch.lower() in CYR for line in english for ch in line["text"] if ch.isalpha())
        / max(1, sum(ch.isalpha() for line in english for ch in line["text"]))
    )
    mean = lambda rows: sum(row["conf"] for row in rows) / len(rows) if rows else 0
    if latin > 0.55 and mean(english) >= mean(russian) - 0.05:
        return english
    return russian


def heading(text: str) -> int | None:
    if text.startswith("Приложение ") or text in {
        "Список сокращений",
        "Термины и определения",
        "Список литературы",
        "Критерии оценки качества медицинской помощи",
    }:
        return 2
    match = HEAD.match(text)
    if not match or len(text) > 280:
        return None
    number, rest = match.group(1), match.group(2)
    if int(number.split(".")[0]) > 12 or rest.startswith("степень "):
        return None
    if "." not in number and not CHAPTER.match(rest):
        return None
    return min(number.count(".") + 2, 4)


def is_toc(lines: list[dict]) -> bool:
    if any(line["text"].strip() == "Оглавление" for line in lines):
        return True
    heads = sum(
        1 for line in lines if line["text"].startswith("Приложение") or heading(line["text"])
    )
    appendix = sum(1 for line in lines if line["text"].startswith("Приложение"))
    long = sum(1 for line in lines if len(line["text"]) > 140)
    recommendation = any("Рекомендация" in line["text"] for line in lines)
    if recommendation or long:
        return False
    return heads >= 6 or appendix >= 4


def join_wraps(rows: list[str]) -> list[str]:
    out: list[str] = []
    for text in rows:
        if out and (out[-1].endswith("-") or (out[-1][-1:] not in ".»\"::" and text[:1].islower())):
            out[-1] = (out[-1][:-1] if out[-1].endswith("-") else out[-1] + " ") + text
        else:
            out.append(text)
    return out


def front(lines: list[dict]) -> str:
    texts = [line["text"].strip() for line in lines if line["conf"] >= 0.45 and line["text"].strip()]

    def at(prefix: str) -> int | None:
        return next((i for i, text in enumerate(texts) if text.lower().startswith(prefix)), None)

    code_at = at("кодирование")
    if code_at is None:
        code_at = next((i for i, text in enumerate(texts) if re.match(r"мк[бbь]", text, re.I)), None)
    age_at = at("возрастная группа")
    year_at = at("год утверждения")
    dev_at = at("разработ")
    anchors = [i for i in (code_at, age_at, year_at, dev_at) if i is not None]
    if not anchors:
        return ""
    title = texts[anchors[0] - 1] if anchors[0] else ""

    def span(start: int | None, end: int | None) -> list[str]:
        if start is None:
            return []
        stop = end if end is not None and end > start else len(texts)
        return texts[start:stop]

    coding = span(code_at, age_at if age_at is not None else year_at)
    if coding and coding[0].lower().startswith("кодирование"):
        codes = re.findall(r"[A-ZА-Я]\d{2}(?:\.\d{1,2})?", " ".join(coding))
        coding = [
            "Кодирование по Международной статистической классификации болезней и проблем, связанных со здоровьем: "
            + "; ".join(codes)
        ]
    orgs: list[str] = []
    if dev_at is not None:
        for text in texts[dev_at:]:
            low = text.lower()
            if orgs and any(word in low for word in ("утвержд", "одобрен", "заседани", "президент")):
                break
            orgs.append(text)
    parts = [("# " + title) if title else "", *coding, *span(age_at, year_at), *span(year_at, dev_at)]
    parts.extend(join_wraps(orgs))
    return "\n\n".join(part.strip() for part in parts if part.strip())


def prose(lines: list[dict]) -> str:
    flat: list[str] = []
    for line in lines:
        for part in SPLIT.split(line["text"]):
            cut = CHAPTER_BODY.match(part.strip())
            if cut:
                flat.extend([cut.group(1), cut.group(2)])
            elif part.strip():
                flat.append(part.strip())
    blocks: list[str] = []
    para: list[str] = []

    def flush() -> None:
        if para:
            text = re.sub(r"\s+([,.;:])", r"\1", " ".join(para))
            text = re.sub(r"(\w)-\s+(\w)", r"\1\2", text)
            blocks.append(text)
            para.clear()

    i = 0
    while i < len(flat):
        text = flat[i]
        level = heading(text)
        if level and text.count("(") > text.count(")"):
            rest = ""
            while i + 1 < len(flat) and text.count("(") > text.count(")"):
                i += 1
                nxt = flat[i]
                if ")" in nxt:
                    head, _, tail = nxt.partition(")")
                    text = f"{text} {head})"
                    rest = tail.strip(" .")
                    break
                text = f"{text} {nxt}"
            flush()
            blocks.append("#" * level + " " + re.sub(r"\s+", " ", text))
            if rest:
                para.append(rest)
            i += 1
            continue
        if level and i + 1 < len(flat) and flat[i + 1].startswith("по Международной статистической"):
            follow = flat[i + 1]
            i += 1
            coding = re.match(r"(по Международной статистической классификации болезней и проблем, связанных со здоровьем)\s*(.*)", follow)
            if coding:
                text = f"{text} {coding.group(1)}"
                if coding.group(2).strip():
                    flat.insert(i + 1, coding.group(2).strip())
            else:
                text = f"{text} {follow}"
        starts = bool(level) or text.startswith(("Рекомендация ", "Уровень ", "Комментари")) or text[:1] in "•-–"
        if starts:
            flush()
        if level:
            blocks.append("#" * level + " " + text)
        elif text[:1] in "•-–" and not para:
            blocks.append("- " + text.lstrip("•-– ").strip())
        elif para and para[-1].endswith("-"):
            para[-1] = para[-1][:-1] + text
        else:
            para.append(text)
        i += 1
    flush()
    return "\n\n".join(blocks)


def is_table(lines: list[dict]) -> bool:
    marks = sum(line["text"] in {"Да", "Нет"} for line in lines)
    numbers = sum(bool(ROW.fullmatch(line["text"])) and line["x"] < 0.25 for line in lines)
    return marks >= 8 and numbers >= 5


def criteria_from_words(words: list[dict]) -> str | None:
    words = [word for word in words if word["y"] < 760]
    if sum(word["t"] == "Да" for word in words) < 8:
        return None
    if not any(word["t"] == "Критерии" for word in words):
        return None
    ordered = sorted(words, key=lambda word: (word["y"], word["x"]))
    bands: list[list[dict]] = []
    for word in ordered:
        if bands and abs(word["y"] - bands[-1][0]["y"]) <= 3:
            bands[-1].append(word)
        else:
            bands.append([word])
    rows: dict[str, list[str]] = {}
    current: str | None = None
    for band in bands:
        number = next((word["t"] for word in band if word["x"] < 120 and ROW.fullmatch(word["t"])), "")
        body = " ".join(
            word["t"] for word in sorted(band, key=lambda word: word["x"]) if 120 <= word["x"] < 450
        )
        yes = "Да" if any(word["t"] == "Да" and word["x"] >= 450 for word in band) else ""
        no = "Нет" if any(word["t"] == "Нет" and word["x"] >= 450 for word in band) else ""
        if "Критерии" in body or body in {"Оценка", "выполнения"}:
            continue
        if number:
            current = number
            rows[number] = [number, body, yes, no]
        elif current and body:
            rows[current][1] = (rows[current][1] + " " + body).strip()
            rows[current][2] = rows[current][2] or yes
            rows[current][3] = rows[current][3] or no
    if len(rows) < 8:
        return None
    out = [
        "## Критерии оценки качества медицинской помощи",
        "",
        "| № | Критерий | Да | Нет |",
        "| --- | --- | --- | --- |",
    ]
    for key in sorted(rows, key=int):
        out.append("| " + " | ".join(cell.replace("|", "/") for cell in rows[key]) + " |")
    return "\n".join(out)


def table(lines: list[dict]) -> str:
    anchors = [line for line in lines if ROW.fullmatch(line["text"]) and line["x"] < 0.25]
    rows: dict[float, list[str]] = {anchor["y"]: [anchor["text"], "", "", ""] for anchor in anchors}

    def owner(line: dict) -> float | None:
        above = [anchor["y"] for anchor in anchors if anchor["y"] <= line["y"] + 0.012]
        return max(above) if above else None

    for line in lines:
        if line["text"] in {"Да", "Нет"} or ROW.fullmatch(line["text"]):
            continue
        if line["text"] in {"Критерии качества", "Оценка", "выполнения"}:
            continue
        if "Критерии оценки качества" in line["text"]:
            continue
        key = owner(line)
        if key is None:
            continue
        rows[key][1] = (rows[key][1] + " " + line["text"]).strip()
    for line in lines:
        if line["text"] not in {"Да", "Нет"}:
            continue
        key = owner(line)
        if key is None:
            continue
        slot = 2 if line["text"] == "Да" else 3
        rows[key][slot] = line["text"]
    out = [
        "## Критерии оценки качества медицинской помощи",
        "",
        "| № | Критерий | Да | Нет |",
        "| --- | --- | --- | --- |",
    ]
    for key in sorted(rows):
        out.append("| " + " | ".join(cell.replace("|", "/") for cell in rows[key]) + " |")
    return "\n".join(out)


def is_flow(lines: list[dict]) -> bool:
    text = " ".join(line["text"] for line in lines)
    marks = sum(1 for line in lines if EDGE.fullmatch(line["text"]))
    return "Алгоритм" in text and marks >= 3


def flow_nodes(lines: list[dict]) -> list[dict]:
    items = []
    for line in lines:
        if EDGE.fullmatch(line["text"]) or line["text"].startswith("Приложение") or ROW.fullmatch(line["text"]):
            continue
        if re.fullmatch(r"[\W_]+", line["text"]):
            continue
        items.append({**line, "x2": line["x"] + max(line["w"], 0.05), "y2": line["y"] + 0.016})
    groups: list[dict] = []
    for item in items:
        placed = False
        for group in groups:
            near = -0.008 <= item["y"] - group["y2"] <= 0.018
            same_column = abs(item["x"] - group["x"]) <= 0.12
            continuation = group["x"] <= item["x"] <= group["x"] + 0.25
            if near and (same_column or continuation):
                group["parts"].append(item)
                group["x"] = min(group["x"], item["x"])
                group["x2"] = max(group["x2"], item["x2"])
                group["y"] = min(group["y"], item["y"])
                group["y2"] = max(group["y2"], item["y2"])
                placed = True
                break
        if not placed:
            groups.append(
                {"parts": [item], "x": item["x"], "x2": item["x2"], "y": item["y"], "y2": item["y2"]}
            )
    nodes = []
    for group in groups:
        ordered = sorted(group["parts"], key=lambda part: (part["y"], part["x"]))
        text = re.sub(r"\s+", " ", " ".join(part["text"] for part in ordered)).strip()
        nodes.append({"text": text, "x": group["x"], "y": group["y"]})
    split: list[dict] = []
    for node in nodes:
        low = node["text"].lower()
        if "алгоритм ведения" in low and "прекратить поступление" in low:
            left, right = re.split(r"\s+(?=Прекратить)", node["text"], maxsplit=1)
            split.append({**node, "text": left.strip()})
            split.append({**node, "text": right.strip(), "y": node["y"] + 0.03})
        elif "прекратить поступление" in low and "уложить" in low:
            left, right = re.split(r"\s+\+\s+|\s+(?=Уложить)", node["text"], maxsplit=1)
            split.append({**node, "text": left.strip()})
            split.append({**node, "text": right.strip(), "y": node["y"] + 0.02})
        else:
            split.append(node)
    for node in split:
        if re.fullmatch(r"АД\W+ЧДД", node["text"]):
            for other in split:
                if "мониторирование" in other["text"].lower() and "ЧДД" not in other["text"]:
                    other["text"] = other["text"].rstrip(" ,") + ", " + node["text"]
    split = [node for node in split if not re.fullmatch(r"АД\W+ЧДД", node["text"])]
    split.sort(key=lambda node: (node["y"], node["x"]))
    return split


def flow_role(text: str) -> str | None:
    low = text.lower()
    if low.startswith("алгоритм ведения"):
        return "start"
    if "прекратить поступление" in low:
        return "stop"
    if low.startswith("уложить"):
        return "lay"
    if "мониторирование" in low:
        return "mon"
    if "кровообращения" in low or "остановки дыхания" in low:
        return "q_arrest"
    if "слр" in low:
        return "cpr"
    if "переднебоковую" in low and "повторн" not in low:
        return "epi"
    if "венозный" in low:
        return "q_vein"
    if low.startswith("сохранить"):
        return "keep"
    if low.startswith("наладить"):
        return "make"
    if "эффект" in low and "эпинефрин" in low:
        return "q_effect"
    if "повторн" in low:
        return "repeat"
    if "электролит" in low:
        return "fluids"
    if "кортикостероид" in low:
        return "steroids"
    if "транспортировка" in low:
        return "transport"
    return None


# Arrows checked against the figure on the algorithm page.
FLOW_EDGES = [
    ("start", "stop", ""),
    ("stop", "lay", ""),
    ("lay", "mon", ""),
    ("lay", "q_arrest", ""),
    ("q_arrest", "cpr", "да"),
    ("q_arrest", "epi", "нет"),
    ("cpr", "epi", ""),
    ("epi", "q_vein", ""),
    ("q_vein", "keep", "да"),
    ("q_vein", "make", "нет"),
    ("keep", "fluids", ""),
    ("make", "fluids", ""),
    ("epi", "q_effect", ""),
    ("q_effect", "repeat", "нет"),
    ("q_effect", "fluids", "да"),
    ("fluids", "steroids", ""),
    ("repeat", "transport", ""),
    ("steroids", "transport", ""),
]


def flow(lines: list[dict]) -> str:
    nodes = flow_nodes(lines)
    roles: dict[str, dict] = {}
    for node in nodes:
        role = flow_role(node["text"])
        if role and role not in roles:
            roles[role] = node
    title = next(line["text"] for line in lines if line["text"].startswith("Приложение"))
    out = ["## " + title, "", "```mermaid", "flowchart TD"]
    for role, node in roles.items():
        label = node["text"].replace('"', "'").replace("[", "(").replace("]", ")")
        shape = "{" + label + "}" if role.startswith("q_") else f'["{label}"]'
        out.append(f"  {role}{shape}")
    for src, dst, label in FLOW_EDGES:
        if src in roles and dst in roles:
            arrow = f"|{label}|" if label else ""
            out.append(f"  {src} -->{arrow} {dst}")
    out.append("```")
    return "\n".join(out)


def is_cover(lines: list[dict]) -> bool:
    return any(
        "Год утверждения" in line["text"] or line["text"].lower().startswith("мкб")
        for line in lines
    )


def _inside(line: dict, rect: list[int], width: int, height: int) -> bool:
    cx = (line["x"] + line["w"] / 2) * width
    cy = (line["y"] + line.get("h", 0.012) / 2) * height
    return rect[0] - 4 <= cx <= rect[2] + 4 and rect[1] - 4 <= cy <= rect[3] + 4


def _cell_text(lines: list[dict], rect: list[int], width: int, height: int, used: list[bool]) -> str:
    picked = []
    for index, line in enumerate(lines):
        if used[index] or not _inside(line, rect, width, height):
            continue
        used[index] = True
        picked.append(line)
    picked.sort(key=lambda line: (line["y"], line["x"]))
    return " ".join(line["text"] for line in picked).replace("|", "/").strip()


def _grid(rows: list[list[str]]) -> str:
    if not rows or not any(cell for row in rows for cell in row):
        return ""
    width = max(len(row) for row in rows)
    rows = [row + [""] * (width - len(row)) for row in rows]
    def line(cells: list[str]) -> str:
        return "| " + " | ".join(cells) + " |"
    body = rows[1:]
    rendered = [line(rows[0]), "| " + " | ".join(["---"] * width) + " |"]
    rendered.extend(line(row) for row in body)
    return "\n".join(rendered)


def _diagram(labels: list[str], edges: list[list[int]]) -> str:
    if not any(labels):
        return ""
    out = ["```mermaid", "flowchart TD"]
    for index, label in enumerate(labels):
        text = " ".join(label.split()) or "…"
        text = text.replace('"', "'").replace("[", "(").replace("]", ")").replace("{", "(").replace("}", ")")
        out.append(f'  n{index}["{text}"]')
    for src, dst in edges:
        out.append(f"  n{src} --> n{dst}")
    out.append("```")
    return "\n".join(out)


def laid_out(lines: list[dict], geom: dict) -> str:
    width, height = geom["w"], geom["h"]
    used = [False] * len(lines)
    blocks: list[tuple[float, str]] = []
    for table in geom["tables"]:
        rows = [[_cell_text(lines, cell, width, height, used) for cell in row] for row in table]
        grid = _grid(rows)
        if grid:
            blocks.append((table[0][0][1] / height, grid))
    if geom["nodes"]:
        labels = [_cell_text(lines, node, width, height, used) for node in geom["nodes"]]
        diagram = _diagram(labels, geom["edges"])
        if diagram:
            blocks.append((min(node[1] for node in geom["nodes"]) / height, diagram))
    blocks.sort(key=lambda item: item[0])
    remaining = [
        line for index, line in enumerate(lines)
        if not used[index] and not re.fullmatch(r"[A-Za-z]", line["text"])
    ]
    pieces: list[str] = []
    cursor = 0
    buffer: list[dict] = []
    for y, markdown in blocks:
        while cursor < len(remaining) and remaining[cursor]["y"] < y:
            buffer.append(remaining[cursor])
            cursor += 1
        if buffer:
            pieces.append(prose(buffer))
            buffer = []
        pieces.append(markdown)
    buffer.extend(remaining[cursor:])
    if buffer:
        pieces.append(prose(buffer))
    return "\n\n".join(piece for piece in pieces if piece.strip())


def page_markdown(lines: list[dict], words: list[dict], cover: dict, geom: dict | None = None) -> str:
    del words
    if not lines or is_toc(lines):
        return ""
    if is_cover(lines):
        if cover["done"]:
            return ""
        block = front(lines)
        kept = sum(1 for line in lines if line["conf"] >= 0.45 and line["text"].strip())
        if kept > 30 and not cover["pending"]:
            cover["pending"] = block
            return ""
        cover["done"] = True
        return block
    if geom and (geom["tables"] or geom["nodes"]):
        return laid_out(lines, geom)
    return prose(lines)


def absorb(heading: str, nxt: str) -> tuple[str, str] | None:
    rules = [
        (
            "## 2. Диагностика",
            r"(, медицинские показания и противопоказания к применению методов \S+)\s*(.*)",
        ),
        (
            "## 3. Лечение",
            r"((?:терап\w*, )?диетотерапию, обезболивание, медицинские показания и противопоказания к применению методов лечения)\s*(.*)",
        ),
        (
            "## 4. Медицинская",
            r"(медицинские показания и противопоказания к применению методов реабилитации, в том числе основанных на использовании природных лечебных факторов)\s*(.*)",
        ),
        (
            "## 5. Профилактика",
            r"(показания и противопоказания к применению методов профилактики)\s*(.*)",
        ),
        (
            "### 1.4 ",
            r"(по Международной статистической классификации болезней и проблем, связанных со здоровьем)\s*(.*)",
        ),
    ]
    for prefix, pattern in rules:
        if heading.startswith(prefix):
            match = re.match(pattern, nxt, re.S)
            if match:
                extra = match.group(1).lstrip(", ").strip()
                return heading + " " + extra, match.group(2).strip()
    return None


def finish(text: str) -> str:
    blocks = text.split("\n\n")
    merged: list[str] = []
    index = 0
    while index < len(blocks):
        block = blocks[index]
        if block.startswith("#") and index + 1 < len(blocks):
            joined = absorb(block, blocks[index + 1])
            if joined:
                merged.append(joined[0])
                if joined[1]:
                    merged.append(joined[1])
                index += 2
                continue
        merged.append(block)
        index += 1
    text = "\n\n".join(merged)

    def references(match: re.Match[str]) -> str:
        body = re.sub(r" (?=\d{1,2}\. [A-ZА-Я][a-zа-я])", "\n\n", match.group(1))
        return "## Список литературы\n\n" + body

    text = re.sub(r"## Список литературы\n\n(.*?)(?=\n\n## )", references, text, count=1, flags=re.S)
    return text


def main() -> None:
    source = Path(sys.argv[1])
    target = Path(sys.argv[2])
    with tempfile.TemporaryDirectory() as folder:
        count = render(source, Path(folder))
        parts = []
        cover = {"done": False, "pending": ""}
        for index in range(count):
            image = Path(folder) / f"{index:03d}.png"
            words = json.loads((Path(folder) / f"{index:03d}.json").read_text())
            geom = json.loads((Path(folder) / f"{index:03d}.geom.json").read_text())
            parts.append(page_markdown(read_page(image), words, cover, geom))
            print(f"page {index + 1}/{count}", file=sys.stderr)
        if not cover["done"] and cover["pending"]:
            parts.insert(0, cover["pending"])
    text = finish("\n\n".join(part for part in parts if part.strip())).rstrip() + "\n"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")
    print(target, target.stat().st_size)


if __name__ == "__main__":
    main()
