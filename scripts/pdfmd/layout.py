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
    # «XVII. Приложение Б» is the appendix heading. The roman prefix is the contents number.
    roman = re.match(r"^[IVX]{1,6}\.\s+(\S.*)$", folded)
    if roman and roman.group(1).lower().startswith("приложение"):
        folded = roman.group(1)
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
    long = sum(1 for line in titles if len(line) > 180)
    if leaders >= 6:
        return True
    # A leftover contents page: two dotted lines and no prose («Приложение А3 …53»).
    if leaders >= 2 and long == 0 and leaders * 2 >= len(titles):
        return True
    # Several appendix titles and no long prose is a contents page without dot leaders.
    # One «Приложение» heading plus a numbered audience, reference, or score list is the appendix itself.
    appendix = sum(1 for line in titles if line.lower().startswith("приложение"))
    # A contents page is mostly appendix titles. Three headings above the appendix text are the appendix.
    return long == 0 and appendix >= 3 and appendix * 2 >= len(titles)


def _contents_piece(piece: str) -> bool:
    """An appendix title or a dotted contents line, not a sentence of the document."""
    body = piece.lstrip("#").strip().lower()
    if piece.startswith("#") and body.startswith("приложение"):
        return True
    return bool(re.search(r"\.{4,}|…{2,}", piece))


_ABBR_HEAD = re.compile(r"^Список сокращений\b\s*", re.I)


def lift_abbreviation_heading(pieces: list[str]) -> list[str]:
    """«Список сокращений» fell into the first definition cell of the abbreviation grid."""
    out: list[str] = []
    for piece in pieces:
        grid = _parse_grid(piece)
        if grid is None:
            out.append(piece)
            continue
        lifted = False
        for row in grid:
            if _separator_row(row):
                continue
            for index, cell in enumerate(row):
                if not _ABBR_HEAD.match(cell.strip()):
                    continue
                row[index] = _ABBR_HEAD.sub("", cell.strip(), count=1).strip()
                lifted = True
                break
            if lifted:
                break
        if lifted:
            out.append("## Список сокращений")
            out.append(_render_grid(grid))
        else:
            out.append(piece)
    return out


def drop_contents_tail(pieces: list[str]) -> list[str]:
    """Appendix titles with no body, right before the abbreviation list, are the contents tail."""
    out: list[str] = []
    index = 0
    while index < len(pieces):
        if _contents_piece(pieces[index]):
            end = index
            while end < len(pieces) and _contents_piece(pieces[end]):
                end += 1
            following = pieces[end].lstrip("#").strip().lower() if end < len(pieces) else ""
            if end - index >= 2 and following.startswith("список сокращений"):
                index = end
                continue
        out.append(pieces[index])
        index += 1
    return out


def garbled_span(text: str) -> bool:
    """A stamp font left several symbols inside one word.

    One apostrophe or one ampersand is an email, a URL, or a bibliography line.
    """
    if "@" in text or "://" in text:
        return False
    for token in text.split():
        if len(token) < 6:
            continue
        marks = {ch for ch in token if ch in "&'|;"}
        if len(marks) >= 2 and any(ch.isalpha() for ch in token):
            return True
    return False


def garbage_line(text: str) -> bool:
    """Stamp noise. Short real words and list markers are kept."""
    folded = clean_text(text)
    if not folded:
        return True
    # A detached electronic signature is stamp text, not the recommendation.
    if re.search(r"СНИЛС=|ОГРН=|\bOID\.\d", folded):
        return True
    if re.search(r"Документ подписан и передан через систему", folded, re.I):
        return True
    if "Владелец сертификата" in folded and "Сертификат" in folded:
        return True
    if re.search(r"ДОКУМЕНТ ПОДПИСАН", folded) and "Сертификат" in folded:
        return True
    if re.search(r"\bE=\S+@\S+.*\bC=RU\b", folded):
        return True
    if CODE.search(folded) or re.fullmatch(r"[а-яa-z]{1,3}[.)]?", folded, re.I):
        return False
    # A leading ** is a footnote. #drug** is a formulary mark, not stamp noise.
    body = re.sub(r"^[*]{1,3}(?=\s|[А-ЯЁA-Zа-яёa-z])", "", folded)
    body = re.sub(r"(?<=\w)[*]{1,3}", "", body)
    body = re.sub(r"#(?=\w)", "", body)
    letters = sum(ch.isalpha() for ch in body)
    # «PaO < 60» is a comparison. Two «<» are not stamp noise.
    comparable = re.sub(r"<\s*\d", "", body)
    weird = sum(ch in "*^@#~<>\\" for ch in comparable)
    if re.fullmatch(r"[+±−–-]\s*\d{1,3}", body):
        return False
    # A citation cut onto its own line («118];», «[115]);») has no letters.
    if letters == 0 and re.fullmatch(r"[\d\[\]().,;:–—\-]+", body) and re.search(r"\d", body) and re.search(r"[\[\]()–—\-]", body):
        return False
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


# A TNM index is a short token drawn smaller, flush with the letter and below its baseline.
_INDEX = re.compile(r"^(?:is|mi|mic|sn|\d{1,2}(?:mi|mic|[a-d])?|[a-dx])$", re.I)


def _attach_subscripts(words: list[dict]) -> list[dict]:
    """Glue a lower index onto the letter it belongs to.

    The text layer stores T1 as «T» plus a 6-pt «1» whose top sits under the
    baseline. Reading by line then dumps every index at the end of the cell.
    A superscript (the «2» of мг/м², a footnote) sits above the baseline and
    is left alone.
    """
    pending = [dict(word) for word in words]
    used: set[int] = set()
    for index, script in enumerate(pending):
        text = script.get("text") or ""
        if not _INDEX.fullmatch(text):
            continue
        height = script["y1"] - script["y0"]
        if height <= 0:
            continue
        best = None
        best_dy = 99.0
        for other, base in enumerate(pending):
            if other == index or other in used:
                continue
            base_h = base["y1"] - base["y0"]
            if base_h < 1 or height > base_h * 0.88:
                continue
            if script["x0"] < base["x1"] - 0.8 or script["x0"] - base["x1"] > 1.6:
                continue
            if script["y0"] < base["y0"] + 2 or script["y0"] >= base["y1"]:
                continue
            if not re.search(r"[0-9A-Za-zА-Яа-яЁё]$", base.get("text") or ""):
                continue
            dy = script["y0"] - base["y0"]
            if dy < best_dy:
                best, best_dy = other, dy
        if best is None:
            continue
        base = pending[best]
        base["text"] = base["text"] + text
        base["x1"] = max(base["x1"], script["x1"])
        base["y1"] = max(base["y1"], script["y1"])
        used.add(index)
    return [word for index, word in enumerate(pending) if index not in used]


def tracked_figure(words: list[dict]) -> bool:
    """A caption set one letter at a time across a figure, not a paragraph.

    Body text also has single-letter prepositions. A figure page is mostly those
    spaced letters, with a run of them sitting a few points apart.
    """
    if len(words) < 16:
        return False
    singles = [word for word in words if len(word.get("text") or "") == 1 and word["text"].isalpha()]
    if len(singles) < 12 or len(singles) / len(words) < 0.45:
        return False
    singles.sort(key=lambda word: (round(word["y0"], 0), word["x0"]))
    run = best = 1
    for prev, nxt in zip(singles, singles[1:]):
        if abs(nxt["y0"] - prev["y0"]) <= 2 and 0 <= nxt["x0"] - prev["x0"] <= 9:
            run += 1
            best = max(best, run)
        else:
            run = 1
    return best >= 6


# A finished Russian word. The next line is then a new word, not the cut ending.
_WORD_END = (
    "ая", "яя", "ое", "ее", "ые", "ие", "ия", "ой", "ый", "ий", "ей",
    "ость", "есть", "ого", "его",
    "ых", "их", "ов", "ев", "ам", "ям", "ах", "ях", "ом", "ем", "ым", "им",
)


