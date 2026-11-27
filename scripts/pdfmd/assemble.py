"""Page blocks to one Markdown document."""

from __future__ import annotations

import re

from layout import merge_split_tables, split_abbreviation_section


def _links(text: str, folder: str) -> str:
    return re.sub(r"\]\(([^)/]+)\)", lambda match: f"]({folder}/{match.group(1)})", text)


def _render(block: dict, folder: str) -> str:
    kind = block["type"]
    text = _links(block["text"].strip(), folder)
    if not text:
        return ""
    if kind == "heading":
        level = min(max(int(block.get("level", 2)), 1), 5)
        return f"{'#' * level} {text}"
    if kind == "list":
        return f"- {text}"
    return text


def assemble(pages: list[dict], asset_folder: str) -> str:
    rendered: list[str] = []
    for page in pages:
        if page.get("skip"):
            continue
        for block in page.get("blocks") or []:
            piece = _render(block, asset_folder)
            if piece:
                rendered.append(piece)
    counts: dict[str, int] = {}
    for piece in rendered:
        if piece.startswith("#") or piece.startswith("- ") or piece.startswith("|") or piece.startswith("!"):
            continue
        if len(piece) < 80:
            counts[piece] = counts.get(piece, 0) + 1
    repeated = {text for text, count in counts.items() if count >= 4}
    kept = [piece for piece in rendered if piece not in repeated]
    text = "\n\n".join(kept)
    text = re.sub(r"\n{3,}", "\n\n", text).strip() + "\n"
    return merge_split_tables(split_abbreviation_section(text))
