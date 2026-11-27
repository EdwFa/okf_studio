"""Turn positioned lines and words into Markdown blocks.

Shared by the text-layer extractor and the OCR pass, so both paths
apply the same heading, list, table and diagram rules.
"""

from __future__ import annotations

import re
from statistics import median

from symbols import map_symbol

CYR = set("абвгдеёжзийклмнопрстуфхцчшщъыьэюя")
CHAPTER = (
    "краткая информация",
    "диагностика",
    "лечение",
    "медицинская реабилитация",
    "профилактика",
    "организация оказания",
    "дополнительная информация",
)
NAMED = {
    "список сокращений": 2,
    "термины и определения": 2,
    "список литературы": 2,
    "критерии оценки качества медицинской помощи": 2,
}
# A short token under a word is a hyphenation piece, unless it is its own word.
# Short tokens that are words of their own. A hyphenation piece is not in this set.
STANDALONE = {
    "в", "с", "к", "у", "о", "я", "а", "и", "но", "на", "по", "не", "из", "от", "до", "за",
    "со", "об", "да", "нет", "ни", "же", "ли", "бы", "он", "мы", "вы", "то",
}
BULLET = re.compile(r"^[•●▪◦]\s+")
# A lowercase «о» before a capital word is a round list marker, not the preposition.
CIRCLE = re.compile(r"^[оo]\s+(?=[А-ЯЁA-Z])")
ITEM = re.compile(r"^(?:[•●▪◦]\s+|[а-яa-z][.)]\s+|\d{1,2}[.)]\s+)\S", re.I)
NUMBERED = re.compile(r"^(\d{1,2}(?:\.\d{1,2}){0,3})\.?\s+(\S.*)$")
PERSON = re.compile(r"^[А-ЯЁ][а-яё]+(?:\s+[А-ЯЁ][а-яё]+){1,3}\s+[-–—]")
CODE = re.compile(r"[A-ZА-Я]\d{2}(?:\.\d{1,2})?")


def clean_text(text: str) -> str:
    text = map_symbol(text).replace("\u00ad", "").replace("\xa0", " ")
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"\s+([,.;:%)\]])", r"\1", text)
    text = re.sub(r"([(\[])\s+", r"\1", text)
    return text


def cyr_ratio(text: str) -> float:
    letters = [ch for ch in text if ch.isalpha()]
    if not letters:
        return 0.0
    return sum(ch.lower() in CYR for ch in letters) / len(letters)


def heading_level(text: str, bold: bool = False) -> int | None:
    """Section heading, or None when the line is a list item or a sentence."""
    folded = clean_text(text)
    if not folded:
        return None
    low = folded.lower().rstrip(".")
    if low in NAMED:
        return 2
    if re.match(r"^приложение\b", low):
        return 2
    match = NUMBERED.match(folded)
    if not match:
        return None
    number, rest = match.group(1), match.group(2)
    if int(number.split(".")[0]) > 30:
        return None
    if PERSON.match(rest) or "рекомендуется" in rest.lower():
        return None
    if "." in number:
        if cyr_ratio(rest) < 0.25 and not bold and len(folded) < 24:
            return None
        return min(2 + number.count("."), 5)
    low_rest = rest.lower()
    if any(low_rest.startswith(key) for key in CHAPTER):
        return 2
    if bold and 8 <= len(folded) <= 160 and not rest.endswith(","):
        return 2
    return None


def is_toc(lines: list[str]) -> bool:
    titles = [clean_text(line) for line in lines if clean_text(line)]
    head = titles[:12]
    if any(re.sub(r"\s+", "", line).lower() == "оглавление" for line in head):
        return True
    leaders = sum(1 for line in titles if re.search(r"\.{4,}|…{2,}", line))
    if leaders >= 6:
        return True
    # Several appendix titles and no long prose is a contents page without dot leaders.
    # One «Приложение» heading plus a numbered audience, reference, or score list is the appendix itself.
    long = sum(1 for line in titles if len(line) > 180)
    appendix = sum(1 for line in titles if line.lower().startswith("приложение"))
    return long == 0 and appendix >= 3