def _broken_piece(prev: dict, nxt: dict) -> bool:
    """The first token of the next line is the rest of a word cut by the cell edge.

    «самообслуживани» / «ю,» and «гиперпигме» / «нтация». A finished word
    («папулезная» / «сыпь») stays two words.
    """
    raw = nxt["text"]
    core = raw.rstrip(".,;:)")
    if not core.isalpha() or not core.islower():
        return False
    left = prev["text"]
    if not left or left.endswith("-") or not left[-1].isalpha():
        return False
    if len(left) < 8 or len(core) > 6:
        return False
    if any(left.endswith(end) for end in _WORD_END):
        return False
    # «или», «при», «в» start the next line. A cut ending does not.
    if core in STANDALONE or core in {"или", "для", "при", "под", "без", "над", "про", "как", "что"}:
        return len(core) == 1 and raw[len(core):len(core) + 1] in {",", ".", ";", ":"}
    if nxt["x0"] < prev["x0"] - 6:
        return True
    if abs(nxt["x0"] - prev["x0"]) <= 3 and nxt["x1"] <= prev["x1"] - 2 and len(core) <= 6:
        return True
    return False


def _suffix(prev: dict, nxt: dict) -> bool:
    """A piece of a word broken across two lines, not the next real word."""
    right = nxt["text"]
    left = prev["text"]
    # A line-break hyphen is not part of the stem: «промежуточ-» / «ный».
    core = left[:-1] if left.endswith("-") else left
    if not core or not right.isalpha() or not core[-1].isalpha():
        return False
    # «квадрипликацией» / «α» is the next word. A cut stem does not end like a finished word.
    if not left.endswith("-") and any(core.endswith(end) for end in _WORD_END):
        return False
    # «Степень» / «НАС» is the next line of a header, not a broken word.
    if right.isupper() and len(right) >= 2 and len(core) >= 4:
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
    ordered = sorted(_attach_subscripts(words), key=lambda word: (round(word["y0"], 1), word["x0"]))
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
        if last is not None and row and _broken_piece(last, row[0]):
            piece = clean_text(row[0]["text"])
            tokens[-1] = tokens[-1] + piece
            last = {
                **row[0],
                "x0": last["x0"],
                "x1": max(last["x1"], row[0]["x1"]),
                "text": tokens[-1],
            }
            row = row[1:]
        if len(row) == 1 and last is not None and _suffix(last, row[0]):
            piece = clean_text(row[0]["text"])
            # The hyphen belongs to the line break («промежуточ-» / «ный»), not to the word.
            if tokens[-1].endswith("-") and piece[:1].islower():
                tokens[-1] = tokens[-1][:-1] + piece
            else:
                tokens[-1] = tokens[-1] + piece
            last = {**row[0], "x0": last["x0"], "x1": max(last["x1"], row[0]["x1"]), "text": tokens[-1]}
            continue
        for word in row:
            token = clean_text(word["text"])
            if not token:
                continue
            # «12-» / «перстной» keeps the hyphen. A letter stem is a line break and is handled above.
            if tokens and tokens[-1].endswith("-") and token[:1].islower():
                stem = tokens[-1][:-1]
                # «12-» / «перстной» and «патолого-» / «анатомического» keep the hyphen.
                # A short alphabetic stub is a line-break hyphen and is joined above.
                if stem.isalpha() or any(ch.isdigit() for ch in stem):
                    tokens[-1] = tokens[-1] + token
                    last = word
                    continue
            tokens.append(token)
            last = word
    text = " ".join(tokens).replace("|", "/")
    text = re.sub(r"\s+([,.;:%)\]])", r"\1", text)
    text = re.sub(r"([(\[])\s+", r"\1", text)
    return text


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


_STRAY_WORD = {
    "и", "в", "с", "к", "у", "о", "а", "я", "на", "по", "за", "от", "до", "из", "не", "но", "или",
}


def _fold_dose_tail(rows: list[list[str]]) -> list[list[str]]:
    """«3 мг/кг или» and «240 мг» are one dose, split by the page edge."""
    if len(rows) < 4:
        return rows
    head, rule = rows[0], rows[1]
    folded: list[list[str]] = []
    for row in rows[2:]:
        filled = [index for index, cell in enumerate(row) if cell.strip()]
        if folded and len(filled) == 1 and len(row) == len(folded[-1]):
            index = filled[0]
            tail = row[index].strip()
            above = folded[-1][index].strip()
            if (
                above
                and above[-1] not in ".!?;:"
                and tail[:1].isdigit()
                and not re.fullmatch(r"\d{1,3}", tail)
            ):
                folded[-1][index] = _glue_cell(above, tail)
                continue
        folded.append(list(row))
    return [head, rule, *folded]


def _fold_stray_edge(rows: list[list[str]]) -> list[list[str]]:
    """The last word of a wrapped line fell past the right rule and became its own column."""
    if not rows:
        return rows
    width = max(len(row) for row in rows)
    if width < 3:
        return rows
    grid = [row + [""] * (width - len(row)) for row in rows]
    bits = [row[-1].strip() for row in grid]
    nonempty = [bit for bit in bits if bit]
    if len(nonempty) < 2:
        return rows
    if any(len(bit.split()) != 1 or bit.lower() not in _STRAY_WORD for bit in nonempty):
        return rows
    if not any(len(row[-2]) > 20 for row in grid):
        return rows
    folded = []
    for row in grid:
        bit = row[-1].strip()
        if bit:
            row[-2] = f"{row[-2]} {bit}".strip()
        folded.append(row[:-1])
    return folded


def _header_fragment(row: list[str]) -> bool:
    """The second line of a wrapped header: empty scheme and drug cells, lowercase tails."""
    if len(row) < 4 or row[0].strip() or row[1].strip():
        return False
    filled = [cell.strip() for cell in row[2:] if cell.strip()]
    if len(filled) < 2:
        return False
    return all(cell[:1].islower() and not any(ch.isdigit() for ch in cell) for cell in filled)


def _join_wrap(left: str, right: str) -> str:
    """A wrapped criterion line. A long word keeps a real hyphen; a short stub does not."""
    left, right = left.strip(), right.strip()
    if left.endswith("-") and right[:1].islower() and len(right) > 4:
        return left + right
    return _glue_cell(left, right)


def fold_wrapped_criteria(rows: list[list[str]]) -> list[list[str]] | None:
    """Each line of a wrapped yes/no criterion became its own row. One criterion is one row.

    The row number is drawn in the middle of a tall cell, so the first line of the
    next criterion can sit above that number. «Да/Нет» sits on whichever line it fits.
    """
    if len(rows) < 3:
        return None
    head = " ".join(cell.strip() for row in rows[:3] for cell in row).lower()
    compact = " ".join(cell.strip() for row in rows for cell in row).replace(" ", "").lower()
    if "да/нет" not in compact:
        return None
    number_re = re.compile(r"^\d{1,2}\.?$")
    numbers = 0
    empty_leads = 0
    parsed: list[tuple[str, str, str]] = []
    for row in rows:
        if not row or not row[0].strip():
            empty_leads += 1
        number = ""
        mark = ""
        texts: list[str] = []
        for cell in row:
            shown = cell.strip()
            if not shown:
                continue
            token = re.sub(r"\s+", "", shown)
            if number_re.fullmatch(token):
                number = token if token.endswith(".") else token + "."
                numbers += 1
                continue
            if token.lower() == "да/нет":
                mark = "Да/Нет"
                continue
            if shown.lower() in {"№", "оценка", "п/п", "выполнения", "критерии оценки качества"}:
                continue
            texts.append(shown)
        parsed.append((number, " ".join(texts), mark))
    titled = "критерии" in head and "оценка" in head
    if numbers < 1 or (not titled and (numbers < 1 or empty_leads < 2)):
        return None
    items: list[dict] = []
    current: dict | None = None

    def close() -> None:
        nonlocal current
        if current and (current["n"] or current["parts"]):
            items.append(current)
        current = None

    for number, text, mark in parsed:
        if number:
            if current is not None:
                prev = " ".join(current["parts"]).rstrip()
                if current["n"] != number and (current["n"] or (prev and prev[-1] in ").")):
                    close()
            if current is None:
                current = {"n": number, "parts": [], "mark": ""}
            current["n"] = number
            if text:
                current["parts"].append(text)
            if mark:
                current["mark"] = mark
            continue
        if not text and not mark:
            continue
        prev = " ".join(current["parts"]).rstrip() if current else ""
        if current is not None and prev and prev[-1] in ")." and text[:1].isupper():
            close()
        if current is None:
            current = {"n": "", "parts": [], "mark": ""}
        if text:
            current["parts"].append(text)
        if mark:
            current["mark"] = mark
    close()
    if len([item for item in items if item["n"]]) < 1:
        return None
    if not titled and len([item for item in items if item["n"]]) < 1:
        return None
    built = [["№", "Критерии оценки качества", "Оценка выполнения"]]
    for item in items:
        text = ""
        for part in item["parts"]:
            text = _join_wrap(text, part) if text else part
        built.append([item["n"], text, item["mark"]])
    return built if len(built) > 2 else None


