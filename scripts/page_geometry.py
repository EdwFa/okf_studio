"""Ruled tables and box-and-arrow diagrams on a grayscale page image.

A table is a lattice of ruled cells that share borders. A diagram is a set of
separate boxes joined by a line that is actually drawn between them. The line's
heavier end is the arrowhead.
"""

from __future__ import annotations

import numpy as np


def analyze(gray: np.ndarray) -> dict:
    height, width = gray.shape
    dark = gray < 110
    horizontal, vertical = _rules(dark)
    cells = _cells(horizontal, vertical)
    tables, nodes = _tables_and_nodes(cells)
    edges = _edges(dark, nodes)
    extra, nodes, edges = _lone_rows(nodes, edges)
    tables.extend(extra)
    return {
        "w": int(width),
        "h": int(height),
        "tables": [
            [[[int(v) for v in cell] for cell in row] for row in table] for table in tables
        ],
        "nodes": [[int(v) for v in node] for node in nodes],
        "edges": [[int(a), int(b)] for a, b in edges],
    }


def _runs(mask: np.ndarray, min_len: int, gap: int = 3) -> list[tuple[int, int]]:
    segs: list[tuple[int, int]] = []
    index = 0
    size = len(mask)
    while index < size:
        if not mask[index]:
            index += 1
            continue
        start = index
        holes = 0
        last = index
        while index < size and holes <= gap:
            if mask[index]:
                holes = 0
                last = index
            else:
                holes += 1
            index += 1
        if last + 1 - start >= min_len:
            segs.append((start, last + 1))
    return segs