def garbage_line(text: str) -> bool:
    """Stamp noise. Short real words and list markers are kept."""
    folded = clean_text(text)
    if not folded:
        return True
    if CODE.search(folded) or re.fullmatch(r"[а-яa-z]{1,3}[.)]?", folded, re.I):
        return False
    letters = sum(ch.isalpha() for ch in folded)
    weird = sum(ch in "*^@#~<>\\" for ch in folded)
    if weird >= 2 or letters == 0:
        return True
    if letters / len(folded) < 0.35 and letters < 8:
        return True
    return False


def is_page_number(text: str, y: float, y1: float, page_h: float) -> bool:
    if not re.fullmatch(r"\d{1,3}", clean_text(text)):
        return False
    band = page_h * 0.055
    return y < band or y1 > page_h - band


def _suffix(prev: dict, nxt: dict) -> bool:
    """A piece of a word broken across two lines, not the next real word."""
    right = nxt["text"]
    left = prev["text"]
    if not right.isalpha() or not left[-1:].isalpha():
        return False
    inside = len(right) <= 5 and nxt["x0"] >= prev["x0"] + 2 and nxt["x1"] <= prev["x1"] - 2
    # Left-aligned stub: «Гемотрансфуз» / «ии», «антиглобулиновы» / «й».
    stub = (
        len(right) <= 3
        and abs(nxt["x0"] - prev["x0"]) <= 2.5
        and right.lower() not in STANDALONE
    )
    if right.lower() in STANDALONE and not inside:
        return False
    return inside or stub


def cell_text(words: list[dict]) -> str:
    """Words whose centers lie in one cell, in reading order."""
    ordered = sorted(words, key=lambda word: (round(word["y0"], 1), word["x0"]))
    rows: list[list[dict]] = []
    for word in ordered:
        if rows and abs(word["y0"] - rows[-1][0]["y0"]) <= 2.8:
            rows[-1].append(word)
        else:
            rows.append([word])
    tokens: list[str] = []
    last: dict | None = None
    for row in rows:
        row.sort(key=lambda word: word["x0"])
        if len(row) == 1 and last is not None and _suffix(last, row[0]):
            tokens[-1] = tokens[-1] + clean_text(row[0]["text"])
            last = {**row[0], "x0": last["x0"], "x1": max(last["x1"], row[0]["x1"]), "text": tokens[-1]}
            continue
        for word in row:
            token = clean_text(word["text"])
            if token:
                tokens.append(token)
                last = word
    return " ".join(tokens).replace("|", "/")


def normalize_criteria(rows: list[list[str]]) -> list[list[str]] | None:
    """The national yes/no quality grid, when the source columns have drifted."""
    hits = 0
    for row in rows:
        cells = {cell.strip() for cell in row}
        if "Да" in cells and "Нет" in cells:
            hits += 1
    if hits < 5:
        return None
    built = [["№", "Критерий", "Да", "Нет"]]
    current: list[str] | None = None
    skip = {"оценка", "выполнения", "критерии качества", "* критерии качества"}
    for row in rows:
        cells = [cell.strip() for cell in row]
        number = cells[0] if cells and re.fullmatch(r"\d{1,2}", cells[0]) else ""
        text = " ".join(
            cell for cell in cells[1:] if cell and cell not in {"Да", "Нет"} and cell.lower() not in skip
        )
        yes = "Да" if "Да" in cells else ""
        no = "Нет" if "Нет" in cells else ""
        if number:
            current = [number, text, yes, no]
            built.append(current)
        elif current is not None and text:
            current[1] = f"{current[1]} {text}".strip()
            current[2] = current[2] or yes
            current[3] = current[3] or no
    return built if len(built) > 5 else None


def merge_continuations(rows: list[list[str]]) -> list[list[str]]:
    """A wrapped line of a numbered row comes back as its own row. Glue it upward."""
    criteria = normalize_criteria(rows)
    if criteria is not None:
        return criteria
    if len(rows) < 2:
        return rows
    width = max(len(row) for row in rows)
    grid = [row + [""] * (width - len(row)) for row in rows]
    merged = [grid[0]]
    marks = {"да", "нет", "х", "+", "-"}
    for row in grid[1:]:
        filled = [index for index, cell in enumerate(row) if cell.strip()]
        numbered = re.fullmatch(r"\d{1,3}", merged[-1][0].strip())
        continuation = (
            numbered
            and row[0].strip() == ""
            and filled
            and all(row[index].strip().lower() not in marks for index in filled)
        )
        if continuation:
            for index in filled:
                merged[-1][index] = f"{merged[-1][index]} {row[index]}".strip()
            continue
        merged.append(row)
    return merged