def _pull_span_text(rows: list[list[str]]) -> list[list[str]]:
    """A colspan left the description in an empty header column, beside a blank cell.

    «1. | | Систематические обзоры» belongs in the «Источник» column.
    """
    if len(rows) < 2:
        return rows
    header = rows[0]
    width = len(header)
    for row in rows[1:]:
        lead = row[0].strip().rstrip(".")
        if not (re.fullmatch(r"\d{1,3}", lead) or re.fullmatch(r"[A-DАВСД]", lead)):
            continue
        for col in range(width - 1, 0, -1):
            if col >= len(row) or header[col].strip() or not header[col - 1].strip():
                continue
            if row[col].strip() and not row[col - 1].strip():
                row[col - 1] = row[col]
                row[col] = ""
    return rows


def merge_continuations(rows: list[list[str]]) -> list[list[str]]:
    """A wrapped line of a numbered row comes back as its own row. Glue it upward."""
    folded = fold_wrapped_criteria(rows)
    if folded is not None:
        return folded
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
        # «Путь / введения» is one header cell, not a data row.
        # «Балл 1» / «гинекологичес» is the next page of the body, not the header.
        if _header_fragment(row):
            targets = [
                merged[0][index].strip()
                for index, cell in enumerate(row)
                if cell.strip() and index < len(merged[0])
            ]
            if targets and all(cell and not cell[-1].isdigit() for cell in targets):
                merged[0] = [
                    _glue_cell(left, right) if right.strip() else left
                    for left, right in zip(merged[0], row)
                ]
                continue
        filled = [index for index, cell in enumerate(row) if cell.strip()]
        lead = merged[-1][0].strip()
        numbered = re.fullmatch(r"\d{1,3}\.?", lead) or re.fullmatch(r"[A-DАВСД]", lead)
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
        # «Уровень» / «достоверности» / «доказательств» is one wrapped header cell.
        word = row[0].strip()
        if (
            re.fullmatch(r"[а-яё]+", word)
            and all(not cell.strip() for cell in row[1:])
            and merged[-1][0].strip()
            and merged[-1][0].strip()[-1] not in ".!?;:"
        ):
            merged[-1][0] = f"{merged[-1][0].strip()} {word}"
            continue
        # «-α/-α,» / «-α/αТα» is the same cell, wrapped onto the next ruled line.
        filled = [index for index, cell in enumerate(row) if cell.strip()]
        if (
            row[0].strip() == ""
            and merged[-1][0].strip()
            and filled
            and all(
                index < len(merged[-1]) and merged[-1][index].rstrip().endswith((",", "/", "–"))
                for index in filled
            )
        ):
            for index in filled:
                merged[-1][index] = _glue_cell(merged[-1][index], row[index])
            continue
        merged.append(row)
    return _pull_span_text(merged)


def _pull_shifted_index(rows: list[list[str]]) -> list[list[str]]:
    """A wrapped cell put the row index on the last line, next to the last word.

    «3-7 | кремом» belongs to the lines above it: the index starts that cell, the word ends it.
    """
    if not rows or max(len(row) for row in rows) < 2:
        return rows
    work = [list(row) for row in rows]
    moves: list[tuple[int, int]] = []
    for index, row in enumerate(rows):
        lead = row[0].strip()
        rest = " ".join(cell.strip() for cell in row[1:] if cell.strip())
        if not re.fullmatch(r"\d{1,2}(?:-\d{1,2})?", lead):
            continue
        if not rest or not rest[:1].islower() or len(rest.split()) > 2 or len(rest) > 16:
            continue
        start = index
        while start > 0 and not rows[start - 1][0].strip():
            start -= 1
        if start == index:
            continue
        moves.append((start, index))
    if not moves:
        return rows
    for start, index in moves:
        row = work[index]
        work[start][0] = row[0].strip()
        for col, cell in enumerate(row[1:], start=1):
            if cell.strip():
                work[index - 1][col] = f"{work[index - 1][col]} {cell}".strip()
        work[index] = [""] * len(row)
    folded: list[list[str]] = []
    for row in work:
        if not any(cell.strip() for cell in row):
            continue
        if folded and not row[0].strip():
            for col, cell in enumerate(row):
                if col and cell.strip():
                    folded[-1][col] = f"{folded[-1][col]} {cell}".strip()
            continue
        folded.append(row)
    return folded


def _shift_into_gap(rows: list[list[str]]) -> list[list[str]]:
    """Text fell one column right of an empty cell. Those two columns are one column."""
    if not rows:
        return rows
    width = max(len(row) for row in rows)
    grid = [row + [""] * (width - len(row)) for row in rows]
    for col in range(width - 1, 0, -1):
        if any(row[col].strip() and row[col - 1].strip() for row in grid):
            continue
        if not any(row[col].strip() for row in grid):
            continue
        for row in grid:
            if row[col].strip() and not row[col - 1].strip():
                row[col - 1] = row[col]
                row[col] = ""
    return grid


def markdown_table(rows: list[list[str]]) -> str:
    rows = _fold_stray_edge(_pull_shifted_index(rows))
    filled = _shift_into_gap(merge_continuations([row for row in rows if any(cell.strip() for cell in row)]))
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


# A box label cut off mid-phrase ends on a conjunction. The arrows then do not match the drawing.
_DANGLING = re.compile(r"(?:^|\s)(?:или|либо|для|при|над|под|между|после|перед)$", re.I)


def _cut_label(label: str) -> bool:
    return _DANGLING.search(clean_text(label)) is not None


