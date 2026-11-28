"""Checks that do not need a PDF: symbols, hyphenation, headings, tables, schemes."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from assemble import _links
from ocr import restore_mass_numbers
from layout import (
    abbreviation_entries,
    drop_contents_tail,
    lift_abbreviation_heading,
    split_restarted_tables,
    letter_tail,
    numbered_tail,
    split_stacked_lines,
    cell_text,
    tracked_figure,
    flow,
    garbage_line,
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
    assert map_symbol("\uf0be") == "—"
    assert map_symbol("\uf02b") == "+"
    assert map_symbol("\uf0fc") == "✓"
    assert map_symbol("\uf0b3") == "≥"
    assert map_symbol("\uf03f") == "?"
    assert map_symbol("\uf0ad") == "↑"
    assert map_symbol("\uf03c") == "<"
    assert map_symbol("\uf03e") == ">"
    assert map_symbol("\uf05b47\uf05d") == "[47]"
    assert map_symbol("\uf0af") == "↓"
    assert map_symbol("\uf0e3") == "©"
    assert map_symbol("\uf07f") == "☐"
    assert map_symbol("\uf031", "Symbol") == "1"
    assert map_symbol("\uf031", "Webdings") == "☐"
    assert map_symbol("\uf031") == "\uf031"
    assert map_symbol("\uf0b2", "Wingdings") == "✦"
    assert map_symbol("\uf0fc", "Wingdings") == "✓"
    assert map_symbol("\uf0e9", "Wingdings-Regular") == "↑"
    assert map_symbol("\uf0ea", "Wingdings-Regular") == "↓"
    assert map_symbol("\uf097", "Wingdings2") == "•"
    assert map_symbol("\ue12c") == "•"
    assert map_symbol("\ue46f") == "▪"
    assert garbage_line("РаО < 60 мм рт.ст. или SaO < 90%") is False
    assert garbage_line("+ 10") is False
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
    risk = [
        {"x0": 325.3, "y0": 185.9, "x1": 392.1, "y1": 199.2, "text": "промежуточ-"},
        {"x0": 348.3, "y0": 199.7, "x1": 369.3, "y1": 213.0, "text": "ный"},
    ]
    assert cell_text(risk) == "промежуточный"
    compound = [
        {"x0": 40, "y0": 100, "x1": 90, "y1": 110, "text": "патолого-"},
        {"x0": 40, "y0": 114, "x1": 130, "y1": 124, "text": "анатомического"},
        {"x0": 134, "y0": 114, "x1": 210, "y1": 124, "text": "исследования"},
    ]
    assert cell_text(compound) == "патолого-анатомического исследования"
    compound = [
        {"x0": 404.5, "y0": 54.7, "x1": 452.4, "y1": 68.0, "text": "Опухоли"},
        {"x0": 455.4, "y0": 54.7, "x1": 471.5, "y1": 68.0, "text": "12-"},
        {"x0": 412.9, "y0": 68.5, "x1": 462.8, "y1": 81.8, "text": "перстной"},
    ]
    assert cell_text(compound) == "Опухоли 12-перстной"
    wrapped = [
        {"x0": 80.0, "y0": 100, "x1": 98.0, "y1": 112, "text": "по-"},
        {"x0": 80.0, "y0": 114, "x1": 110.0, "y1": 126, "text": "лях"},
    ]
    assert cell_text(wrapped) == "полях"
    stage = [
        {"x0": 165.8, "y0": 279.1, "x1": 170.9, "y1": 289.1, "text": "T"},
        {"x0": 174.8, "y0": 279.1, "x1": 180.1, "y1": 289.1, "text": "*"},
        {"x0": 170.9, "y0": 282.6, "x1": 174.8, "y1": 290.2, "text": "1"},
    ]
    assert cell_text(stage) == "T1 *"
    nodes = [
        {"x0": 303.1, "y0": 448.6, "x1": 309.3, "y1": 458.7, "text": "N"},
        {"x0": 313.2, "y0": 448.6, "x1": 316.2, "y1": 458.7, "text": ","},
        {"x0": 319.2, "y0": 448.6, "x1": 325.3, "y1": 458.7, "text": "N"},
        {"x0": 329.2, "y0": 448.6, "x1": 332.2, "y1": 458.7, "text": ","},
        {"x0": 335.2, "y0": 448.6, "x1": 341.3, "y1": 458.7, "text": "N"},
        {"x0": 309.3, "y0": 452.2, "x1": 313.2, "y1": 459.7, "text": "0"},
        {"x0": 325.3, "y0": 452.2, "x1": 329.2, "y1": 459.7, "text": "1"},
        {"x0": 341.3, "y0": 452.2, "x1": 345.2, "y1": 459.7, "text": "2"},
    ]
    assert cell_text(nodes) == "N0, N1, N2"
    superscript = [
        {"x0": 280.5, "y0": 426.1, "x1": 299.6, "y1": 436.2, "text": "мг/м"},
        {"x0": 299.6, "y0": 425.2, "x1": 303.5, "y1": 432.7, "text": "2"},
        {"x0": 306.7, "y0": 426.1, "x1": 320.2, "y1": 436.2, "text": "в/в"},
    ]
    assert cell_text(superscript) == "мг/м 2 в/в"
    assert garbage_line("**#~")
    assert not garbage_line("**Риск прогрессирования болезни определяется размером опухоли")
    assert not garbage_line("о В случае почечной дисфункции первая доза #карбоплатина** должна быть")
    assert not garbage_line("ёдоксорубицина**")


def test_headings() -> None:
    assert heading_level("1.1 Определение заболевания или состояния", False) == 3
    assert heading_level("1. Краткая информация по заболеванию", False) == 2
    assert heading_level("3. Hb Lepore и δβ-талассемия", True) == 2
    assert heading_level("3. Приказ Минздрава России от 13.10.2017", False) is None
    assert heading_level("1. Ильина Наталья Ивановна - вице-президент", False) is None
    assert heading_level("Список литературы", False) == 2
    assert heading_level("Приложение Б. Алгоритмы действий врача", False) == 2
    assert heading_level("XVII. Приложение Б. Алгоритмы действий врача", False) == 2
    assert heading_level("II. Рекомендуется выполнить операцию", False) is None
    joined = flow(
        [
            {"text": "Приложение Г1. Шкалы оценки, вопросники и другие оценочные", "x": 63, "x1": 400, "y": 431, "y1": 453, "h": 22, "bold": True},
            {"text": "|", "x": 27, "x1": 37, "y": 482, "y1": 504, "h": 22, "bold": True},
            {"text": "инструменты состояния пациента", "x": 63, "x1": 400, "y": 482, "y1": 504, "h": 22, "bold": True},
        ],
        800,
    )
    assert joined[0]["type"] == "heading"
    assert "оценочные инструменты" in joined[0]["text"]
    assert "|" not in joined[0]["text"]


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
    body = ["Приложение А3.2. Режимы лекарственной терапии"]
    body += [f"{i}. Режим внутрипузырной терапии." for i in range(1, 12)]
    body += ["Приложение А3.2.1.", "Приложение А3.2.2."]
    assert not is_toc(body)
    tail = drop_contents_tail([
        "## Приложение А3. Справочные материалы",
        "по применению лекарственного препарата...................................53",
        "## Приложение Б. Алгоритмы",
        "## Список сокращений",
        "ГИ - глубина инвазии",
    ])
    assert tail[0].endswith("Список сокращений")
    assert "препарата" not in tail[0]
    assert is_toc([
        "Приложение А3. Справочные материалы, включая соответствие показаний к",
        "применению и противопоказаний, способов применения и доз лекарственных",
        "препаратов, инструкции по применению лекарственного препарата...................................53",
        "Приложение В. Информация для пациентов...............................................................................61",
    ])


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
    glued = abbreviation_entries(
        "TNM – классификация стадий CI -доверительный интервал"
    )
    assert glued[0].startswith("TNM")
    assert any(part.startswith("CI") for part in glued)
    pair = abbreviation_entries(
        "ОСЖ – околоушная слюнная железа МЭК- мукоэпидермоидная карцинома"
    )
    assert pair[0].startswith("ОСЖ")
    assert pair[1].startswith("МЭК")
    virus = abbreviation_entries(
        "ПЦР - полимеразная цепная реакция РС вирус - респираторно-синцитиальный вирус"
    )
    assert virus[0].startswith("ПЦР")
    assert virus[1].startswith("РС вирус")
    pair2 = abbreviation_entries(
        "АСЛ-О – антистрептолизин-О БГСА – бета-гемолитический стрептококк группы А"
    )
    assert pair2[0].startswith("АСЛ-О")
    assert pair2[1].startswith("БГСА")
    aria = abbreviation_entries(
        "ARIA - Allergic Rhinitis and its Impact on Asthma - Аллергический ринит и его влияние на астму"
    )
    assert len(aria) == 1 and aria[0].startswith("ARIA")
    treg = abbreviation_entries("Th – Т-хелперы Treg – Т-регуляторные клетки")
    assert treg[0].startswith("Th") and treg[1].startswith("Treg")
    section = split_abbreviation_section(
        "## Список сокращений\n\n"
        "FDA – Food and Drug Administration – Агентство\n\n"
        "США IgE - иммуноглобулины класса Е\n\n"
        "ВЭБ – вирус\n\n"
        "Эпштейна-Барр МКБ 10 – международная классификация\n\n"
        "- C. pneumoniae - Chlamydophila pneumoniae IgG - иммуноглобулин класса G\n"
    )
    assert "Агентство США" in section
    assert "\nIgE - иммуноглобулины класса Е" in section
    assert "вирус Эпштейна-Барр" in section
    assert "\nМКБ 10 – международная классификация" in section
    assert "\nIgG - иммуноглобулин класса G" in section
    wrapped = split_abbreviation_section(
        "## Список сокращений\n\nCTV (Clinical Target Volume) - клинический\n\n"
        "объем мишени - включает макроскопический объем\n\nнед - неделя\n"
    )
    assert "клинический объем мишени" in wrapped
    assert "\nнед - неделя" in wrapped or "\n\nнед - неделя" in wrapped
    names = abbreviation_entries(
        "Барр ECOG - шкала оценки AUC* (area under the curve) – параметр концентрации"
    )
    assert names[0] == "Барр"
    assert names[1].startswith("ECOG")
    assert any(part.startswith("AUC") for part in names)
    assert [item.split(" – ")[0] for item in dose] == ["ЛТ", "ЛТ 5х5 Гр"], dose
    dose_next = abbreviation_entries(
        "ЛТ – лучевая терапия ЛТ 5х5 Гр – лучевая терапия РОД 5 Гр, СОД 25 Гр ЛФК – лечебная физкультура"
    )
    assert [item.split(" – ")[0] for item in dose_next] == ["ЛТ", "ЛТ 5х5 Гр", "ЛФК"], dose_next
    assert dose_next[1].endswith("СОД 25 Гр"), dose_next
    named = abbreviation_entries(
        "СРБ – С-реактивный белок Тиопурины – другие иммунодепрессанты "
        "НПВП – препараты «Печеночные» ферменты - определение активности"
    )
    assert named[0].startswith("СРБ") and named[1].startswith("Тиопурины"), named
    assert named[2].startswith("НПВП") and named[3].startswith("«Печеночные»"), named
    salts = abbreviation_entries(
        "PUCAI – индекс активности язвенного колита Аминосалициловая кислота и аналогичные препараты – аминосалицилаты"
    )
    assert salts[0].startswith("PUCAI") and salts[1].startswith("Аминосалициловая"), salts
    tail = abbreviation_entries(
        "БК – болезнь Крона ВЗК – воспалительное заболевание "
        "Тиопурины – иммунодепрессанты Аналоги пурина УЗИ – исследование"
    )
    assert [item.split(" – ")[0] for item in tail] == ["БК", "ВЗК", "Тиопурины", "УЗИ"], tail
    assert tail[0].endswith("Крона") and "Аналоги пурина" in tail[2], tail
    quoted_keep = abbreviation_entries(
        "ДАА – группа АТХ «Другие анальгетики и антипиретики» ДГБСГ - динамическая гепатобилисцинтиграфия"
    )
    assert quoted_keep[0].endswith("антипиретики»") and quoted_keep[1].startswith("ДГБСГ"), quoted_keep
    vein = abbreviation_entries("БРВ – безрецидивная выживаемость в/в ‒ внутривенно")
    assert vein[0].startswith("БРВ") and vein[0].endswith("выживаемость"), vein
    assert vein[1].startswith("в/в"), vein
    marrow = abbreviation_entries("ГСК – гемопоэтические стволовые клетки КМ- костный мозг")
    assert marrow[0].startswith("ГСК") and marrow[1].startswith("КМ"), marrow
    roman = abbreviation_entries(
        "АРА — антагонисты рецепторов ангиотензина II АСТ — аспартатаминотрансфераза"
    )
    assert roman[0].endswith("II"), roman
    assert roman[1].startswith("АСТ"), roman
    qualifier = abbreviation_entries(
        "КТ — компьютерная томография КФК общ. — креатинфосфокиназа общая"
    )
    assert qualifier[0].endswith("томография"), qualifier
    assert qualifier[1].startswith("КФК общ."), qualifier
    mutation = abbreviation_entries(
        "ЦВК – центральный венозный катетер Мутация BRAFV600E – гетерозиготная мутация гена BRAF"
    )
    assert mutation[0].startswith("ЦВК") and mutation[0].endswith("катетер"), mutation
    assert mutation[1].startswith("Мутация BRAFV600E"), mutation
    chrom = abbreviation_entries("ХгА - хромогранин А ХТ - химиотерапия")
    assert chrom[0].endswith("хромогранин А") and chrom[1].startswith("ХТ"), chrom
    vitamin = split_abbreviation_section(
        "## Список сокращений\n\nАВК – антагонисты витамина\n\nК АКТ – антикоагулянтная терапия\n"
    )
    assert "антагонисты витамина К" in vitamin, vitamin
    assert "\n\nАКТ – антикоагулянтная терапия" in vitamin, vitamin
    stage = abbreviation_entries(
        "RECIST — критерии (Response Evaluation Criteria in Solid Tumors) "
        "TNM (аббревиатура от tumor, nodus и metastasis) — международная классификация"
    )
    assert stage[0].startswith("RECIST") and stage[1].startswith("TNM"), stage
    pet = abbreviation_entries(
        "ПЭТ/КТ — томография (Флудезоксиглюкоза [18F]) ПЭТ-КТ с FAPI - позитронная томография"
    )
    assert pet[0].startswith("ПЭТ/КТ") and pet[1].startswith("ПЭТ-КТ с FAPI"), pet
    isotope = abbreviation_entries(
        "18F-ФДГ - Флудезоксиглюкоза [18F] ХЛТ — химиолучевая терапия"
    )
    assert isotope[0].startswith("18F-ФДГ") and isotope[0].endswith("[18F]"), isotope
    assert isotope[1].startswith("ХЛТ"), isotope
    gallium = abbreviation_entries(
        "68Ga-DOTATATE - 68 gallium [68Ga] DOTA-(Tyr3)-octreotate "
        "68Ga-DOTATOC - 68Ga DOTA-(Phe1)-(Tyr3)-octreotide "
        "68Ga-DOTANOC - 68Ga - DOTA-(Nal3)-octreotide "
        "MINEN (mixed neuroendocrine and -non-neuroendocrine neoplasm) - смешанная неоплазия"
    )
    assert [item.split(" - ")[0] for item in gallium] == [
        "68Ga-DOTATATE",
        "68Ga-DOTATOC",
        "68Ga-DOTANOC",
        "MINEN (mixed neuroendocrine and -non-neuroendocrine neoplasm)",
    ], gallium
    restored = restore_mass_numbers(
        [{"text": "Ga-DOTATATE - 68 gallium", "y": 0.235, "y1": 0.256, "h": 0.021}],
        [{"text": "68Оа-ЭОТАТАТЕ - 68 gallium", "y": 203.7, "y1": 214.7}],
        848.4,
    )
    assert restored[0]["text"].startswith("68Ga-DOTATATE"), restored
    spaced = restore_mass_numbers(
        [{"text": "68 Ga-DOTANOC - 68 Ga - DOTA", "y": 0.28, "y1": 0.30, "h": 0.02}],
        [],
        848.4,
    )
    assert spaced[0]["text"].startswith("68Ga-DOTANOC"), spaced
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
    tail = "\n\n".join(
        [
            "| УДД | Расшифровка |\n| --- | --- |\n| 4 | Несравнительные исследования |",
            "| 5 | Имеется лишь обоснование механизма действия |\n| --- | --- |",
            "Таблица 19. Шкала оценки уровней убедительности рекомендаций",
            "| УУР | Расшифровка |\n| --- | --- |\n| A | Сильная рекомендация |",
        ]
    )
    kept_scales = merge_split_tables(tail)
    assert kept_scales.count("| --- |") == 2
    assert "| 5 | Имеется лишь обоснование механизма действия |" in kept_scales
    assert "| УУР | Расшифровка |" in kept_scales
    series = "\n\n".join(
        [
            "| Категории | Тип | Риск | Рекомендации |\n| --- | --- | --- | --- |\n| EU-TIRADS 1 | нет узлов | 0% | - |",
            "| EU-TIRADS 2 | доброкачественное | 0% | наблюдение |\n| --- | --- | --- | --- |\n| EU-TIRADS 3 | низкий риск | 2-4% | ТАБ |",
        ]
    )
    one_scale = merge_split_tables(series)
    assert one_scale.count("\n| --- |") == 1
    assert "| EU-TIRADS 2 | доброкачественное | 0% | наблюдение |" in one_scale
    assert "| EU-TIRADS 3 | низкий риск | 2-4% | ТАБ |" in one_scale
    section = "\n\n".join(
        [
            "| Период | 1 год | 2-й год | 3-й год |\n| --- | --- | --- | --- |\n| Осмотр | 3 мес. | 3 мес. | 4 мес. |",
            "| Обследование для выявления осложнений |  |  |  |\n| --- | --- | --- | --- |\n| Анализ мочи | 3 мес. | 3 мес. | 6 мес. |",
        ]
    )
    joined = merge_split_tables(section)
    assert joined.count("\n| --- |") == 1
    assert "выявления осложнений" in joined
    assert "| Анализ мочи | 3 мес. | 3 мес. | 6 мес. |" in joined
    stage = "\n\n".join(
        [
            "| Стадия | Т | N | M |\n| --- | --- | --- | --- |\n| IVB | Любое T | 3 | 0 |",
            "| Стадия | Т | N | M |\n| --- | --- | --- | --- |\n|  | 4b | Любое N | 0 |\n| IVC | Любое T | Любое N | 1 |",
        ]
    )
    staged = merge_split_tables(stage)
    assert staged.count("\n| --- |") == 1
    assert "|  | 4b | Любое N | 0 |" in staged
    assert "Любое T 4b" not in staged
    formulary = "\n\n".join(
        [
            "| Режим | Кому | Балл |\n| --- | --- | --- |\n| Авелумаб** + акситиниб** | без терапии | 3 |",
            "| Ниволумаб** + ипилимумаб** | группа плохого прогноза | 4 |\n| --- | --- | --- |\n| Сунитиниб** | хороший прогноз | 3 |",
        ]
    )
    one_form = merge_split_tables(formulary)
    assert one_form.count("\n| --- |") == 1
    assert "| Ниволумаб** + ипилимумаб** | группа плохого прогноза | 4 |" in one_form
    assert "| Сунитиниб** | хороший прогноз | 3 |" in one_form
    wrapped = "\n\n".join(
        [
            "| Методы | 3 м. | 60 м. |\n| --- | --- | --- |\n| Гормональные исследования уровня | X | X |",
            "| кальцитонина в крови |  |  |\n| --- | --- | --- |\n| Диспансерный прием | X | X |",
        ]
    )
    one_row = merge_split_tables(wrapped)
    assert one_row.count("\n| --- |") == 1
    assert "исследования уровня кальцитонина в крови" in one_row
    assert "| Диспансерный прием | X | X |" in one_row
    titled = "\n\n".join(
        [
            "| Методы | 3 м. | 60 м. |\n| --- | --- | --- |\n| Анализ | X | X |",
            "| Другая таблица |  |  |\n| --- | --- | --- |\n| Строка | a | b |",
        ]
    )
    assert merge_split_tables(titled).count("\n| --- |") == 2
    lone = "\n\n".join(
        [
            "|  | Возраст | Лимфодиссекция | ТКТ |\n| --- | --- | --- | --- |\n| ETA, 2012 | порог | повышение | во всех |",
            "| Российская ассоциация эндокринологов, 2013 | Рекомендации АТА 2009 | При уровне | Всем |\n| --- | --- | --- | --- |",
        ]
    )
    with_row = merge_split_tables(lone)
    assert with_row.count("\n| --- |") == 1
    assert "| Российская ассоциация эндокринологов, 2013 | Рекомендации АТА 2009 | При уровне | Всем |" in with_row
    grades = "\n\n".join(
        [
            "| УУР | Расшифровка |\n| --- | --- |\n| A | Сильная рекомендация |",
            "| B | Условная рекомендация |\n| --- | --- |\n| C | Слабая рекомендация |",
        ]
    )
    scale = merge_split_tables(grades)
    assert scale.count("\n| --- |") == 1
    assert "| B | Условная рекомендация |" in scale
    assert "| C | Слабая рекомендация |" in scale
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
    histology = "\n\n".join(
        [
            "\n".join(
                [
                    "| Инвазивные карциномы молочной железы |  |",
                    "| --- | --- |",
                    "| 8500/3 | Инвазивная протоковая карцинома |",
                    "| 8525/3 | Плеоморфная карцинома |",
                    "| 8013/3 | Нейроэндокринная карцинома |",
                    "| 8041/3 | Нейроэндокринная карцинома, мелкоклеточная |",
                    "| Эпителиально-миоэпителиальные опухоли |  |",
                ]
            ),
            "\n".join(
                [
                    "| 8940/0 | Плеоморфная аденома |",
                    "| --- | --- |",
                    "| 8983/3 | Аденомиоэпителиома неспецифицированная |",
                ]
            ),
        ]
    )
    one = merge_split_tables(histology)
    assert one.count("| --- |") == 1
    assert "| 8940/0 | Плеоморфная аденома |" in one
    assert "| 8983/3 | Аденомиоэпителиома неспецифицированная |" in one
    separated = "\n\n".join(
        [
            "| Уровень достоверности доказательств | Расшифровка |\n| --- | --- |\n| 1 | обзор |\n| 2 | исследования |\n| 3 | когортные |\n| 4 | случай |\n| 5 | мнение |",
            "Шкала оценки уровней достоверности доказательств для методов лечения",
            "| Уровень достоверности доказательств | Расшифровка |\n| --- | --- |\n| 1 | метаанализ |",
        ]
    )
    scales = merge_split_tables(separated)
    assert scales.count("| --- |") == 2


def test_citation_tail() -> None:
    assert garbage_line("118];") is False
    assert garbage_line("[115]);") is False
    assert garbage_line("Документ подписан и передан через систему разработки и ведения стандартов медицинской помощи")
    assert garbage_line("Владелец сертификата: организация, Сертификат: серийный номер, период Дата и время подписания сотрудник действия")
    assert garbage_line("E=shelygin@yandex.ru, C=RU, G=Юрий Анатольевич, SN=Шелыгин")
    assert garbage_line("Генеральный директор ФГБУ ДОКУМЕНТ ПОДПИСАН «ЦЭККМП» ЭЛЕКТРОННОЙ подписью Сертификат Ь31с")
    assert garbage_line("****") is True
    assert garbage_line("48") is True
    lines = [
        {"text": "препаратов [95, 116–", "x": 20, "y": 80, "y1": 95, "h": 15, "bold": False},
        {"text": "118];", "x": 20, "y": 99, "y1": 114, "h": 15, "bold": False},
        {"text": "3 режим далее", "x": 20, "y": 260, "y1": 275, "h": 15, "bold": False},
    ]
    blocks = flow(lines, 842)
    assert any("116–118];" in block["text"] for block in blocks)
    assert any(block["text"].startswith("3 режим") for block in blocks)


def test_regimen_and_service_continuation() -> None:
    chemo = "\n\n".join(
        [
            "| Схема | Препарат | Доза | Путь |\n| --- | --- | --- | --- |\n| Монотерапия | Дакарбазин** | 250 мг/м2 | В/в |",
            "| Монотерапия | Ломустин** | 130 мг/м2 | Внутрь |\n| --- | --- | --- | --- |\n| Комбинация | Цисплатин** | 20 мг/м2 | В/в |",
        ]
    )
    one = merge_split_tables(chemo)
    assert one.count("\n| --- |") == 1
    assert "| Монотерапия | Ломустин** | 130 мг/м2 | Внутрь |" in one
    services = "\n\n".join(
        [
            "| Термин | Услуга |\n| --- | --- |\n| Дерматоскопия | A03.01.001 Осмотр |\n| Биопсия | A08.01.001 Исследование |",
            "| Цитология | A08.01.002 Исследование |\n| --- | --- |\n| УЗИ | A04.06.002 Исследование |",
        ]
    )
    joined = merge_split_tables(services)
    assert joined.count("\n| --- |") == 1
    assert "| Цитология | A08.01.002 Исследование |" in joined


def test_t_continuation() -> None:
    parts = "\n\n".join(
        [
            "| Критерий T | Толщина | Изъязвление |\n| --- | --- | --- |\n| T2a | >1,0 и ≤2,0 мм | Без изъязвления |",
            "| T2b | >1,0 и ≤2,0 мм | C изъязвлением |\n| --- | --- | --- |\n| T3 | >2,0 и ≤4,0 мм | Неизвестно |",
        ]
    )
    joined = merge_split_tables(parts)
    assert joined.count("\n| --- |") == 1
    assert "| T2b | >1,0 и ≤2,0 мм | C изъязвлением |" in joined
    assert "| T3 | >2,0 и ≤4,0 мм | Неизвестно |" in joined


def test_wrapped_criteria() -> None:
    rows = [
        ["", "№", "Критерии оценки качества", "Оценка"],
        ["п/п", "", "", "выполнения"],
        ["1.", "", "Выполнен прием врача-", ""],
        ["", "", "гастроэнтеролога с", ""],
        ["", "", "(при наличии свищей)", "Да/Нет"],
        ["", "", "Выполнена колоноскопия с", ""],
        ["2.", "", "исследованием кишки (при", "Да/Нет"],
        ["", "", "установлении диагноза)", ""],
    ]
    grid = markdown_table(rows)
    assert "| 1. | Выполнен прием врача-гастроэнтеролога с (при наличии свищей) | Да/Нет |" in grid
    assert "| 2. | Выполнена колоноскопия с исследованием кишки (при установлении диагноза) | Да/Нет |" in grid
    assert grid.count("Да/Нет") == 2


def test_shifted_index() -> None:
    rows = [
        ["УФ-", ""],
        ["индекс", "Меры защиты"],
        ["0-2", "Защита не нужна"],
        ["", "Необходима защита. В полуденные часы"],
        ["", "одежду с длинными рукавами и шляпу. Пользуйтесь солнцезащитным"],
        ["3-7", "кремом"],
        ["", "Необходима усиленная защита"],
        ["8", "кремом"],
    ]
    grid = markdown_table(rows)
    assert "| 3-7 | Необходима защита. В полуденные часы одежду с длинными рукавами и шляпу. Пользуйтесь солнцезащитным кремом |" in grid
    assert "| 8 | Необходима усиленная защита кремом |" in grid
    assert "| 3-7 | кремом |" not in grid


def test_garbled_span() -> None:
    from layout import garbled_span

    assert garbled_span("Клинические рско&хъ'хядеяцшжн")
    assert garbled_span("Ра |р;юо|'М1КП клинических рекомендаций:")
    assert not garbled_span("Клинические рекомендации")
    assert not garbled_span("Ассоциация онкологов России")
    assert not garbled_span("е-таП: 1ео&аз12000@та11.ги")
    assert not garbled_span("отделением отдела хирургии эндокринных'органов ФГБУ")


def test_tracked_figure() -> None:
    words = [{"x0": 40 + i * 5, "y0": 100, "x1": 44 + i * 5, "y1": 110, "text": ch} for i, ch in enumerate("пациентс")]
    words += [{"x0": 40, "y0": 80, "x1": 120, "y1": 92, "text": "Приложение"}]
    words += [{"x0": 40 + i * 5, "y0": 140, "x1": 44 + i * 5, "y1": 150, "text": ch} for i, ch in enumerate("лечение")]
    assert tracked_figure(words)
    prose = [{"x0": 40, "y0": 100 + i * 14, "x1": 200, "y1": 112 + i * 14, "text": "диагностика"} for i in range(20)]
    prose += [{"x0": 20, "y0": 100 + i * 14, "x1": 28, "y1": 112 + i * 14, "text": "и"} for i in range(6)]
    assert not tracked_figure(prose)


def test_mermaid_rejects_sparse() -> None:
    labels = ["остановить", "уложить", "мониторинг", "вопрос"]
    assert mermaid(labels, [(0, 1)]) == ""
    graph = mermaid(labels, [(0, 1), (1, 2), (2, 3)])
    assert "n0" in graph and "n0 --> n1" in graph and graph.strip().endswith("```")
    cut = ["Опухоль нерезектабельна", "Радиохирургия или", "Системная терапия", "Наблюдение"]
    assert mermaid(cut, [(0, 1), (1, 2), (2, 3)]) == ""
    glued = [
        "Адъювантная гормонотерапия проводилась",
        "Ингибиторы Ингибиторы ароматазы",
        "Фулвестрант",
        "Прогестагены",
    ]
    assert mermaid(glued, [(0, 1), (1, 2), (2, 3), (0, 3)]) == ""
    kept = mermaid(["конец в конец", "бок в бок", "наблюдение"], [(0, 2), (1, 2)])
    assert "конец в конец" in kept
    percentile = ["Процентиль роста", "50-й 90-й 95-й", "80 94 98 105", "81 95 99 106", "34 49 54 61"]
    assert mermaid(percentile, [(0, 1), (1, 2), (2, 3), (3, 4), (0, 4)]) == ""


def test_stray_column() -> None:
    grid = markdown_table(
        [
            ["Уровень", "Расшифровка", ""],
            ["достоверности", "", ""],
            ["доказательств", "", ""],
            ["2", "Отдельные рандомизированные клинические исследования", "и"],
            ["", "систематические обзоры исследований любого дизайна,", "за"],
            ["", "исключением рандомизированных клинических исследований", "с"],
            ["", "применением метаанализа", ""],
        ]
    )
    assert "и за с" not in grid
    assert grid.startswith("| Уровень достоверности доказательств | Расшифровка |")
    assert "исследования и систематические" in grid
    assert "дизайна, за исключением" in grid
    assert "исследований с применением" in grid
    assert grid.count("|") and "\n| --- | --- | --- |" not in grid


def test_stage_and_tail() -> None:
    stacked = split_stacked_lines(["III", "T1, T2\nT3", "N1\nN0, N1", "M0\nM0"])
    assert stacked == [
        ["III", "T1, T2", "N1", "M0"],
        ["", "T3", "N0, N1", "M0"],
    ]
    assert split_stacked_lines(["Т4a", "Опухоль\nпрорастает\nтолько\nприлежащие"]) is None
    nodes = "\n\n".join(
        [
            "| Символ |  |\n| --- | --- |\n| N2b | метастазы |",
            "| N2c | с обеих сторон |\n| --- | --- |\n| N3 | больше 6 см |",
        ]
    )
    joined = merge_split_tables(nodes)
    assert joined.count("\n| --- |") == 1
    assert "| N2c | с обеих сторон |" in joined
    cut = "\n\n".join(
        [
            "| Т | Описание |\n| --- | --- |\n| Т4b | Опухоль распространяется на жевательный аппарат, крыловидные |",
            "отростки основной кости или основания черепа и/или охватывает сонную артерию",
            "*Примечание: только поверхностная эрозия.",
        ]
    )
    glued = merge_split_tables(cut)
    assert "крыловидные отростки основной кости" in glued
    assert "*Примечание" in glued
    scale = "\n\n".join(
        [
            "| УДД | Расшифровка |\n| --- | --- |\n| 1 | обзор |\n| 2 | РКИ |\n| 3 | когортные |",
            "4 Несравнительные исследования, описание клинического случая 5 Имеется лишь обоснование механизма действия",
            "Таблица 3. Шкала УУР",
        ]
    )
    extended = merge_split_tables(scale)
    assert "| 4 | Несравнительные исследования, описание клинического случая |" in extended
    assert "| 5 | Имеется лишь обоснование механизма действия |" in extended
    assert "Таблица 3" in extended
    assert numbered_tail([["УДД", "Расшифровка"], ["---", "---"], ["3", "когортные"]], "1. Приказ") is None
    grades = "\n\n".join(
        [
            "| УУР | Расшифровка |\n| --- | --- |\n| A | сильная |\n| B | условная |",
            "C Слабая рекомендация (отсутствие доказательств надлежащего качества)",
            "Порядок обновления клинических рекомендаций.",
        ]
    )
    graded = merge_split_tables(grades)
    assert "| C | Слабая рекомендация" in graded
    assert "Порядок обновления" in graded
    assert letter_tail([["УУР", "Расшифровка"], ["---", "---"], ["B", "условная"]], "Порядок обновления") is None
    quality = "\n\n".join(
        [
            "| № | Критерии |  | Оценка |\n| --- | --- | --- | --- |\n| 6 |  | исследование | Да/нет |",
            "| 7 | исследование ЛДГ | Да/нет |\n| --- | --- | --- |\n| 8 | удаление | Да/нет |",
        ]
    )
    joined = merge_split_tables(quality)
    assert joined.count("\n| --- |") == 1
    assert "| 7 |  | исследование ЛДГ | Да/нет |" in joined
    note = "\n\n".join(
        [
            "| Схема | Режим | Длительность | Примечание |\n| --- | --- | --- | --- |\n| Pem | доза | 21 день | проводится поддерживающая |",
            "|  |  |  | или развития непереносимой токсичности |\n| --- | --- | --- | --- |\n| Nivo | доза | 21 день | приоритетный |",
        ]
    )
    noted = merge_split_tables(note)
    assert "поддерживающая или развития" in noted
    dose = "\n\n".join(
        [
            "| Схема | Препарат | Доза |\n| --- | --- | --- |\n| Ниволумаб | #Ниволумаб | 3 мг/кг или |",
            "| Схема | Препарат | Доза |\n| --- | --- | --- |\n|  |  | 240 мг |\n|  | #Ниволумаб | 480 мг |",
        ]
    )
    dosed = merge_split_tables(dose)
    assert "3 мг/кг или 240 мг" in dosed
    wrapped_head = markdown_table(
        [
            ["Схема", "Препарат", "Доза", "Путь", "Дни", "Длительность"],
            ["", "", "", "введения", "приема", "цикла, дни"],
            ["CarD1", "доцетаксел", "65 мг/м2", "В/в", "1-й", "21"],
        ]
    )
    assert "Путь введения" in wrapped_head.splitlines()[0]
    assert "введения" not in "\n".join(wrapped_head.splitlines()[2:])
    assert "|  | #Ниволумаб | 480 мг |" in dosed
    assert noted.count("\n| --- |") == 1
    assert "| Nivo | доза | 21 день | приоритетный |" in noted
    port = "\n\n".join(
        [
            "| Параметр | Баллы |\n| --- | --- |\n| Гематокрит < 30% | + 10 |",
            "Параметр Баллы",
            "РаО < 60 мм рт.ст. или SaO < 90% 2 2 + 10",
            "Плевральный выпот + 10",
            "Таблица 2. Классы риска",
        ]
    )
    # The fixture has one score row; the rule needs three. Pad it.
    port = port.replace(
        "| Гематокрит < 30% | + 10 |",
        "| Натрий | + 20 |\n| Глюкоза | + 10 |\n| Гематокрит < 30% | + 10 |",
    )
    scored = merge_split_tables(port)
    assert "| РаО < 60 мм рт.ст. или SaO < 90% | + 10 |" in scored
    assert "| Плевральный выпот | + 10 |" in scored
    assert "Таблица 2" in scored
    assert scored.count("Параметр") == 1
    quality = "\n\n".join(
        [
            "| № | Критерии качества | Оценка выполнения (да/нет) |\n| --- | --- | --- |\n| 1. | Выполнен прием | Да/нет |",
            "| 2. | Назначена антибактериальная терапия системного действия | Да/нет |\n| --- | --- | --- |",
            "Критерии оценки качества специализированной помощи",
            "| № | Критерии качества | Оценка выполнения (да/нет) |\n| --- | --- | --- |\n| 1 | Выполнен прием | Да/нет |",
        ]
    )
    joined = merge_split_tables(quality)
    assert joined.count("| 2. | Назначена антибактериальная терапия системного действия | Да/нет |") == 1
    assert joined.count("| --- | --- | --- |") == 2


def test_column_cuts() -> None:
    from extract import _column_cuts

    class Rule:
        def __init__(self, x, y0, y1):
            self.x0, self.y0, self.y1 = x, y0, y1

    boxes = [
        [(27, 10, 258, 32), (258, 10, 358, 32), (358, 10, 413, 32)],
        [(27, 32, 258, 80), (258, 32, 358, 80), (358, 32, 413, 80)],
    ]
    rules = [Rule(307.6, 0, 33), Rule(307.6, 32, 80), Rule(258, 0, 33)]
    assert _column_cuts(boxes, rules) == [307.6]


def test_udd_wrap() -> None:
    rows = [
        ["УДД", "Источник доказательств", "", ""],
        ["1.", "", "Систематические обзоры исследований с контролем референсным", ""],
        ["", "", "методом или систематический обзор рандомизированных клинических", ""],
        ["", "", "исследований с применением мета-анализа", ""],
        ["3.", "Исследования без последовательного контроля", "", ""],
    ]
    grid = markdown_table(rows)
    assert "| 1. | Систематические обзоры исследований с контролем референсным методом или систематический обзор рандомизированных клинических исследований с применением мета-анализа |" in grid
    assert "| 3. | Исследования без последовательного контроля |" in grid
    assert grid.count("\n") == 3
    parts = [
        "| УДД | Источник доказательств |\n| --- | --- |\n| A | Сильная рекомендация, все исследования имеют высокое или |",
        "|  | удовлетворительное методологическое качество, их выводы по |\n| --- | --- |\n|  | интересующим исходам являются согласованными) |\n| B | Условная рекомендация |",
    ]
    joined = merge_split_tables("\n\n".join(parts))
    assert "высокое или удовлетворительное" in joined
    assert "являются согласованными)" in joined
    assert "| B | Условная рекомендация |" in joined
    repeated = merge_split_tables(
        "\n\n".join(
            [
                "| УДД | Источник |\n| --- | --- |\n| A | Сильная рекомендация, все исследования имеют высокое или |",
                "| УДД | Источник |\n| --- | --- |\n|  | удовлетворительное методологическое качество, их выводы по |\n|  | интересующим исходам являются согласованными) |\n| B | Условная рекомендация |",
            ]
        )
    )
    assert "выводы по интересующим исходам являются согласованными)" in repeated
    assert "| B | Условная рекомендация |" in repeated


def test_parenthetical_codes() -> None:
    sample = (
        "AUROC (Area Under Receiver Operating Characteristic Curve) - показатель "
        "Вах (BCL2 Associated X Protein) - bcl-2-подобный белок "
        "Bcl-2 (B-Cell Leukemia) - фактор апоптоза"
    )
    codes = [item.split(" - ")[0].split(" (")[0] for item in abbreviation_entries(sample)]
    assert codes == ["AUROC", "Вах", "Bcl-2"]


def test_split_header() -> None:
    prev = (
        "| Гистологический кри-терий ЭоЭ | Степень поражения | Распространенность (стадия) |\n"
        "| --- | --- | --- |\n"
        "| Эозинофильное воспаление | 0 баллов | 0 баллов |"
    )
    prose = "1 В норме эозинофилы отсутствуют. Гистологический кри- Степень поражения Распространенность"
    nxt = "| терий ЭоЭ |  | (стадия) |\n| --- | --- | --- |\n| Базальный слой | 0 - нет | 0 - нет |"
    joined = merge_split_tables("\n\n".join([prev, prose, nxt]))
    assert "| Базальный слой | 0 - нет | 0 - нет |" in joined
    assert joined.count("Гистологический") == 1
    assert "кри- Степень" not in joined


def test_stamp_block() -> None:
    lines = [
        {"text": "Сведения представлены в приложении.", "x": 50, "y": 560, "y1": 572, "h": 12, "bold": False},
        {"text": "Генеральный директор ФГБУ", "x": 50, "y": 627, "y1": 639, "h": 12, "bold": False},
        {"text": "ДОКУМЕНТ ПОДПИСАН", "x": 200, "y": 632, "y1": 644, "h": 12, "bold": False},
        {"text": "ЭЛЕКТРОННОЙ подписью", "x": 200, "y": 640, "y1": 652, "h": 12, "bold": False},
        {"text": "Сертификат Ь31с24", "x": 200, "y": 656, "y1": 668, "h": 12, "bold": False},
    ]
    blob = " ".join(block["text"] for block in flow(lines, 842))
    assert "приложении" in blob
    assert "ПОДПИСАН" not in blob
    assert "Генеральный" not in blob


def test_stacked_header() -> None:
    words = [
        {"x0": 27, "y0": 153, "x1": 70, "y1": 164, "text": "Степень"},
        {"x0": 27, "y0": 161, "x1": 50, "y1": 172, "text": "НАС"},
    ]
    assert cell_text(words) == "Степень НАС"


def test_cell_edge_word() -> None:
    words = [
        {"x0": 131.4, "y0": 581.6, "x1": 191.2, "y1": 594.9, "text": "гиперпигме"},
        {"x0": 106.3, "y0": 602.5, "x1": 144.7, "y1": 615.8, "text": "нтация"},
        {"x0": 365.3, "y0": 223.3, "x1": 457.5, "y1": 236.6, "text": "самообслуживани"},
        {"x0": 365.3, "y0": 244.2, "x1": 377.2, "y1": 257.5, "text": "ю,"},
        {"x0": 400.0, "y0": 244.2, "x1": 430.0, "y1": 257.5, "text": ">50%"},
    ]
    # Two columns. Join each column on its own, the way a cell does.
    skin = cell_text(words[:2])
    scale = cell_text(words[2:])
    assert skin == "гиперпигментация"
    assert "самообслуживанию," in scale and ">50%" in scale
    kept = cell_text(
        [
            {"x0": 106.3, "y0": 454.9, "x1": 166.8, "y1": 468, "text": "папулезная"},
            {"x0": 106.3, "y0": 475.5, "x1": 134.6, "y1": 488, "text": "сыпь"},
        ]
    )
    assert kept == "папулезная сыпь"
    spaced = cell_text(
        [
            {"x0": 200, "y0": 100, "x1": 280, "y1": 112, "text": "симптомов"},
            {"x0": 200, "y0": 114, "x1": 220, "y1": 126, "text": "или"},
            {"x0": 224, "y0": 114, "x1": 270, "y1": 126, "text": "полная"},
        ]
    )
    assert spaced == "симптомов или полная"
    liver = cell_text(
        [
            {"x0": 202.3, "y0": 620, "x1": 258.2, "y1": 633, "text": "билирубин"},
            {"x0": 202.3, "y0": 641, "x1": 208.0, "y1": 654, "text": "в"},
            {"x0": 211.0, "y0": 641, "x1": 245.3, "y1": 654, "text": "норме,"},
        ]
    )
    assert liver == "билирубин в норме,"
    chains = cell_text(
        [
            {"x0": 10, "y0": 0, "x1": 90, "y1": 10, "text": "глобиновых"},
            {"x0": 10, "y0": 12, "x1": 42, "y1": 22, "text": "цепей"},
        ]
    )
    assert chains == "глобиновых цепей"
    alpha = cell_text(
        [
            {"x0": 10, "y0": 0, "x1": 110, "y1": 10, "text": "квадрипликацией"},
            {"x0": 10, "y0": 12, "x1": 18, "y1": 22, "text": "α"},
        ]
    )
    assert alpha == "квадрипликацией α"


def test_repeated_column_banner() -> None:
    def grid(rows: list[str]) -> str:
        head = "| Таблица 4. Балльная оценка |  |  |  |"
        body = "\n".join(rows)
        return f"{head}\n| --- | --- | --- | --- |\n| Орган | Балл 0 | Балл 1 | Балл 2 |\n{body}"

    first = grid(["| КОЖА | нет | мало | много |"])
    second = grid(["| РОТ | нет | мало | много |"])
    merged = merge_split_tables(f"{first}\n\n{second}")
    assert merged.count("Орган | Балл 0") == 1
    assert "КОЖА" in merged and "РОТ" in merged
    assert merged.count("\n| --- |") == 1


def test_banner_tail_joins_the_cut_row() -> None:
    first = "\n".join([
        "| Таблица 4. Балльная оценка проявлений |  |  |  |  |",
        "| --- | --- | --- | --- | --- |",
        "| Орган | Балл 0 | Балл 1 | Балл 2 | Балл 3 |",
        "| ГЕНИТАЛИИ | нет симптомов | осмотр | дискомфорт | сильная боль либо |",
    ])
    tail = "\n".join([
        "| Орган | Балл 0 | Балл 1 | Балл 2 | Балл 3 |",
        "| --- | --- | --- | --- | --- |",
        "|  |  | гинекологичес | гинекологическом | невозможность |",
        "|  |  | ком | обследовании | влагалищной |",
        "|  |  | обследовании |  | пенетрации |",
    ])
    merged = merge_split_tables(
        f"{first}\n\n![Таблица, страница 71](p071-table1.png)\n\n"
        "Таблица 4. Балльная оценка проявлений хронической РТПХ\n\n"
        f"{tail}"
    )
    assert merged.count("\n| --- |") == 1
    assert merged.count("Орган | Балл 0") == 1
    assert "осмотр гинекологическом обследовании" in merged
    assert "дискомфорт гинекологическом обследовании" in merged
    assert "сильная боль либо невозможность влагалищной пенетрации" in merged
    assert "Таблица 4. Балльная оценка проявлений хронической РТПХ" not in merged


def test_comma_wrap_stays_one_row() -> None:
    grid = markdown_table([
        ["", "Генотип", "Признаки", "тяжесть"],
        ["Минимальные проявления", "--/αα, -α/-α,", "Анемия 1 ст, ↓ MCV,", "1+"],
        ["", "-α/αТα", "↓ MCН", ""],
    ])
    assert grid.count("\n|") == 2
    assert "-α/-α, -α/αТα" in grid
    assert "↓ MCV, ↓ MCН" in grid


def test_headerless_continuation() -> None:
    first = "\n".join([
        "|  | Генотип | Признаки | тяжесть |",
        "| --- | --- | --- | --- |",
        "| Носительство | β+/β | Незначительное снижение MCV | 0 |",
        "| Малая форма | β+/β+ | Анемия 1 ст | 0-1 |",
    ])
    genotype = "β+/β0 или сочетание β+/β с трипликацией альфа генов"
    second = "\n".join([
        f"| Промежуточная форма | {genotype} | Анемия 2-3 ст | 2-3 |",
        "| --- | --- | --- | --- |",
        "| Большая форма | β0/β0 | Анемия 3 ст | 4+ |",
    ])
    merged = merge_split_tables(f"{first}\n\n{second}")
    assert merged.count("\n| --- |") == 1
    assert "Промежуточная форма" in merged
    assert "Большая форма" in merged
    assert merged.splitlines()[0].startswith("|  | Генотип |")
    infections = "\n".join([
        "| Показания | Исследование |",
        "| --- | --- |",
        "| Температура ≥38°С, впервые возникшая | Взятие крови в 2 флакона для гемокультуры |",
        "| Катетер-ассоциированная инфекция | Взятие одновременно крови из вены и из ЦВК |",
        "| Ожидаемая нейтропения (лейкопения) >10 дней | Определение антител к грибам рода аспергиллы |",
    ])
    stomatitis = "\n".join([
        "| Стоматит | Получение мазков со слизистой оболочки ротоглотки для бактерий, вирусов и грибов |",
        "| --- | --- |",
        "| Эзофагит | Эзофагогастродуоденоскопия и соскоб со слизистой оболочки |",
    ])
    joined = merge_split_tables(f"{infections}\n\n{stomatitis}")
    assert joined.count("\n| --- |") == 1
    assert joined.splitlines()[0].startswith("| Показания | Исследование |")
    assert "| Стоматит |" in joined and "| Эзофагит |" in joined
    platelets = "\n".join([
        "|  | Количество |  |",
        "| --- | --- | --- |",
        "| Показание | тромбоцитов в | Примечания |",
        "|  | периферической крови |  |",
    ])
    doses = "\n".join([
        "| Во время или после химиотерапии, в период миелотоксического агранулоцитоза | Менее 20 × 109/л | При синдроме повышенного потребления тромбоцитов порог повышают |",
        "| --- | --- | --- |",
        "| Установка ЦВК | Менее 30 × 109/л | - |",
    ])
    folded = merge_split_tables(f"{platelets}\n\n{doses}")
    assert folded.count("\n| --- |") == 1
    assert folded.splitlines()[0].startswith("| Показание | Количество тромбоцитов в периферической крови | Примечания |")
    assert "| Установка ЦВК |" in folded
    assert "Во время или после химиотерапии" in folded.splitlines()[2]


def test_abbreviation_heading_lifts_out_of_the_cell() -> None:
    dotted = [
        "## Приложение Б. Алгоритмы........................................................................ 156",
        "Таблица 11. Лабораторный и инструментальный мониторинг............................ 159",
        "## Приложение В. Информация для пациентов....................................... 162",
    ]
    table = "\n".join([
        "| АЛТ | Список сокращений аланинаминотрансфераза |",
        "| --- | --- |",
        "| АСТ | аспартатаминотрансфераза |",
    ])
    lifted = lift_abbreviation_heading([*dotted, table])
    kept = drop_contents_tail(lifted)
    assert kept[0] == "## Список сокращений"
    assert "Список сокращений аланинаминотрансфераза" not in kept[1]
    assert "| АЛТ | аланинаминотрансфераза |" in kept[1]
    assert "Приложение Б" not in "\n".join(kept)


def test_restarted_criteria_tables_split() -> None:
    rows = [
        "| № | Критерии оценки качества | Оценка выполнения |",
        "| --- | --- | --- |",
        "| 1. | Выполнена проба | Да/Нет |",
        "| 4. | Выполнено молекулярно-биологическое исследование мокроты | Да/Нет |",
        "|  | Критерии оценки качества специализированной медицинской помощи детям при туберкулезе |  |",
        "| 1. | Выполнена спиральная компьютерная томография легких | Да/Нет |",
        "| 4. | Выполнено исследование чувствительности | Да/Нет |",
    ]
    split = split_restarted_tables("\n".join(rows))
    assert split.count("\n| --- |") == 2
    parts = split.split("Критерии оценки качества специализированной")
    assert "| 4. | Выполнено молекулярно-биологическое" in parts[0]
    assert "| 1. | Выполнена спиральная" in parts[1]
    assert parts[1].count("\n| --- |") == 1


def test_histology_code_continues() -> None:
    prev = "\n".join([
        "| Злокачественные |  |",
        "| --- | --- |",
        "| Хондросаркома | 9222/3 |",
        "| Периостальная хондросаркома | 9221/3 |",
        "| Светлоклеточная хондросаркома | 9242/3 |",
        "| Мезенхимальная хондросаркома | 9240/3 |",
        "| Остеобластома БДУ | 9200/1 |",
    ])
    nxt = "\n".join([
        "| Гигантоклеточная опухоль кости БДУ | 9250/1 |",
        "| --- | --- |",
        "| Злокачественные |  |",
    ])
    merged = merge_split_tables(prev + "\n\n" + nxt)
    assert merged.count("\n| --- |") == 1, merged
    assert "| Гигантоклеточная опухоль кости БДУ | 9250/1 |" in merged.split("\n| --- |", 1)[1]


def test_flowchart_rejects_evidence_table() -> None:
    from extract import flowchart_column_is_a_table, flowchart_labels_are_a_table

    scale = ["Уровни достоверности доказательств (ЕОК)", "A", "Данные многочисленных рандомизированных клинических исследований"]
    assert flowchart_labels_are_a_table(scale)
    classes = ["Таблица П1. Классы показаний согласно рекомендациям", "Класс", "Определение"]
    assert flowchart_labels_are_a_table(classes)
    route = ["I этап кардиореабилитации", "Отделение реанимации и интенсивной терапии", "МДРК"]
    assert not flowchart_labels_are_a_table(route)
    assert flowchart_column_is_a_table([88] * 20)
    assert not flowchart_column_is_a_table([80, 80, 80, 80, 368, 368, 368])


def test_grade_is_not_an_asset() -> None:
    linked = _links("[148](УДД 5, УУР С)", "assets/758_2")
    assert linked == "[148] (УДД 5, УУР С)"
    picture = _links("![Схема](p157-fig1.png)", "assets/758_2")
    assert picture == "![Схема](assets/758_2/p157-fig1.png)"


def main() -> None:
    test_symbol()
    test_hyphenation()
    test_headings()
    test_toc()
    test_table()
    test_abbreviations()
    test_merge_continued_table()
    test_citation_tail()
    test_regimen_and_service_continuation()
    test_t_continuation()
    test_wrapped_criteria()
    test_udd_wrap()
    test_parenthetical_codes()
    test_split_header()
    test_stamp_block()
    test_stacked_header()
    test_cell_edge_word()
    test_repeated_column_banner()
    test_banner_tail_joins_the_cut_row()
    test_comma_wrap_stays_one_row()
    test_headerless_continuation()
    test_abbreviation_heading_lifts_out_of_the_cell()
    test_restarted_criteria_tables_split()
    test_histology_code_continues()
    test_flowchart_rejects_evidence_table()
    test_grade_is_not_an_asset()
    test_shifted_index()
    test_garbled_span()
    test_stage_and_tail()
    test_stray_column()
    test_column_cuts()
    test_tracked_figure()
    test_mermaid_rejects_sparse()
    print("ok")


if __name__ == "__main__":
    main()