def markdown_table(rows: list[list[str]]) -> str:
    filled = merge_continuations([row for row in rows if any(cell.strip() for cell in row)])
    if len(filled) < 2:
        return ""
    width = max(len(row) for row in filled)
    grid = [row + [""] * (width - len(row)) for row in filled]
    keep = [index for index in range(width) if any(row[index].strip() for row in grid)]
    if len(keep) < 2:
        return ""
    grid = [[row[index] for index in keep] for row in grid]
    def line(cells: list[str]) -> str:
        return "| " + " | ".join(cell.replace("\n", " ").strip() for cell in cells) + " |"
    body = [line(grid[0]), "| " + " | ".join(["---"] * len(keep)) + " |"]
    body.extend(line(row) for row in grid[1:])
    return "\n".join(body)


def mermaid(labels: list[str], edges: list[tuple[int, int]]) -> str:
    """Boxes and only the arrows that were actually found between them."""
    kept = [(index, label) for index, label in enumerate(labels) if clean_text(label)]
    if len(kept) < 2 or not edges:
        return ""
    remap = {old: new for new, (old, _) in enumerate(kept)}
    used = []
    for src, dst in edges:
        if src in remap and dst in remap and src != dst:
            used.append((remap[src], remap[dst]))
    if not used:
        return ""
    # A sparse graph drops branches. The picture carries the scheme then.
    linked = {node for edge in used for node in edge}
    if len(used) < len(kept) - 1 or len(linked) < len(kept) - 1:
        return ""
    out = ["```mermaid", "flowchart TD"]
    for new, (_, label) in enumerate(kept):
        text = clean_text(label).replace('"', "'")
        for char, repl in (("[", "("), ("]", ")"), ("{", "("), ("}", ")")):
            text = text.replace(char, repl)
        shape = "{" + text + "}" if text.endswith("?") or text.lower().startswith("есть ли") else f'["{text}"]'
        out.append(f"  n{new}{shape}")
    for src, dst in used:
        out.append(f"  n{src} --> n{dst}")
    out.append("```")
    return "\n".join(out)


def label_list(labels: list[str]) -> str:
    items = []
    for label in labels:
        text = clean_text(label)
        if text and text not in items:
            items.append(text)
    if not items:
        return ""
    lines = ["Надписи на схеме:"]
    lines.extend(f"- {item}" for item in items)
    return "\n".join(lines)


def _item_start(text: str) -> bool:
    if heading_level(text) is not None:
        return False
    return ITEM.match(text) is not None or CIRCLE.match(text) is not None or re.fullmatch(r"[а-яa-z][.)]", text, re.I) is not None


def _item_text(text: str) -> str:
    """Graphical bullets become Markdown markers. Letter labels stay in the text."""
    return CIRCLE.sub("", BULLET.sub("", text)).strip()


def _baseline(lines: list[dict]) -> list[dict]:
    """Words that share a baseline are one line, even when the file splits them.

    The tolerance follows the line height, so a PDF point and a 0–1 OCR
    coordinate are not treated as the same unit.
    """
    heights = [line["h"] for line in lines if line.get("h", 0) > 0]
    tol = (median(heights) if heights else 2) * 0.4
    ordered = sorted(lines, key=lambda line: (line["y"], line["x"]))
    rows: list[list[dict]] = []
    for line in ordered:
        if rows and abs(line["y"] - rows[-1][0]["y"]) <= tol:
            rows[-1].append(line)
        else:
            rows.append([line])
    merged = []
    for row in rows:
        row.sort(key=lambda line: line["x"])
        if len(row) == 1:
            merged.append(row[0])
            continue
        merged.append(
            {
                "text": " ".join(line["text"] for line in row),
                "x": row[0]["x"],
                "y": min(line["y"] for line in row),
                "y1": max(line["y1"] for line in row),
                "h": max(line["h"] for line in row),
                "bold": any(line.get("bold") for line in row),
                "italic": any(line.get("italic") for line in row),
            }
        )
    return merged


def _block_start(text: str) -> bool:
    return text.startswith(("Рекомендация", "Уровень убедительности", "Уровень достоверности", "Комментарий", "Комментарии"))


