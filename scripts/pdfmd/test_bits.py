"""Checks that do not need a PDF: symbols, hyphenation, headings, tables, schemes."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from layout import (
    abbreviation_entries,
    cell_text,
    heading_level,
    is_toc,
    markdown_table,
    merge_split_tables,
    mermaid,
    split_abbreviation_section,
)
from symbols import map_symbol


def test_symbol() -> None:
    assert map_symbol("\uf061/\uf061\uf061") == "α/αα"
    assert map_symbol("\uf062") == "β"
    assert map_symbol("\uf0a3") == "≤"
    assert map_symbol("\uf0a7") == "▪"
    assert map_symbol("\uf0ae") == "→"
    assert map_symbol("\uf0fc") == "✓"
    assert "\uf061" not in map_symbol("ген \uf061")


def test_hyphenation() -> None:
    words = [
        {"x0": 369.9, "y0": 83, "x1": 415, "y1": 94, "text": "необходи"},
        {"x0": 377.6, "y0": 95.5, "x1": 407.5, "y1": 106, "text": "мости"},
    ]
    assert cell_text(words) == "необходимости"
    column = [
        {"x0": 172.6, "y0": 121, "x1": 205, "y1": 132, "text": "оценка"},
        {"x0": 172.6, "y0": 134, "x1": 235, "y1": 145, "text": "соотношения"},
        {"x0": 172.6, "y0": 146, "x1": 200, "y1": 157, "text": "типов"},
    ]
    assert cell_text(column) == "оценка соотношения типов"
    split = [
        {"x0": 90.8, "y0": 451, "x1": 157.6, "y1": 464, "text": "Гемотрансфуз"},
        {"x0": 90.8, "y0": 464, "x1": 102.7, "y1": 476, "text": "ии"},
    ]
    assert cell_text(split) == "Гемотрансфузии"
    separate = [
        {"x0": 259.9, "y0": 449, "x1": 327.0, "y1": 461, "text": "внутривенный"},
        {"x0": 276.9, "y0": 462, "x1": 309.2, "y1": 473, "text": "доступ"},
    ]
    assert cell_text(separate) == "внутривенный доступ"


def test_headings() -> None:
    assert heading_level("1.1 Определение заболевания или состояния", False) == 3
    assert heading_level("1. Краткая информация по заболеванию", False) == 2
    assert heading_level("3. Hb Lepore и δβ-талассемия", True) == 2
    assert heading_level("3. Приказ Минздрава России от 13.10.2017", False) is None
    assert heading_level("1. Ильина Наталья Ивановна - вице-президент", False) is None
    assert heading_level("Список литературы", False) == 2
    assert heading_level("Приложение Б. Алгоритмы действий врача", False) == 2


def test_toc() -> None:
    assert is_toc(["Оглавление", "Список сокращений ........ 4"])
    assert is_toc([
        "Приложение А1. Состав рабочей группы",
        "Приложение А2. Методология",
        "Приложение А3. Справочные материалы",
        "Приложение Б. Алгоритмы действий врача",
    ])
    assert not is_toc([
        "Приложение А2. Методология разработки клинических рекомендаций",
        "1. Врачи-оториноларингологи.",
        "2. Врачи-терапевты.",
        "3. Врачи-педиатры.",
        "4. Врачи-неврологи",
        "5. Врачи общей практики.",
        "6. Врачи-инфекционисты.",
        "7. Врачи-нейрохирурги",
        "8. Студенты медицинских ВУЗов.",
        "Таблица 1. Шкала оценки уровней достоверности доказательств",
    ])
    assert not is_toc(["Рекомендуется ввести эпинефрин всем пациентам с анафилаксией."])


def test_table() -> None:
    grid = markdown_table(
        [
            ["№", "Критерий", "", "Да"],
            ["1", "Введён эпинефрин", "", "Да"],
        ]
    )
    assert "\n| --- | --- | --- |" in grid
    counts = [line.count("|") for line in grid.splitlines()]
    assert len(set(counts)) == 1


def test_abbreviations() -> None:
    mashed = (
        "в/в – внутривенно(ый) ВОЗ – Всемирная организация здравоохранения "
        "ПЭТ/КТ – томография, совмещенная с томографией кг - килограмм "
        "мм рт.ст. - миллиметр ртутного столба эндоУЗИ – эндоскопическое исследование "
        "D0–3 — объем лимфодиссекции en bloc — удаление единым блоком "
        "APACHE-II — шкала оценки # – препарат off-label ** – жизненно необходимые"
    )
    entries = abbreviation_entries(mashed)
    assert [item.split(" – ")[0].split(" — ")[0].split(" - ")[0] for item in entries] == [
        "в/в",
        "ВОЗ",
        "ПЭТ/КТ",
        "кг",
        "мм рт.ст.",
        "эндоУЗИ",
        "D0–3",
        "en bloc",
        "APACHE-II",
        "#",
        "**",
    ], entries
    dose = abbreviation_entries("ЛТ – лучевая терапия ЛТ 5х5 Гр – лучевая терапия РОД 5 Гр, СОД 25 Гр")
    assert [item.split(" – ")[0] for item in dose] == ["ЛТ", "ЛТ 5х5 Гр"], dose
    stage = abbreviation_entries(
        "RECIST — критерии (Response Evaluation Criteria in Solid Tumors) "
        "TNM (аббревиатура от tumor, nodus и metastasis) — международная классификация"
    )
    assert stage[0].startswith("RECIST") and stage[1].startswith("TNM"), stage
    pet = abbreviation_entries(
        "ПЭТ/КТ — томография (Флудезоксиглюкоза [18F]) ПЭТ-КТ с FAPI - позитронная томография"
    )
    assert pet[0].startswith("ПЭТ/КТ") and pet[1].startswith("ПЭТ-КТ с FAPI"), pet
    doc = "## Список сокращений\n\n" + mashed + "\n\n## Термины и определения\n\nАдъювантная химиотерапия – вид химиотерапии. Безрецидивная выживаемость – интервал.\n"
    split = split_abbreviation_section(doc)
    abbr, terms = split.split("## Термины и определения")
    assert abbr.count("\n\nв/в –") == 1 or "\nв/в –" in abbr
    assert "\n\nВОЗ –" in abbr
    assert "Безрецидивная выживаемость – интервал." in terms
    assert terms.count("\n\n") == 1


def test_merge_continued_table() -> None:
    numbered = "\n".join(
        [
            "| № | Термин | Код |",
            "| --- | --- | --- |",
            "| 1 | осмотр | A01 |",
            "| 2 | анализ | B03 |",
            "",
            "| 3 | биопсия | A11 |",
            "| --- | --- | --- |",
            "| 4 | КТ | A06 |",
        ]
    )
    merged = merge_split_tables(numbered)
    assert sum(1 for line in merged.splitlines() if set(line.replace("|", "").replace("-", "").replace(" ", "")) == set() and "---" in line) == 1
    assert "| 3 | биопсия | A11 |" in merged
    assert "| 4 | КТ | A06 |" in merged
    dotted = "\n".join(
        [
            "| УДД | Расшифровка |",
            "| --- | --- |",
            "| 1. | Систематический обзор |",
            "",
            "| 2. | Отдельные исследования |",
            "| --- | --- |",
            "| 3. | Когортные исследования |",
        ]
    )
    joined_dots = merge_split_tables(dotted)
    assert joined_dots.count("\n| --- |") == 1 or joined_dots.count("| --- |") == 1
    assert "| 2. | Отдельные исследования |" in joined_dots
    assert "| 3. | Когортные исследования |" in joined_dots
    repeated = "\n".join(
        [
            "| № | Термин |",
            "| --- | --- |",
            "| 1 | осмотр |",
            "",
            "| № | Термин |",
            "| --- | --- |",
            "| | продолжение |",
            "| 2 | анализ |",
        ]
    )
    glued = merge_split_tables(repeated)
    assert sum(1 for line in glued.splitlines() if "---" in line and set(line.replace("|", "").replace("-", "").replace(" ", "")) == set()) == 1
    assert "осмотр продолжение" in glued
    assert "| 2 | анализ |" in glued
    split_by_picture = "\n".join(
        [
            "| Режим | Препарат |",
            "| --- | --- |",
            "| EP | этопозид |",
            "",
            "![Таблица, страница 41](assets/584_2/p041-table1.png)",
            "",
            "|  | цисплатин |",
            "| --- | --- |",
            "| TIP | паклитаксел |",
        ]
    )
    joined = merge_split_tables(split_by_picture)
    assert joined.count("![Таблица") == 1
    assert "| EP | этопозид |" in joined
    assert "|  | цисплатин |" in joined
    assert "этопозид цисплатин" not in joined
    assert "| TIP | паклитаксел |" in joined
    assert sum(1 for line in joined.splitlines() if line.startswith("| --- |")) == 1


def test_mermaid_rejects_sparse() -> None:
    labels = ["остановить", "уложить", "мониторинг", "вопрос"]
    assert mermaid(labels, [(0, 1)]) == ""
    graph = mermaid(labels, [(0, 1), (1, 2), (2, 3)])
    assert "n0" in graph and "n0 --> n1" in graph and graph.strip().endswith("```")


def main() -> None:
    test_symbol()
    test_hyphenation()
    test_headings()
    test_toc()
    test_table()
    test_abbreviations()
    test_merge_continued_table()
    test_mermaid_rejects_sparse()
    print("ok")


if __name__ == "__main__":
    main()
