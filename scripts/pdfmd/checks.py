"""Quality checks for a converted document.

Errors are things that make the file unsafe to use: broken tables, missing
pictures, untranslated symbol-font bytes, or a large share of source words
that never reached the Markdown.
"""

from __future__ import annotations

import re
from pathlib import Path

TOKEN = re.compile(r"[0-9A-Za-zА-Яа-яЁёμ]+")
CYR = set("абвгдеёжзийклмнопрстуфхцчшщъыьэюя")


def _tokens(text: str) -> list[str]:
    return [token.lower().replace("ё", "е") for token in TOKEN.findall(text)]


def _tables(md: str) -> list[list[str]]:
    groups: list[list[str]] = []
    current: list[str] = []
    for line in md.splitlines():
        if line.startswith("|"):
            current.append(line)
        elif current:
            groups.append(current)
            current = []
    if current:
        groups.append(current)
    return groups


def _mermaid_errors(md: str) -> list[str]:
    errors = []
    for match in re.finditer(r"```mermaid\n(.*?)```", md, re.S):
        body = match.group(1)
        nodes = set(re.findall(r"^\s*(n\d+)", body, re.M))
        if len(nodes) < 2:
            errors.append("схема mermaid без блоков")
        for src, dst in re.findall(r"(n\d+)\s+-->\s*(?:\|[^|]*\|\s*)?(n\d+)", body):
            if src not in nodes or dst not in nodes:
                errors.append(f"стрелка схемы {src} → {dst} ведёт в отсутствующий блок")
    return errors


def structural(md: str, assets: Path) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    if not md.strip():
        return ["пустой документ"], warnings
    if md.count("```") % 2:
        errors.append("незакрытый блок кода")
    if re.search(r"[\ue000-\uf8ff]", md):
        errors.append("в тексте остались символы служебного шрифта")
    for group in _tables(md):
        counts = [line.count("|") for line in group]
        if len(set(counts)) != 1:
            errors.append("в таблице разное число столбцов")
            break
        if not any(set(line.replace("|", "").replace("-", "").replace(" ", "").replace(":", "")) == set() and "---" in line for line in group):
            errors.append("у таблицы нет строки разделителя")
            break
    for match in re.finditer(r"!\[[^\]]*\]\(([^)]+)\)", md):
        name = Path(match.group(1)).name
        if not (assets / name).exists():
            errors.append(f"нет файла рисунка {name}")
    errors.extend(_mermaid_errors(md))
    letters = [ch for ch in md if ch.isalpha()]
    if letters and sum(ch.lower() in CYR for ch in letters) / len(letters) < 0.4:
        warnings.append("мало кириллицы: возможно, перепутан язык распознавания")
    if md.count("\n#") + (1 if md.startswith("#") else 0) < 3:
        warnings.append("мало заголовков")
    return errors, warnings


def recall(md: str, pdf: Path, pages: list[dict]) -> tuple[float, str | None]:
    """Share of text-layer words from kept pages that appear in the Markdown."""
    import pymupdf

    from symbols import map_symbol

    skipped = {page["page"] for page in pages if page.get("skip") or page.get("needs_ocr")}
    present = set(_tokens(md))
    total = hit = 0
    doc = pymupdf.open(pdf)
    for index, page in enumerate(doc):
        if index + 1 in skipped:
            continue
        height = page.rect.height
        for word in page.get_text("words"):
            if word[1] < height * 0.05 or word[3] > height * 0.955:
                continue
            for token in TOKEN.findall(map_symbol(word[4]).lower().replace("ё", "е")):
                if len(token) < 4:
                    continue
                total += 1
                if token in present:
                    hit += 1
    doc.close()
    if total < 40:
        return 1.0, None
    score = hit / total
    if score < 0.9:
        return score, f"в Markdown попало {score:.0%} слов текстового слоя ({hit} из {total})"
    return score, None