def _gaps(lines: list[dict], page_h: float) -> tuple[float, float]:
    ordered = sorted(lines, key=lambda line: (line["y"], line["x"]))
    gaps = [b["y"] - a["y1"] for a, b in zip(ordered, ordered[1:]) if 0 <= b["y"] - a["y1"] < page_h * 0.15]
    med_gap = median(gaps) if gaps else page_h * 0.012
    # Body lines sit one gap apart. A real paragraph break is clearly larger.
    return med_gap * 1.45, max(med_gap * 1.9, med_gap + 4)


def flow(lines: list[dict], page_h: float) -> list[dict]:
    """Positioned lines → heading, list and paragraph blocks.

    A line dict has text, x, y, y1, h, bold.
    """
    lines = _baseline(lines)
    near_at, break_at = _gaps(lines, page_h)
    prepared: list[dict] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        text = clean_text(line["text"])
        if not text or garbage_line(text) or is_page_number(text, line["y"], line["y1"], page_h):
            index += 1
            continue
        if re.fullmatch(r"[а-яa-z][.)]", text, re.I) and index + 1 < len(lines):
            nxt = lines[index + 1]
            extra = clean_text(nxt["text"])
            if extra and not heading_level(extra, nxt.get("bold", False)) and not _item_start(extra):
                text = f"{text} {extra}"
                line = {**line, "y1": nxt["y1"]}
                index += 1
        level = heading_level(text, line.get("bold", False))
        if level:
            cursor = line
            while index + 1 < len(lines):
                nxt = lines[index + 1]
                extra = clean_text(nxt["text"])
                if not extra or garbage_line(extra) or is_page_number(extra, nxt["y"], nxt["y1"], page_h):
                    index += 1
                    continue
                if heading_level(extra, nxt.get("bold", False)):
                    break
                gap = nxt["y"] - cursor["y1"]
                unclosed = text.count("(") > text.count(")")
                continues = extra[:1].islower() or unclosed
                near = gap < near_at
                if continues and near and len(extra) < 180 and len(text) + len(extra) < 280:
                    text = clean_text(text + " " + extra)
                    cursor = nxt
                    index += 1
                    continue
                break
            prepared.append({"kind": "heading", "level": level, "text": text, "y": line["y"]})
            index += 1
            continue
        prepared.append({**line, "kind": "line", "text": text})
        index += 1

    blocks: list[dict] = []
    buf: list[dict] = []

    def flush() -> None:
        if not buf:
            return
        if _item_start(buf[0]["text"]):
            text = _join([_item_text(buf[0]["text"])] + [item["text"] for item in buf[1:]])
            blocks.append({"type": "list", "text": text, "y": buf[0]["y"]})
        else:
            blocks.append({"type": "para", "text": _join([item["text"] for item in buf]), "y": buf[0]["y"]})
        buf.clear()

    for item in prepared:
        if item["kind"] == "heading":
            flush()
            blocks.append({"type": "heading", "level": item["level"], "text": item["text"], "y": item["y"]})
            continue
        if buf:
            gap = item["y"] - buf[-1]["y1"]
            intro = (
                item["text"].endswith(":")
                and item["text"][:1].isupper()
                and len(item["text"]) < 140
                and buf[-1]["text"].rstrip().endswith((".", "]"))
            )
            if gap > break_at or _item_start(item["text"]) or _block_start(item["text"]) or intro:
                flush()
        buf.append(item)
    flush()
    return blocks


def _join(parts: list[str]) -> str:
    out = ""
    for part in parts:
        if not out:
            out = part
            continue
        if out.endswith("-") and part[:1].islower():
            out = out[:-1] + part
        else:
            out = f"{out} {part}"
    return clean_text(out)


_ABBR_TOKEN = re.compile(r"[A-Za-zА-Яа-яЁё0-9][A-Za-zА-Яа-яЁё0-9./+–\-]*")
_ABBR_SEP = re.compile(r"[ \t]+[-–—]{1,2}[ \t]+")