def _rules(dark: np.ndarray) -> tuple[list[tuple[int, int, int]], list[tuple[int, int, int]]]:
    height, width = dark.shape
    horizontal: list[dict] = []
    for y in range(height):
        if int(dark[y].sum()) < 160:
            continue
        for x0, x1 in _runs(dark[y], 150):
            placed = False
            for band in horizontal:
                overlap = min(x1, band["x1"]) - max(x0, band["x0"])
                if y - band["y1"] <= 3 and overlap > 60:
                    band["x0"] = min(band["x0"], x0)
                    band["x1"] = max(band["x1"], x1)
                    band["y1"] = y
                    placed = True
                    break
            if not placed:
                horizontal.append({"x0": x0, "x1": x1, "y0": y, "y1": y})
    hlines = [
        (band["x0"], band["x1"], (band["y0"] + band["y1"]) // 2)
        for band in horizontal
        if band["y1"] - band["y0"] <= 4 and band["x1"] - band["x0"] >= 150
    ]

    vertical: list[dict] = []
    for x in range(width):
        if int(dark[:, x].sum()) < 34:
            continue
        for y0, y1 in _runs(dark[:, x], 34):
            placed = False
            for band in vertical:
                overlap = min(y1, band["y1"]) - max(y0, band["y0"])
                if x - band["x1"] <= 3 and overlap > 18:
                    band["x1"] = x
                    band["y0"] = min(band["y0"], y0)
                    band["y1"] = max(band["y1"], y1)
                    placed = True
                    break
            if not placed:
                vertical.append({"x0": x, "x1": x, "y0": y0, "y1": y1})
    vlines = [
        ((band["x0"] + band["x1"]) // 2, band["y0"], band["y1"])
        for band in vertical
        if band["x1"] - band["x0"] <= 4 and band["y1"] - band["y0"] >= 34
    ]
    return hlines, vlines


def _cells(horizontal: list[tuple[int, int, int]], vertical: list[tuple[int, int, int]]) -> list[tuple[int, int, int, int]]:
    boxes: list[tuple[int, int, int, int]] = []
    ordered = sorted(horizontal, key=lambda line: (line[2], line[0]))
    for index, (x0, x1, top) in enumerate(ordered):
        for below_x0, below_x1, bottom in ordered[index + 1 :]:
            if bottom - top < 22:
                continue
            if bottom - top > 640:
                break
            if abs(below_x0 - x0) > 14 or abs(below_x1 - x1) > 14:
                continue
            left = any(abs(x - x0) <= 8 and y0 <= top + 8 and y1 >= bottom - 8 for x, y0, y1 in vertical)
            right = any(abs(x - x1) <= 8 and y0 <= top + 8 and y1 >= bottom - 8 for x, y0, y1 in vertical)
            if not (left and right):
                continue
            cut = any(top + 8 < y < bottom - 8 and ax0 <= x0 + 10 and ax1 >= x1 - 10 for ax0, ax1, y in ordered)
            if cut:
                continue
            boxes.append((x0, top, x1, bottom))
            break
    split: list[tuple[int, int, int, int]] = []
    for x0, top, x1, bottom in _dedupe(boxes):
        cuts = sorted(
            {
                x
                for x, y0, y1 in vertical
                if x0 + 24 < x < x1 - 24 and y0 <= top + 8 and y1 >= bottom - 8
            }
        )
        merged = []
        for x in cuts:
            if merged and x - merged[-1] <= 10:
                merged[-1] = x
            else:
                merged.append(x)
        bounds = [x0, *merged, x1]
        if len(bounds) == 2:
            split.append((x0, top, x1, bottom))
            continue
        for left, right in zip(bounds, bounds[1:]):
            if right - left >= 36:
                split.append((left, top, right, bottom))
    return _dedupe(split)


def _dedupe(boxes: list[tuple[int, int, int, int]]) -> list[tuple[int, int, int, int]]:
    kept: list[tuple[int, int, int, int]] = []
    for box in sorted(boxes, key=lambda item: (item[1], item[0])):
        if any(_same(box, other) for other in kept):
            continue
        kept.append(box)
    return kept


def _same(a: tuple[int, int, int, int], b: tuple[int, int, int, int]) -> bool:
    return abs(a[0] - b[0]) <= 8 and abs(a[1] - b[1]) <= 8 and abs(a[2] - b[2]) <= 8 and abs(a[3] - b[3]) <= 8


def _rows(cells: list[tuple[int, int, int, int]]) -> list[list[tuple[int, int, int, int]]]:
    rows: list[list[tuple[int, int, int, int]]] = []
    for cell in sorted(cells, key=lambda item: (item[1], item[0])):
        if rows and abs(cell[1] - rows[-1][0][1]) <= 8 and abs(cell[3] - rows[-1][0][3]) <= 8:
            rows[-1].append(cell)
        else:
            rows.append([cell])
    for row in rows:
        row.sort(key=lambda item: item[0])
    return rows


def _aligned(a: list[tuple[int, int, int, int]], b: list[tuple[int, int, int, int]]) -> bool:
    if len(a) != len(b):
        return False
    for left, right in zip(a, b):
        if abs(left[0] - right[0]) > 12 or abs(left[2] - right[2]) > 12:
            return False
    return True


def _tables_and_nodes(
    cells: list[tuple[int, int, int, int]],
) -> tuple[list[list[list[tuple[int, int, int, int]]]], list[tuple[int, int, int, int]]]:
    rows = _rows(cells)
    used = [False] * len(rows)
    tables: list[list[list[tuple[int, int, int, int]]]] = []
    for index, row in enumerate(rows):
        if used[index] or len(row) < 2:
            continue
        stack = [row]
        used[index] = True
        while True:
            nxt = None
            for cursor in range(index + 1, len(rows)):
                if used[cursor]:
                    continue
                if rows[cursor][0][1] - stack[-1][0][3] > 10:
                    break
                if abs(rows[cursor][0][1] - stack[-1][0][3]) <= 8 and _aligned(stack[-1], rows[cursor]):
                    nxt = cursor
                break
            if nxt is None:
                break
            stack.append(rows[nxt])
            used[nxt] = True
            index = nxt
        if len(stack) >= 2:
            tables.append(stack)
        else:
            used[index] = False
    nodes: list[tuple[int, int, int, int]] = []
    for row, taken in zip(rows, used):
        if not taken:
            nodes.extend(row)
    return tables, nodes


def _shaft(strip: np.ndarray, along_rows: bool) -> int | None:
    """Index of a thin straight line that reaches both ends of the strip."""
    frac = strip.mean(axis=0 if along_rows else 1)
    hot = np.where(frac > 0.42)[0]
    clusters: list[list[int]] = []
    for index in hot:
        if clusters and index - clusters[-1][-1] <= 3:
            clusters[-1].append(int(index))
        else:
            clusters.append([int(index)])
    for cluster in clusters:
        if len(cluster) > 6:
            continue
        pos = cluster[len(cluster) // 2]
        line = strip[:, pos] if along_rows else strip[pos, :]
        if len(line) < 8:
            continue
        ink = np.where(line > 0)[0]
        if ink.size == 0 or ink.size < 0.48 * len(line):
            continue
        if ink[0] <= 14 and ink[-1] >= len(line) - 14:
            return pos
    return None


def _edges(dark: np.ndarray, nodes: list[tuple[int, int, int, int]]) -> list[tuple[int, int]]:
    edges: list[tuple[int, int]] = []
    for i, a in enumerate(nodes):
        for j, b in enumerate(nodes):
            if i >= j:
                continue
            link = _link(dark, a, b, nodes, i, j)
            if link:
                edges.append(link)
    return edges


def _corridor_clear(
    nodes: list[tuple[int, int, int, int]], skip: set[int], box: tuple[int, int, int, int]
) -> bool:
    x0, y0, x1, y1 = box
    for index, node in enumerate(nodes):
        if index in skip:
            continue
        if node[2] <= x0 or node[0] >= x1 or node[3] <= y0 or node[1] >= y1:
            continue
        return False
    return True


def _arrowhead(
    dark: np.ndarray, upper: tuple[int, int, int, int], lower: tuple[int, int, int, int]
) -> bool:
    x0 = max(upper[0], lower[0]) + 8
    x1 = min(upper[2], lower[2]) - 8
    y1 = lower[1] - 2
    y0 = max(upper[3] + 2, y1 - 34)
    if x1 - x0 < 24 or y1 - y0 < 10:
        return False
    band = dark[y0:y1, x0:x1]
    columns = np.where(band.sum(axis=0) >= 4)[0]
    return columns.size > 0 and columns[-1] - columns[0] <= 16


def _link(
    dark: np.ndarray,
    a: tuple[int, int, int, int],
    b: tuple[int, int, int, int],
    nodes: list[tuple[int, int, int, int]],
    i: int,
    j: int,
) -> tuple[int, int] | None:
    upper, lower = (a, b) if a[1] <= b[1] else (b, a)
    upper_i, lower_i = (i, j) if a[1] <= b[1] else (j, i)
    gap_y = lower[1] - upper[3]
    overlap_x0 = max(upper[0], lower[0]) + 6
    overlap_x1 = min(upper[2], lower[2]) - 6
    if 8 <= gap_y <= 480 and overlap_x1 - overlap_x0 >= 16:
        strip = dark[upper[3] + 2 : lower[1] - 2, overlap_x0:overlap_x1]
        shaft = _shaft(strip, along_rows=True) if strip.size else None
        linked = False
        if shaft is not None:
            at = overlap_x0 + shaft
            linked = gap_y <= 220 or _corridor_clear(
                nodes, {i, j}, (at - 8, upper[3] + 2, at + 8, lower[1] - 2)
            )
        if not linked and gap_y <= 220 and _arrowhead(dark, upper, lower):
            linked = True
        if linked:
            return (upper_i, lower_i)
    left, right = (a, b) if a[0] <= b[0] else (b, a)
    left_i, right_i = (i, j) if a[0] <= b[0] else (j, i)
    gap_x = right[0] - left[2]
    overlap_y0 = max(left[1], right[1]) + 4
    overlap_y1 = min(left[3], right[3]) - 4
    if 8 <= gap_x <= 320 and overlap_y1 - overlap_y0 >= 14:
        strip = dark[overlap_y0:overlap_y1, left[2] + 2 : right[0] - 2]
        if strip.size and _shaft(strip, along_rows=False) is not None:
            return (left_i, right_i)
    return None


def _lone_rows(
    nodes: list[tuple[int, int, int, int]], edges: list[tuple[int, int]]
) -> tuple[list, list, list]:
    if not nodes:
        return [], [], []
    rows = _rows(nodes)
    tables = []
    drop: set[int] = set()
    lookup = {node: index for index, node in enumerate(nodes)}
    if not edges:
        for row in rows:
            indexes = [lookup[cell] for cell in row]
            if len(row) >= 2:
                tables.append([row])
                drop.update(indexes)
    kept_nodes = [node for index, node in enumerate(nodes) if index not in drop]
    remap = {old: new for new, old in enumerate(index for index in range(len(nodes)) if index not in drop)}
    kept_edges = [(remap[a], remap[b]) for a, b in edges if a in remap and b in remap]
    return tables, kept_nodes, kept_edges