def _glued_label(label: str) -> bool:
    """Several boxes read as one node repeat a word with nothing between the copies."""
    tokens = label.split()
    for left, right in zip(tokens, tokens[1:]):
        a = re.sub(r"[^0-9A-Za-zА-Яа-яЁё]", "", left).lower()
        b = re.sub(r"[^0-9A-Za-zА-Яа-яЁё]", "", right).lower()
        if len(a) >= 6 and a == b:
            return True
    return False


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
    # Glued labels mean the boxes were merged, so the arrows do not match the drawing.
    if any(_glued_label(clean_text(label)) or _cut_label(label) for _, label in kept):
        return ""
    # A table read as boxes glues a whole header into one node. A flowchart label is short.
    if any(len(clean_text(label).split()) > 8 for _, label in kept):
        return ""
    # Percentile cells are numbers, not flowchart boxes.
    numeric = 0
    for _, label in kept:
        text = clean_text(label)
        if sum(ch.isdigit() for ch in text) >= 3 and sum(ch.isalpha() for ch in text) <= 6:
            numeric += 1
    if numeric >= max(3, len(kept) // 2):
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
        # A pipe in the left margin is not a column. «| инструменты» is one heading line.
        kept = []
        for index, frag in enumerate(row):
            nxt = row[index + 1] if index + 1 < len(row) else None
            gap = (nxt["x"] - frag.get("x1", frag["x"])) if nxt else 0
            if frag["text"].strip() == "|" and nxt and gap > 14:
                continue
            kept.append(frag)
        row = kept
        if not row:
            continue
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


def _stamp_anchor(text: str) -> bool:
    folded = clean_text(text)
    if re.search(r"ДОКУМЕНТ ПОДПИСАН|Документ подписан и передан", folded):
        return True
    if re.search(r"Сертификат:\s*серийный номер", folded):
        return True
    if re.search(r"\bE=\S+@\S+", folded) and "C=RU" in folded:
        return True
    if "СНИЛС=" in folded or "ОГРН=" in folded:
        return True
    return False


def _drop_stamp(lines: list[dict]) -> list[dict]:
    """An electronic-signature stamp is a cluster of short lines, not the recommendation."""
    anchors = [index for index, line in enumerate(lines) if _stamp_anchor(line["text"])]
    if not anchors:
        return lines
    drop: set[int] = set()
    for anchor in anchors:
        start = anchor
        while start > 0:
            prev = lines[start - 1]
            gap = lines[start]["y"] - prev["y1"]
            prev_text = clean_text(prev["text"])
            if gap > 18 or len(prev_text) > 80 or prev_text.endswith("."):
                break
            start -= 1
        for index in range(start, len(lines)):
            if index > anchor:
                nxt = clean_text(lines[index]["text"])
                if nxt.startswith(("Приложение", "Рекоменд")) or (
                    len(nxt) > 80 and lines[index]["y"] - lines[index - 1]["y1"] > 12
                ):
                    break
            drop.add(index)
    return [line for index, line in enumerate(lines) if index not in drop]


def flow(lines: list[dict], page_h: float) -> list[dict]:
    """Positioned lines → heading, list and paragraph blocks.

    A line dict has text, x, y, y1, h, bold.
    """
    lines = _drop_stamp(_baseline(lines))
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
                # «нет» / «да» is a flowchart answer, not the rest of the heading.
                if extra.lower() in {"нет", "да"}:
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
        elif re.search(r"\d[-–—]$", out) and part[:1].isdigit():
            out = out + part
        else:
            out = f"{out} {part}"
    return clean_text(out)


_ABBR_TOKEN = re.compile(r"[A-Za-zА-Яа-яЁё0-9][A-Za-zА-Яа-яЁё0-9./+–\-]*")
_ABBR_SEP = re.compile(
    r"[ \t]+[-–—‒−]{1,2}(?:[ \t]+|(?=[А-Яа-яЁё]))|(?<=[A-ZА-ЯЁ0-9])[-–—‒−][ \t]+"
)
# A dose at the end of a definition («СОД 25 Гр») is not the next abbreviation.
_DOSE_UNIT = {"гр", "мг", "мкг", "мл", "мкл", "см", "мм", "кг", "нг", "ме", "ед", "gy"}


def _dose_unit(word: str) -> bool:
    head = word.lower().rstrip(".").split("/")[0]
    return head in _DOSE_UNIT


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
            # «Эпштейна-Барр» is a name. A code's pieces are short («ПЭТ-КТ», «АСЛ-О»).
            chunks = re.split(r"[-–]", token)
            if not any(len(chunk) > 4 and chunk[:1].isupper() and chunk[1:].islower() for chunk in chunks):
                return True
        if uppers and (any(ch.isdigit() for ch in token) or "-" in token or "–" in token):
            # «антистрептолизин-О» is a word. A hyphenated code is short or mostly capitals.
            if not (len(token) > 12 and uppers / len(letters) < 0.5):
                return True
    if all(len(part) <= 6 for part in parts):
        only = parts[0]
        # «Барр» and «Asthma» are words. A code is capitals («ВОЗ», «ARIA») or a digit.
        if len(parts) == 1 and re.fullmatch(r"[А-ЯЁA-Z][а-яёa-z]+", only):
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
    # «Печеночные» ферменты — определение. The quoted term is the next entry.
    quoted = re.search(
        r"(?:(?<=\s)|^)(«[^»]{1,40}»(?:\s+(?:[а-яё]{1,24}|[А-ЯЁ][а-яё]{2,24})){0,3})\s*$",
        text,
    )
    if quoted and text[: quoted.start()].strip():
        return quoted.start(1)
    # «Тиопурины — …» and «Аминосалициловая кислота и аналогичные препараты — …».
    # Latin title case stays in the definition («Asthma»). A hyphenated name («Эпштейна-Барр») stays too.
    titled = re.search(
        r"(?:(?<=\s)|^)([А-ЯЁ][а-яё]{2,24}(?:\s+(?:[а-яё]{1,24}|[А-ЯЁ][а-яё]{2,24})){0,8})\s*$",
        text,
    )
    if titled and text[: titled.start()].strip() and not text[: titled.start()].endswith("-"):
        return titled.start(1)
    # «MINEN (mixed ...) — определение»: the code stands before the parenthesis.
    wrapped = re.search(
        r"(?:(?<=\s)|^)([A-ZА-ЯЁ][A-ZА-ЯЁ0-9/+–\-]{0,24})\*?\s+\([^()]*\)\s*$",
        text,
    )
    if wrapped:
        return wrapped.start(1)
    # «Вах (BCL2 …)» and «Bcl-2 (B-Cell …)» are the next code, not the tail of the definition.
    named = re.search(
        r"(?:(?<=\s)|^)([А-ЯЁ][а-яё]{2,16}|[A-Z][A-Za-z0-9]{1,16}(?:-[A-Za-z0-9]+)?)\s+\([^()]*\)\s*$",
        text,
    )
    if named and text[: named.start()].strip() and not text[: named.start()].rstrip().endswith("-"):
        return named.start(1)
    tail_at = max(0, len(text) - 60)
    tail = text[tail_at:]
    tokens = list(_ABBR_TOKEN.finditer(tail))
    if not tokens:
        return None
    last = tokens[-1]
    # «хелперы Treg — …»: a short Latin code after a Cyrillic definition. «on Asthma» stays put.
    if re.fullmatch(r"[A-Z][a-z]{1,8}(?:-[A-Za-z0-9]+)?", last.group()):
        prev = text[: tail_at + last.start()].rstrip()
        if prev and re.search(r"[А-Яа-яЁё]$", prev):
            return tail_at + last.start()
    # «РС вирус — респираторно-синцитиальный»: the code is the capital pair plus the word.
    if len(tokens) >= 2 and not _is_strong(last.group()):
        prev = tokens[-2]
        gap = tail[prev.end():last.start()]
        word = last.group()
        if (
            _is_strong(prev.group())
            and not gap.strip()
            and word.isalpha()
            and word.islower()
            and len(word) <= 12
        ):
            return tail_at + prev.start()
    # «ВОЗ» must not swallow the tail of the previous definition, «(ый)».
    # «ЛТ 5х5 Гр» and «ПЭТ-КТ с FAPI» keep the codes that stand in front of the last one.
    if _is_strong(last.group()):
        group = [last]
        for prev in reversed(tokens[:-1]):
            if len(group) >= 4:
                break
            gap = tail[prev.end():group[0].start()]
            if any(ch in gap for ch in "(),;[]"):
                break
            word = prev.group()
            # «Гр» before «ЛФК» closes the previous dose. «ЛТ 5х5 Гр» keeps «Гр» as its last token.
            if _dose_unit(word):
                break
            # «хромогранин А» is not the next code. «ПЭТ-КТ с FAPI» still keeps «с».
            if len(word) == 1 and word.isalpha() and word.lower() not in {"с", "и", "в"}:
                break
            # «ангиотензина II» stays with the definition. «АСТ» is the next code.
            if re.fullmatch(r"[IVX]{1,4}", word) and re.search(r"[А-ЯA-Z]", group[0].group()):
                break
            if word.lower() in {"с", "и", "по", "на", "от", "для", "в"} or _is_strong(word):
                # «США IgE»: the country name closes the previous definition.
                if re.fullmatch(r"[А-ЯЁ]{2,}", word) and re.match(r"[A-Za-z]", group[0].group()):
                    break
                group.insert(0, prev)
                continue
            break
        # «Мутация BRAFV600E»: the name is the title-case word in front of the code.
        earlier = next((token for token in tokens if token.start() == group[0].start()), None)
        if earlier is not None:
            index = tokens.index(earlier)
            if index:
                named = tokens[index - 1]
                gap = tail[named.end():earlier.start()]
                code = tail[group[0].start():group[-1].end()]
                if (
                    not gap.strip()
                    and any(ch.isdigit() for ch in code)
                    and re.fullmatch(r"[А-ЯЁ][а-яё]{2,24}", named.group())
                ):
                    return tail_at + named.start()
        return tail_at + group[0].start()
    # «КФК общ.»: the capital code keeps the short lowercase qualifier in front of the dash.
    if len(tokens) >= 2:
        prev = tokens[-2]
        gap = tail[prev.end():last.start()]
        word = last.group().rstrip(".")
        if (
            _is_strong(prev.group())
            and gap.strip() in {"", "."}
            and word.isalpha()
            and word.islower()
            and len(word) <= 6
            and text[: tail_at + prev.start()].strip()
        ):
            return tail_at + prev.start()
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
        # «Impact on Asthma — перевод»: on/and/the are not the next code.
        if re.match(r"(?:on|and|its|the|of|for|to|in|at|by|or|an)\b", text[at:]):
            continue
        starts.append(at)
    # «TNM (аббревиатура …) — определение»: the code stands before the parenthesis, not before the dash.
    for match in re.finditer(r"(?<=\)\s)([A-ZА-ЯЁ][A-ZА-ЯЁ0-9/+–\-]{1,16})(?=\s+\()", text):
        starts.append(match.start(1))
    starts = sorted(set(starts))
    if not starts:
        return [text.strip()] if text.strip() else []
    # One code that begins the line is the whole entry. A code after leftover words is the next entry.
    if len(starts) == 1 and not text[: starts[0]].strip():
        return [text.strip()]
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


def _cut_sentence(prev_row: list[str], row: list[str]) -> bool:
    """One lowercase fragment is the rest of the cell cut by the page edge."""
    filled = [(index, cell.strip()) for index, cell in enumerate(row) if cell.strip() and not set(cell.strip()) <= set("-")]
    if len(filled) != 1:
        return False
    index, text = filled[0]
    if not text[:1].islower() or index >= len(prev_row):
        return False
    above = prev_row[index].strip()
    return len(above) > 40 and above[-1] not in ".!?;:"


def _repeated_banner(row: list[str], prev: list[list[str]]) -> bool:
    """The column titles printed again under the page edge («Орган | Балл 0 | …»)."""
    norm = [cell.strip().lower() for cell in row]
    filled = [cell for cell in norm if cell]
    if len(filled) < 3 or any(len(cell) > 20 for cell in filled):
        return False
    return any([cell.strip().lower() for cell in old] == norm for old in prev[2:])


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


def _icd_continuation(prev: list[list[str]], grid: list[list[str]]) -> bool:
    """A histology grid continued on the next page has no second header.

    The next part opens on a morphology code. A different scale, with its own
    caption between the parts, never reaches this check.
    """
    if len(prev[0]) != len(grid[0]) or len(prev[0]) < 2:
        return False
    code = re.compile(r"\d{4}/\d")
    if sum(1 for row in prev[2:] if code.search(row[0])) >= 4 and code.search(grid[0][0]):
        return True
    # «Хондросаркома | 9220/3»: the morphology code is the last column, not the name.
    last = len(prev[0]) - 1
    if sum(1 for row in prev[2:] if last < len(row) and code.search(row[last])) < 4:
        return False
    return last < len(grid[0]) and code.search(grid[0][last]) is not None


def _label_index(cell: str) -> tuple[str, int] | None:
    match = re.fullmatch(r"(.+?)\s*(\d+)\s*$", cell.strip())
    if not match or len(match.group(1).strip()) < 2:
        return None
    return match.group(1).strip().lower(), int(match.group(2))


def _series_continuation(prev: list[list[str]], grid: list[list[str]]) -> bool:
    """EU-TIRADS 2 on the next page is the next row, not a new header."""
    if len(prev[0]) != len(grid[0]):
        return False
    nxt = _label_index(grid[0][0])
    if nxt is None:
        return False
    last = None
    for row in reversed(prev[2:]):
        last = _label_index(row[0])
        if last is not None:
            break
    return last is not None and last[0] == nxt[0] and nxt[1] == last[1] + 1


def _note_tail(prev: list[list[str]], grid: list[list[str]]) -> bool:
    """The page break left the tail of the last note in the last column."""
    if len(prev[0]) != len(grid[0]) or len(grid[0]) < 2:
        return False
    filled = [index for index, cell in enumerate(grid[0]) if cell.strip()]
    if filled != [len(grid[0]) - 1]:
        return False
    tail = grid[0][-1].strip()
    last = prev[-1][-1].strip()
    # A one-word drug in the last column is the next regimen row, not a cut note.
    if " " not in last or len(last) < 24:
        return False
    if not tail[:1].islower() or last[-1] in ".!?;:":
        return False
    return True


def _continue_same_scale(
    out: list[str], grid: list[list[str]]
) -> tuple[int, list[list[str]]] | None:
    """The next part of one scale, with only a numbered footnote between the headers.

    A caption «Таблица N» stops the join, so two different scales stay apart.
    """
    if not out:
        return None
    last = out[-1].strip()
    # Adjacent parts and picture breaks already have their own join.
    if last.startswith("|") or last.startswith("!["):
        return None
    earlier = None
    for index in range(len(out) - 1, -1, -1):
        if _parse_grid(out[index]):
            earlier = index
            break
        if _image_block(out[index]):
            continue
        text = out[index].strip()
        if re.match(r"\d", text) and "Таблица" not in text[:80] and "таблица" not in text[:80]:
            continue
        # The cut header fell out of the table as its own short line («кри- Степень»).
        if (
            len(text) < 120
            and not text.endswith(".")
            and re.search(r"[А-Яа-яA-Za-z]{3}-", text)
            and "Таблица" not in text
            and "таблица" not in text
        ):
            continue
        return None
    if earlier is None:
        return None
    prev = _parse_grid(out[earlier])
    if prev is None:
        return None
    last = out[-1]
    if not last.lstrip().startswith("|"):
        repaired = _repair_split_header(prev, last, grid)
        if repaired is not None:
            prose, grid = repaired
            if prose:
                out[-1] = prose
            else:
                out.pop()
    if [cell.lower() for cell in prev[0]] != [cell.lower() for cell in grid[0]]:
        return None
    return earlier, grid


def _repair_split_header(
    prev: list[list[str]] | None, prose: str, grid: list[list[str]]
) -> tuple[str, list[list[str]]] | None:
    """A page break cut the header: «кри-» stayed on the footnote, «терий ЭоЭ» opened the next grid."""
    if prev is None or not grid or not grid[0]:
        return None
    lead = grid[0][0].strip()
    head = prev[0][0].strip()
    if not lead or not head or not lead[0].islower() or "-" not in head:
        return None
    if not head.replace("-", "").endswith(lead):
        return None
    marker = head.split("-")[0].rstrip()
    if len(marker) < 8 or marker not in prose[-160:]:
        return None
    trimmed = prose[: prose.rfind(marker)].rstrip()
    repaired = [list(prev[0]), *grid[1:]]
    return trimmed, repaired


def _stacked_header(prev: list[list[str]]) -> bool:
    """Column titles wrapped onto the next ruled lines, with no data yet.

    «Количество / тромбоцитов в / периферической крови» is one header, and the
    cells that the first line left empty are filled underneath.
    """
    rows = [row for row in prev if not _separator_row(row)]
    if not 2 <= len(rows) <= 4 or len(rows[0]) < 2:
        return False
    if any(len(cell.strip()) > 24 or any(ch.isdigit() for ch in cell) for row in rows for cell in row):
        return False
    return any(
        not rows[0][index].strip() and any(row[index].strip() for row in rows[1:])
        for index in range(len(rows[0]))
    )


def _fold_header_stack(prev: list[list[str]]) -> list[list[str]]:
    rows = [row for row in prev if not _separator_row(row)]
    width = len(rows[0])
    folded = []
    for index in range(width):
        parts = [row[index].strip() for row in rows if row[index].strip()]
        folded.append(" ".join(parts))
    return [folded, ["---"] * width]


def _headerless_rows(prev: list[list[str]], grid: list[list[str]]) -> bool:
    """The next page kept the rules and dropped the column titles, so a data row became the header."""
    if len(prev[0]) != len(grid[0]) or len(grid[0]) < 2:
        return False
    if _short_banner(grid[0]) or grid[0][0].strip().lower().startswith("таблица"):
        return False
    if not any(len(cell.strip()) > 40 for cell in grid[0]):
        return False
    if _stacked_header(prev):
        return True
    if len(prev) < 4:
        return False
    titles = [cell.strip() for cell in prev[0] if cell.strip()]
    if len(titles) < 2 or any(len(cell) > 24 for cell in titles):
        return False
    # Two columns: a short row label plus a long cell is data («Стоматит | мазки…»).
    if len(grid[0]) == 2:
        lead = grid[0][0].strip()
        return bool(lead) and len(lead) <= 24 and lead.lower() not in {cell.lower() for cell in titles}
    return len(grid[0]) >= 3


def _wrapped_lead(prev: list[list[str]], grid: list[list[str]]) -> bool:
    """The page break cut one cell. The next grid opens on the rest of that cell.

    The tail starts with a lowercase letter and the other cells of that row are
    empty, so it is not a new header.
    """
    if len(prev[0]) != len(grid[0]) or len(grid[0]) < 3:
        return False
    head = grid[0]
    if not head[0].strip() or any(cell.strip() for cell in head[1:]):
        return False
    if not head[0][:1].islower():
        return False
    last = prev[-1]
    if not last[0].strip() or last[0].rstrip().endswith((".", "!", "?", ";", ":")):
        return False
    return any(cell.strip() for cell in last[1:])


_GRADES = {"A": 1, "B": 2, "C": 3, "D": 4, "А": 1, "В": 2, "С": 3, "Д": 4}


_T_ORDER = [
    "tx", "t0", "tis", "t1", "t1a", "t1b", "t2", "t2a", "t2b",
    "t3", "t3a", "t3b", "t4", "t4a", "t4b",
]


def _t_code(cell: str) -> str | None:
    token = cell.strip().split(":")[0].split()
    if not token:
        return None
    code = token[0].lower().replace("т", "t")
    return code if code in _T_ORDER else None


def _regimen_continuation(prev: list[list[str]], grid: list[list[str]]) -> bool:
    """A chemotherapy row on the next page is data, not a new header."""
    if len(prev[0]) != len(grid[0]) or len(grid[0]) < 4:
        return False
    dose = re.compile(r"мг/|мкг/")
    if not dose.search(" ".join(grid[0])):
        return False
    return any(dose.search(" ".join(row)) for row in prev[2:])


def _formulary_continuation(prev: list[list[str]], grid: list[list[str]]) -> bool:
    """A drug row on the next page is data, so the separator must not sit under it."""
    if len(prev[0]) != len(grid[0]) or len(grid[0]) < 3:
        return False
    if "**" not in grid[0][0]:
        return False
    return any("**" in row[0] for row in prev[2:])


def _service_continuation(prev: list[list[str]], grid: list[list[str]]) -> bool:
    """A nomenclature row on the next page continues the service table."""
    if len(prev[0]) != len(grid[0]):
        return False
    code = re.compile(r"[AА]\d{2}\.\d{2}\.\d{3}")
    if not code.search(" ".join(grid[0])):
        return False
    return sum(1 for row in prev[2:] if code.search(" ".join(row))) >= 2


_N_ORDER = ["nx", "n0", "n1", "n2", "n2a", "n2b", "n2c", "n3", "n3a", "n3b"]


def _n_code(cell: str) -> str | None:
    token = cell.strip().split(":")[0].split()
    if not token:
        return None
    code = token[0].lower().replace("н", "n")
    return code if code in _N_ORDER else None


def _n_continuation(prev: list[list[str]], grid: list[list[str]]) -> bool:
    """N2c on the next page continues the N table. It is not a new header."""
    if len(prev[0]) != len(grid[0]):
        return False
    nxt = _n_code(grid[0][0])
    if nxt is None:
        return False
    last = None
    for row in reversed(prev[2:]):
        last = _n_code(row[0])
        if last is not None:
            break
    return last is not None and _N_ORDER.index(nxt) == _N_ORDER.index(last) + 1


def letter_tail(prev: list[list[str]], text: str) -> list[list[str]] | None:
    """Grade C of a scale sits under the page edge, outside the grid."""
    if len(prev[0]) != 2:
        return None
    last = None
    for row in reversed(prev[2:]):
        last = _GRADES.get(row[0].strip())
        if last is not None:
            break
    match = re.fullmatch(r"([A-DАВСД])\s+(\S.{15,})", re.sub(r"\s+", " ", text).strip())
    if match is None or last is None or _GRADES.get(match.group(1)) != last + 1:
        return None
    return [[match.group(1), match.group(2).strip()]]


def numbered_tail(prev: list[list[str]], text: str) -> list[list[str]] | None:
    """Rows 4 and 5 of a scale sit under the page edge, outside the grid."""
    if len(prev[0]) != 2:
        return None
    last = None
    for row in reversed(prev[2:]):
        token = row[0].strip()
        if token.isdigit():
            last = int(token)
            break
    if last is None:
        return None
    parts = re.split(r"(?<=\s)(?=\d{1,2}\s)", text.strip())
    rows = []
    expect = last + 1
    for part in parts:
        match = re.fullmatch(r"(\d{1,2})\s+(.+)", part.strip())
        if match is None or int(match.group(1)) != expect:
            return None
        rows.append([match.group(1), re.sub(r"\s+", " ", match.group(2)).strip()])
        expect += 1
    return rows or None


def split_stacked_lines(raw_row: list[str]) -> list[list[str]] | None:
    """Two stage rows drawn in one ruled band: «III / T1, T2 + T3».

    A wrapped description is one cell with many lines. That stays one row.
    """
    parts = [(cell or "").split("\n") for cell in raw_row]
    multi = [len(part) for part in parts if len(part) > 1]
    if len(multi) < 2 or len(set(multi)) != 1 or multi[0] != 2:
        return None
    if len(parts[0]) != 1:
        return None
    rows = []
    for index in range(2):
        cells = []
        for part in parts:
            if len(part) == 2:
                cells.append(clean_text(part[index]))
            elif index == 0:
                cells.append(clean_text(" ".join(part)))
            else:
                cells.append("")
        rows.append(cells)
    return rows


def _t_continuation(prev: list[list[str]], grid: list[list[str]]) -> bool:
    """T2b on the next page continues the T table. It is not a new header."""
    if len(prev[0]) != len(grid[0]):
        return False
    nxt = _t_code(grid[0][0])
    if nxt is None:
        return False
    last = None
    for row in reversed(prev[2:]):
        last = _t_code(row[0])
        if last is not None:
            break
    return last is not None and _T_ORDER.index(nxt) == _T_ORDER.index(last) + 1


def _letter_continuation(prev: list[list[str]], grid: list[list[str]]) -> bool:
    """Row B of a grade scale is the next row, not a new header."""
    if len(prev[0]) != len(grid[0]):
        return False
    nxt = _GRADES.get(grid[0][0].strip())
    if nxt is None:
        return False
    last = None
    for row in reversed(prev[2:]):
        last = _GRADES.get(row[0].strip())
        if last is not None:
            break
    return last is not None and nxt == last + 1


def _with_blank_column(prev: list[list[str]], grid: list[list[str]]) -> list[list[str]] | None:
    """The next page dropped a column that was empty in every body row."""
    if len(prev[0]) != len(grid[0]) + 1 or not prev[2:]:
        return None
    blanks = [
        index
        for index in range(len(prev[0]))
        if all(not row[index].strip() for row in prev[2:])
    ]
    if len(blanks) != 1:
        return None
    padded = []
    for row in grid:
        cells = list(row)
        cells.insert(blanks[0], "")
        padded.append(cells)
    if not _continued_numbers(prev, padded):
        return None
    return padded


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


def _short_banner(row: list[str]) -> bool:
    filled = [cell.strip() for cell in row if cell.strip()]
    return len(row) >= 4 and len(filled) >= 3 and all(len(cell) <= 20 for cell in filled)


def _same_cells(left: list[str], right: list[str]) -> bool:
    if len(left) != len(right):
        return False
    return [cell.strip().lower() for cell in left] == [cell.strip().lower() for cell in right]


def _join_piece(left: str, right: str) -> str:
    """A short lowercase stub continues the word; a real word stays separate."""
    left, right = left.strip(), right.strip()
    if not right:
        return left
    if not left:
        return right
    core = right.rstrip(".,;:)")
    if (
        core.isalpha()
        and core.islower()
        and 1 < len(core) <= 4
        and left[-1].isalpha()
        and len(left) >= 8
        and not any(left.endswith(end) for end in _WORD_END)
        and core not in {"или", "для", "при", "под", "без", "над", "про", "как", "что", "нет", "либо", "да"}
    ):
        return left + core + right[len(core):]
    return _glue_cell(left, right)


def _fold_wrap_tail(last: list[str], body: list[list[str]]) -> list[list[str]]:
    """Lines with an empty first cell are the rest of the row the page cut."""
    while body and not body[0][0].strip() and any(cell[:1].islower() for cell in body[0][1:] if cell.strip()):
        width = max(len(last), len(body[0]))
        last.extend([""] * (width - len(last)))
        row = body[0] + [""] * (width - len(body[0]))
        for index, cell in enumerate(row):
            last[index] = _join_piece(last[index], cell)
        body = body[1:]
    return body


def _banner_owner(out: list[str], grid: list[list[str]]) -> tuple[int, list[int]] | None:
    """«Орган | Балл 0 | …» printed again after the same caption and the page picture."""
    if not grid or not _short_banner(grid[0]):
        return None
    captions: list[int] = []
    for index in range(len(out) - 1, -1, -1):
        prev = _parse_grid(out[index])
        if prev is not None:
            if len(prev[0]) != len(grid[0]) or not any(_same_cells(row, grid[0]) for row in prev[2:]):
                return None
            head = re.sub(r"\s+", " ", prev[0][0]).strip().lower()
            for cap in captions:
                text = re.sub(r"\s+", " ", out[cap]).strip().lower()
                if not (head.startswith(text[:24]) or text.startswith(head[:24])):
                    return None
            return index, captions
        if _image_block(out[index]):
            continue
        text = out[index].strip()
        if text.lower().startswith("таблица") and "\n" not in text and len(text) < 400:
            captions.append(index)
            continue
        return None
    return None


def _score_tail(out: list[str], tail: str) -> bool:
    """«Гематокрит + 10» on one page, «PaO … + 10» under the edge of the next."""
    prev_at = _previous_grid(out)
    if prev_at is None:
        return False
    prev = _parse_grid(out[prev_at])
    if prev is None or len(prev[0]) != 2 or len(prev) < 5:
        return False
    hits = sum(1 for row in prev[2:] if re.match(r"[+±−–-]?\s*\d", row[1].strip()))
    if hits < 3:
        return False
    folded = re.sub(r"\s+", " ", tail).strip()
    header = " ".join(cell.strip() for cell in prev[0] if cell.strip())
    if folded.lower() == header.lower():
        return True
    scored = re.fullmatch(r"(.+?)\s+(?:\d{1,2}\s+)*([+±−–-]\s*\d{1,3})", folded)
    if scored and scored.group(1)[:1].isalpha() and not scored.group(1).lower().startswith("таблица"):
        prev.append([scored.group(1).strip(), scored.group(2)])
        out[prev_at] = _render_grid(prev)
        return True
    if re.fullmatch(r"[+±−–-]\s*\d{1,3}", folded) and not prev[-1][1].strip():
        prev[-1][1] = folded
        out[prev_at] = _render_grid(prev)
        return True
    if (
        len(folded) <= 90
        and folded[:1].isalpha()
        and not folded.lower().startswith("таблица")
        and folded[-1] not in ".:;"
        and prev[-1][1].strip()
    ):
        prev.append([folded, ""])
        out[prev_at] = _render_grid(prev)
        return True
    return False


def merge_split_tables(md: str) -> str:
    """A table continued on the next page repeats its header. Keep the header once.

    The row that was cut by the page edge comes back with an empty first cell.
    Its text belongs to the last row of the previous part. A numbered table that
    does not repeat the header is one grid, not a new table starting at the next row.
    A histology grid continued on the next page opens on a morphology code, not a
    second header. A picture of the table may sit between the two parts.
    """
    blocks = md.split("\n\n")
    out: list[str] = []
    for block in blocks:
        grid = _parse_grid(block)
        # «3» on the previous page, «4 … 5 …» under the page edge, still the same scale.
        tail = block.strip()
        if grid is None and tail and _score_tail(out, tail):
            continue
        if grid is None and tail and tail[0] in _GRADES:
            prev_at = _previous_grid(out)
            prev = _parse_grid(out[prev_at]) if prev_at is not None else None
            extra = letter_tail(prev, tail) if prev is not None else None
            if extra:
                prev.extend(extra)
                out[prev_at] = _render_grid(prev)
                continue
        if grid is None and tail and tail[0].isdigit():
            prev_at = _previous_grid(out)
            prev = _parse_grid(out[prev_at]) if prev_at is not None else None
            extra = numbered_tail(prev, tail) if prev is not None else None
            if extra:
                prev.extend(extra)
                out[prev_at] = _render_grid(prev)
                continue
        # «крыловидные» / «отростки…» is the same cell, cut by the page edge.
        if (
            grid is None
            and tail
            and tail[0].islower()
            and tail[0] not in "#|!-"
            and len(tail) < 320
            and ";" not in tail
            and ". " not in tail
            and not tail.startswith(("http", "www"))
        ):
            prev_at = _previous_grid(out)
            prev = _parse_grid(out[prev_at]) if prev_at is not None else None
            if prev is not None:
                last = prev[-1]
                target = next(
                    (
                        index
                        for index in range(len(last) - 1, -1, -1)
                        if last[index].strip() and last[index].rstrip()[-1] not in ".!?;:"
                    ),
                    None,
                )
                if target is not None:
                    last[target] = _glue_cell(last[target], tail)
                    out[prev_at] = _render_grid(prev)
                    continue
        continued_scale = _continue_same_scale(out, grid) if grid is not None else None
        if continued_scale is not None:
            earlier, grid = continued_scale
            prev = _parse_grid(out[earlier])
            prev.extend(grid[2:])
            out[earlier] = _render_grid(prev)
            continue
        owned = _banner_owner(out, grid) if grid is not None else None
        if owned is not None:
            prev_at, captions = owned
            prev = _parse_grid(out[prev_at])
            body = _fold_wrap_tail(prev[-1], grid[2:])
            body = [row for row in body if not _repeated_banner(row, prev)]
            prev.extend(body)
            out[prev_at] = _render_grid(prev)
            for index in sorted(captions, reverse=True):
                del out[index]
            continue
        prev_at = _previous_grid(out) if grid is not None else None
        if grid is None or prev_at is None:
            out.append(block)
            continue
        prev = _parse_grid(out[prev_at])
        same_header = [cell.lower() for cell in prev[0]] == [cell.lower() for cell in grid[0]]
        blank_lead = len(prev[0]) == len(grid[0]) and not grid[0][0].strip()
        continued = (
            _continued_numbers(prev, grid)
            or _series_continuation(prev, grid)
            or _icd_continuation(prev, grid)
            or _letter_continuation(prev, grid)
            or _t_continuation(prev, grid)
            or _n_continuation(prev, grid)
            or _regimen_continuation(prev, grid)
            or _formulary_continuation(prev, grid)
            or _service_continuation(prev, grid)
            or _note_tail(prev, grid)
        )
        if not same_header and not continued:
            padded = _with_blank_column(prev, grid)
            if padded is not None:
                grid = padded
                continued = True
        # One ruled row cut onto the next page is emitted as a header with no body.
        lead = grid[0][0].strip()
        if len(grid) == 2 and len(prev[0]) == len(grid[0]) and not same_header and len(lead) > 40 and " " in lead:
            prev.append(grid[0])
            out[prev_at] = _render_grid(prev)
            continue
        number = re.fullmatch(r"(\d{1,2})\.?", lead)
        if number and len(grid) == 2 and len(prev[0]) == len(grid[0]) and not same_header:
            last_n = next(
                (
                    int(row[0].strip().rstrip("."))
                    for row in reversed(prev[2:])
                    if row[0].strip().rstrip(".").isdigit()
                ),
                None,
            )
            if last_n is not None and int(number.group(1)) == last_n + 1:
                prev.append(grid[0])
                out[prev_at] = _render_grid(prev)
                continue
        # A full-width section band («Обследование для выявления…») is a row of the same grid.
        section = (
            len(prev[0]) == len(grid[0])
            and len(grid[0]) >= 4
            and bool(grid[0][0].strip())
            and not any(cell.strip() for cell in grid[0][1:])
            and len(grid[0][0].strip()) > 20
        )
        wrapped = _wrapped_lead(prev, grid)
        headerless = _headerless_rows(prev, grid)
        if not same_header and not continued and not blank_lead and not wrapped and not section and not headerless:
            out.append(block)
            continue
        if section and not same_header:
            body = [grid[0], *grid[2:]]
        elif wrapped:
            prev[-1][0] = _glue_cell(prev[-1][0], grid[0][0])
            body = grid[2:]
        elif _note_tail(prev, grid):
            prev[-1][-1] = _glue_cell(prev[-1][-1], grid[0][-1])
            body = grid[2:]
            while body and _cut_sentence(prev[-1], body[0]):
                prev[-1] = [
                    _glue_cell(left, right) if right.strip() else left
                    for left, right in zip(prev[-1], body[0])
                ]
                body = body[1:]
        elif same_header:
            body = grid[2:]
            if body and _header_fragment(body[0]):
                prev[0] = [
                    _glue_cell(left, right) if right.strip() else left
                    for left, right in zip(prev[0], body[0])
                ]
                body = body[1:]
            # An empty stage cell is the next row of a span («4b | Любое N»).
            # Several lowercase lines are one cell cut by the page edge.
            while body and _cut_sentence(prev[-1], body[0]):
                prev[-1] = [
                    _glue_cell(left, right) if right.strip() else left
                    for left, right in zip(prev[-1], body[0])
                ]
                body = body[1:]
            if body and not body[0][0].strip() and any(cell[:1].islower() for cell in body[0][1:] if cell.strip()):
                prev[-1] = [_glue_cell(left, right) for left, right in zip(prev[-1], body[0])]
                body = body[1:]
        elif headerless:
            if _stacked_header(prev):
                prev = _fold_header_stack(prev)
            body = [grid[0], *grid[2:]]
        elif blank_lead:
            # Empty first cell is the next drug row of a spanned regimen, not a cut sentence.
            body = [grid[0], *grid[2:]]
            while body and _cut_sentence(prev[-1], body[0]):
                prev[-1] = [
                    _glue_cell(left, right) if right.strip() else left
                    for left, right in zip(prev[-1], body[0])
                ]
                body = body[1:]
        else:
            body = [grid[0], *grid[2:]]
        body = [row for row in body if not _repeated_banner(row, prev)]
        prev.extend(body)
        prev = _fold_dose_tail(prev)
        out[prev_at] = _render_grid(prev)
    text = "\n\n".join(out)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return text + "\n"


def _caption_row(row: list[str]) -> bool:
    """A title sitting in the grid between two numbered scales («Критерии оценки…»)."""
    if row[0].strip():
        return False
    text = " ".join(cell.strip() for cell in row[1:] if cell.strip())
    return len(text) > 40 and text[:1].isupper()


def split_restarted_tables(md: str) -> str:
    """A second numbered table glued into the first one restarts at 1 after its caption."""
    blocks = md.split("\n\n")
    out: list[str] = []
    for block in blocks:
        grid = _parse_grid(block)
        if grid is None or len(grid) < 6:
            out.append(block)
            continue
        body = grid[2:]
        cuts: list[int] = []
        last_n = None
        for index, row in enumerate(body):
            lead = row[0].strip().rstrip(".")
            if not lead.isdigit():
                continue
            number = int(lead)
            if (
                last_n is not None
                and number == 1
                and last_n > 1
                and index > 0
                and _caption_row(body[index - 1])
            ):
                cuts.append(index - 1)
            last_n = number
        if not cuts:
            out.append(block)
            continue
        header = [grid[0], grid[1]]
        start = 0
        for cut in cuts:
            if cut > start:
                out.append(_render_grid(header + body[start:cut]))
            end = cut
            titles: list[str] = []
            while end < len(body) and _caption_row(body[end]):
                titles.append(" ".join(cell.strip() for cell in body[end] if cell.strip()))
                end += 1
            if titles:
                out.append(" ".join(titles))
            start = end
        if start < len(body):
            out.append(_render_grid(header + body[start:]))
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
        raw = line.strip()
        if raw.startswith("- "):
            raw = raw[2:].strip()
        if in_abbr and raw and not raw.startswith(("|", "!", "```", "-")):
            parts = abbreviation_entries(raw)
            emitted = []
            for part in parts:
                # «клинический» / «объем мишени» is the same definition, cut onto the next line.
                first = part.split()[0] if part.split() else ""
                if re.fullmatch(r"[а-яё]{4,}", first) and not _is_strong(first):
                    target = emitted if emitted else out
                    prev_at = next((i for i in range(len(target) - 1, -1, -1) if target[i].strip()), None)
                    if prev_at is not None and not target[prev_at].startswith("#"):
                        target[prev_at] = f"{target[prev_at]} {part}"
                        continue
                # The tail of the previous definition («Эпштейна-» / «Барр») is not a new code.
                if re.fullmatch(r"[А-ЯЁA-Z]{1,5}", part) or re.fullmatch(
                    r"[А-ЯЁ][а-яё]+(?:(?:\s+|-)[А-ЯЁ][а-яё]+){0,2}", part
                ):
                    target = emitted if emitted else out
                    prev_at = next((i for i in range(len(target) - 1, -1, -1) if target[i].strip()), None)
                    if prev_at is not None and not target[prev_at].startswith("#"):
                        prev = target[prev_at]
                        if prev.endswith(("−", "-", "–", "—")):
                            target[prev_at] = prev[:-1] + "-" + part
                        else:
                            target[prev_at] = f"{prev} {part}"
                        continue
                emitted.append(part)
            if len(emitted) > 1 or (emitted and emitted[0] != line.strip()):
                for part in emitted:
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