def _is_abbr(token: str) -> bool:
    """A short code before the dash, not a word from the definition."""
    if token in {"#"} or set(token) <= {"*"} and token:
        return True
    parts = token.split()
    if not parts or len(parts) > 3 or len(token) > 32:
        return False
    if any(len(part) > 24 for part in parts):
        return False
    letters = [ch for ch in token if ch.isalpha()]
    if "/" in token and len(token) <= 12:
        return True
    if letters:
        uppers = sum(ch.isupper() for ch in letters)
        if uppers / len(letters) >= 0.5:
            return True
        if uppers >= 2 and len(token) <= 18:
            return True
        if uppers and (any(ch.isdigit() for ch in token) or "-" in token or "–" in token):
            return True
    if all(len(part) <= 6 for part in parts):
        only = parts[0]
        if len(parts) == 1 and len(only) >= 5 and re.search(r"[а-яё]", only) and not re.search(r"[a-z]", only, re.I):
            return False
        return True
    return False


def _is_strong(token: str) -> bool:
    """A code that stands alone: capitals, a slash pair, a number. Not «en» or «мм»."""
    if not _is_abbr(token):
        return False
    if "/" in token or any(ch.isdigit() for ch in token) or any(ch.isupper() for ch in token):
        return True
    return False


def _abbr_at(before: str) -> int | None:
    """Start index of the abbreviation that ends where `before` ends."""
    text = before.rstrip()
    if not text:
        return None
    mark = re.search(r"(?:(?<=\s)|^)(\*{1,3}|#)$", text)
    if mark:
        return mark.start(1)
    tail_at = max(0, len(text) - 60)
    tail = text[tail_at:]
    tokens = list(_ABBR_TOKEN.finditer(tail))
    if not tokens:
        return None
    last = tokens[-1]
    # «ВОЗ» must not swallow the tail of the previous definition, «(ый)».
    # «ЛТ 5х5 Гр» and «ПЭТ-КТ с FAPI» keep the codes that stand in front of the last one.
    if _is_strong(last.group()):
        group = [last]
        for prev in reversed(tokens[:-1]):
            if len(group) >= 4:
                break
            gap = tail[prev.end():group[0].start()]
            if "(" in gap or ")" in gap:
                break
            word = prev.group()
            if word.lower() in {"с", "и", "по", "на", "от", "для", "в"} or _is_strong(word):
                group.insert(0, prev)
                continue
            break
        return tail_at + group[0].start()
    group = [last]
    for prev in reversed(tokens[:-1]):
        if len(group) >= 3:
            break
        cand = tail[prev.start():last.end()]
        if "  " in cand or not _is_abbr(cand):
            break
        if any(ch.isupper() for ch in prev.group()):
            break
        group.insert(0, prev)
    cand = tail[group[0].start():last.end()]
    if _is_abbr(cand):
        return tail_at + group[0].start()
    return None


def abbreviation_entries(text: str) -> list[str]:
    """One abbreviation per item. A definition may stay wrapped onto the entry."""
    starts = []
    for match in _ABBR_SEP.finditer(text):
        at = _abbr_at(text[: match.start()])
        if at is None:
            continue
        starts.append(at)
    # «TNM (аббревиатура …) — определение»: the code stands before the parenthesis, not before the dash.
    for match in re.finditer(r"(?<=\)\s)([A-ZА-ЯЁ][A-ZА-ЯЁ0-9/+–\-]{1,16})(?=\s+\()", text):
        starts.append(match.start(1))
    starts = sorted(set(starts))
    if len(starts) < 2:
        return [text.strip()] if text.strip() else []
    parts = []
    lead = text[: starts[0]].strip()
    if lead:
        parts.append(lead)
    for index, start in enumerate(starts):
        end = starts[index + 1] if index + 1 < len(starts) else len(text)
        piece = text[start:end].strip()
        if piece:
            parts.append(piece)
    return parts or [text.strip()]


