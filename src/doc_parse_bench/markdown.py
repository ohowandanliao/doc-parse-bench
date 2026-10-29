"""Markdown parsing/rendering shared by all models; no GT-dependent repairs."""

import re

from bs4 import BeautifulSoup
from markdown_it import MarkdownIt

from .schema import VISUAL_TYPES, Block, Page

IMAGE_RE = re.compile(r"!\[[^\]]*\]\(([^)]+)\)|<img\b[^>]*>", re.I)


def table_html(text: str) -> str:
    if not text.strip():
        return ""
    if re.search(r"<table\b", text, re.I):
        return text
    rendered = MarkdownIt("commonmark").enable("table").render(text)
    soup = BeautifulSoup(rendered, "html.parser")
    table = soup.find("table")
    return str(table) if table else text


def merge_tables(fragments: list[str], drop_repeated_header: bool = True) -> str:
    """Join only explicitly linked tables; preserve spans and de-duplicate a header prefix."""
    soups = [BeautifulSoup(table_html(value), "html.parser") for value in fragments]
    tables = [soup.find("table") for soup in soups]
    if not all(tables):
        return "\n\n".join(fragments)
    base = tables[0]
    base_rows = base.find_all("tr")

    def row_key(row):
        return [
            (
                cell.get("rowspan", "1"),
                cell.get("colspan", "1"),
                re.sub(r"\s+", "", cell.get_text()),
            )
            for cell in row.find_all(["td", "th"], recursive=False)
        ]

    headers = [row_key(row) for row in base_rows[:5]]
    destination = base.find("tbody") or base
    for table in tables[1:]:
        rows = table.find_all("tr")
        skip = 0
        if drop_repeated_header:
            for row, header in zip(rows[:5], headers):
                if row_key(row) != header:
                    break
                skip += 1
        for row in rows[skip:]:
            destination.append(row.extract())
    return str(base)


def parse_markdown(text: str, page: int, prefix: str = "md") -> list[Block]:
    """Keep Markdown source, group HTML tables/formulas, recover Ovis visual boxes."""
    lines = text.splitlines()
    tokens = MarkdownIt("commonmark").enable("table").parse(text)
    blocks = []
    i = 0
    while i < len(tokens):
        token = tokens[i]
        if token.level != 0 or token.map is None or token.nesting == -1:
            i += 1
            continue
        start, end = token.map
        source = "\n".join(lines[start:end]).strip()
        kind, level, value = "text", None, source
        if token.type == "heading_open":
            kind, level = "title", int(token.tag[1:])
            value = tokens[i + 1].content
        elif token.type == "table_open" or re.match(r"<table\b", source, re.I):
            kind = "table"
        elif token.type in {"fence", "code_block"}:
            kind = "code"
        elif re.fullmatch(r"\s*(?:\$\$.*\$\$|\\\[.*\\\])\s*", source, re.S):
            kind = "formula"
        if source:
            images = list(IMAGE_RE.finditer(source))
            cursor = 0
            # Image links can share a paragraph with surrounding text.
            if images and kind == "text":
                for match in images:
                    if source[cursor : match.start()].strip():
                        blocks.append(Block("", "text", source[cursor : match.start()].strip()))
                    marker = match.group()
                    coords = re.search(r"bbox_([\d.]+)_([\d.]+)_([\d.]+)_([\d.]+)", marker)
                    bbox = [float(c) / 1000 for c in coords.groups()] if coords else None
                    blocks.append(
                        Block("", "image", bbox=bbox, metadata={"original_markdown": marker})
                    )
                    cursor = match.end()
                if source[cursor:].strip():
                    blocks.append(Block("", "text", source[cursor:].strip()))
            else:
                blocks.append(
                    Block(
                        "", kind, value, table_html(source) if kind == "table" else "", level=level
                    )
                )
        i += 1
        # A top-level list's map already spans all child paragraphs.
        while i < len(tokens) and (tokens[i].level > 0 or tokens[i].nesting == -1):
            i += 1
    for index, block in enumerate(blocks):
        block.id = f"{prefix}.p{page}.{index:04d}"
    return blocks


def render_block(block: Block, page: int, chart_policy: str = "native") -> str:
    if block.type in VISUAL_TYPES:
        if block.type == "chart" and chart_policy == "chart-table":
            content = block.html or block.text
            if content and (
                "<table" in content.lower() or re.search(r"\|.*\n\s*\|?\s*:?-", content)
            ):
                return table_html(content)
        if block.bbox:
            coords = "_".join(str(round(c * 1000)) for c in block.bbox)
            return f"![](page{page}_{coords}.jpg)"
        return block.metadata.get("original_markdown", "![image](image)")
    if block.type == "table":
        return table_html(block.html or block.text)
    if block.type == "title":
        value = re.sub(r"\s+", " ", re.sub(r"^#{1,6}\s+", "", block.text)).strip()
        return f"{'#' * max(1, block.level or 1)} {value}" if value else ""
    if block.type == "formula":
        value = block.text.strip()
        if not value:
            return ""
        if value.startswith(("$$", r"\[")):
            return value
        return f"$$\n{value}\n$$"
    return block.text


def render_page(page: Page, chart_policy: str = "native") -> str:
    return (
        "\n\n".join(
            value
            for block in page.blocks
            if (value := render_block(block, page.number, chart_policy))
        )
        + "\n"
    )