def _table_cells(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def _separator_row(cells: list[str]) -> bool:
    body = [cell.replace(" ", "") for cell in cells if cell]
    return bool(body) and all(re.fullmatch(r":?-{3,}:?", cell) for cell in body)


def _parse_grid(block: str) -> list[list[str]] | None:
    lines = [line for line in block.splitlines() if line.startswith("|")]
    if len(lines) < 2 or len(lines) != len([line for line in block.splitlines() if line.strip()]):
        return None
    rows = [_table_cells(line) for line in lines]
    if not _separator_row(rows[1]):
        return None
    width = max(len(row) for row in rows)
    return [row + [""] * (width - len(row)) for row in rows]


def _render_grid(rows: list[list[str]]) -> str:
    def line(cells: list[str]) -> str:
        return "| " + " | ".join(cells) + " |"
    return "\n".join(line(row) for row in rows)


def _glue_cell(left: str, right: str) -> str:
    left, right = left.strip(), right.strip()
    if not right or left == right:
        return left
    if not left:
        return right
    if left.endswith("-") and right[:1].islower():
        return left[:-1] + right
    return f"{left} {right}"


def _row_number(cell: str) -> int | None:
    match = re.fullmatch(r"\d{1,3}\.?", cell.strip())
    return int(match.group().rstrip(".")) if match else None


def _continued_numbers(prev: list[list[str]], grid: list[list[str]]) -> bool:
    """The next page of a numbered table has no repeated header. Its first row is data."""
    if len(prev[0]) != len(grid[0]):
        return False
    nxt = _row_number(grid[0][0])
    if nxt is None:
        return False
    last = None
    for row in reversed(prev[2:]):
        last = _row_number(row[0])
        if last is not None:
            break
    return last is not None and nxt == last + 1


def _image_block(block: str) -> bool:
    text = block.strip()
    return text.startswith("![") and "\n" not in text


def _previous_grid(out: list[str]) -> int | None:
    """The table this page continues, skipping the snapshot pictures placed between the parts."""
    for index in range(len(out) - 1, -1, -1):
        if _parse_grid(out[index]):
            return index
        if not _image_block(out[index]):
            return None
    return None


def merge_split_tables(md: str) -> str:
    """A table continued on the next page repeats its header. Keep the header once.

    The row that was cut by the page edge comes back with an empty first cell.
    Its text belongs to the last row of the previous part. A numbered table that
    does not repeat the header is one grid, not a new table starting at the next row.
    A picture of the table may sit between the two parts.
    """
    blocks = md.split("\n\n")
    out: list[str] = []
    for block in blocks:
        grid = _parse_grid(block)
        prev_at = _previous_grid(out) if grid is not None else None
        if grid is None or prev_at is None:
            out.append(block)
            continue
        prev = _parse_grid(out[prev_at])
        same_header = [cell.lower() for cell in prev[0]] == [cell.lower() for cell in grid[0]]
        blank_lead = len(prev[0]) == len(grid[0]) and not grid[0][0].strip()
        if not same_header and not _continued_numbers(prev, grid) and not blank_lead:
            out.append(block)
            continue
        if same_header:
            body = grid[2:]
            if body and not body[0][0].strip():
                prev[-1] = [_glue_cell(left, right) for left, right in zip(prev[-1], body[0])]
                body = body[1:]
        elif blank_lead:
            # Empty first cell is the next drug row of a spanned regimen, not a cut sentence.
            body = [grid[0], *grid[2:]]
        else:
            body = [grid[0], *grid[2:]]
        prev.extend(body)
        out[prev_at] = _render_grid(prev)
    text = "\n\n".join(out)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return text + "\n"


def split_abbreviation_section(md: str) -> str:
    """In «Список сокращений» each abbreviation starts on its own line."""
    out: list[str] = []
    in_abbr = False
    for line in md.split("\n"):
        if line.startswith("#"):
            name = re.sub(r"^#+\s*", "", line).strip().lower().replace("ё", "е")
            in_abbr = name.startswith("список сокращений")
            out.append(line)
            continue
        if in_abbr and line.strip() and not line.startswith(("|", "!", "-", "```")):
            parts = abbreviation_entries(line.strip())
            if len(parts) > 1:
                for part in parts:
                    out.extend(["", part])
                continue
        out.append(line)
    text = "\n".join(out)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return text + "\n"


def promote_title(blocks: list[dict]) -> list[dict]:
    """The line above the ICD coding line is the document title."""
    texts = [block["text"] for block in blocks]
    if any(block["type"] == "heading" and block.get("level") == 1 for block in blocks):
        return blocks
    coding = next((i for i, text in enumerate(texts) if text.lower().startswith("кодирование")), None)
    if coding is None:
        return blocks
    title = ""
    for text in reversed(texts[:coding]):
        if 12 <= len(text) <= 180 and cyr_ratio(text) > 0.5 and not text.lower().startswith("утвержден"):
            title = text
            break
    if not title:
        return blocks
    out = []
    used = False
    for block in blocks:
        if not used and block["text"] == title:
            out.append({"type": "heading", "level": 1, "text": title, "y": block["y"]})
            used = True
        else:
            out.append(block)
    return out
