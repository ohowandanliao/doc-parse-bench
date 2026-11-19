"""Small tracked fallback for tests when the ignored PDF2Text snapshot is absent."""

from enum import IntEnum


class BlockType(IntEnum):
    TEXT = 0
    TITLE = 1
    PARAGRAPH_TITLE = 2
    DOC_TITLE = 3
    IMAGE = 4
    IMAGE_CAPTION = 5
    IMAGE_FOOTNOTE = 6
    TABLE = 7
    HEADER = 12
    FOOTER = 13
    PAGE_NUMBER = 14
    HEADER_IMAGE = 15
    FOOTER_IMAGE = 16
    CHART = 18
    CHART_BODY = 19
    CHART_CAPTION = 20
    CHART_FOOTNOTE = 21


_NAMES = {item.name.lower(): item.value for item in BlockType}
_MARGINAL = {
    BlockType.HEADER,
    BlockType.FOOTER,
    BlockType.PAGE_NUMBER,
    BlockType.HEADER_IMAGE,
    BlockType.FOOTER_IMAGE,
}
_TITLES = {BlockType.TITLE, BlockType.PARAGRAPH_TITLE, BlockType.DOC_TITLE}


def _type(block):
    value = block.get("type", -1)
    return _NAMES.get(value.lower(), -1) if isinstance(value, str) else value


def _set_type(block, value):
    block["type"] = BlockType(value).name.lower()


def _text(block):
    values = []
    for line in block.get("lines") or []:
        for span in line.get("spans") or []:
            value = span.get("text", span.get("content", ""))
            if isinstance(value, str):
                values.append(value)
    return "".join(values)


def filter_header_footer(pdf_info):
    for page in pdf_info:
        page["para_blocks"] = [
            block for block in page.get("para_blocks") or [] if _type(block) not in _MARGINAL
        ]


def keep_header_footer(pdf_info):
    for page in pdf_info:
        discarded = page.get("discarded_blocks") or []
        kept = []
        remaining = []
        for block in discarded:
            if _type(block) in _MARGINAL:
                _set_type(block, BlockType.TEXT)
                kept.append(block)
            else:
                remaining.append(block)
        page["discarded_blocks"] = remaining
        page.setdefault("para_blocks", []).extend(kept)
        for block in page["para_blocks"]:
            if _type(block) in _MARGINAL:
                _set_type(block, BlockType.TEXT)


def _appendix_page(pdf_info):
    minimum = max(0, int(len(pdf_info) * 0.5))
    for page in pdf_info:
        if int(page.get("page_idx", 0)) < minimum:
            continue
        for block in page.get("para_blocks") or []:
            if _type(block) in _TITLES and _text(block).strip().lower().startswith(
                ("附录", "appendix")
            ):
                return int(page["page_idx"])
    return None


def filter_appendix(pdf_info):
    start = _appendix_page(pdf_info)
    if start is not None:
        pdf_info[:] = [page for page in pdf_info if int(page["page_idx"]) < start]


def _clear_text(block):
    for line in block.get("lines") or []:
        for span in line.get("spans") or []:
            for key in ("text", "content"):
                if isinstance(span.get(key), str):
                    span[key] = ""
    for child in block.get("blocks") or []:
        _clear_text(child)


def filter_chart_analysis(pdf_info):
    keep = {BlockType.CHART_BODY, BlockType.CHART_CAPTION, BlockType.CHART_FOOTNOTE}
    for page in pdf_info:
        for block in page.get("para_blocks") or []:
            if _type(block) != BlockType.CHART:
                continue
            _set_type(block, BlockType.IMAGE)
            block["blocks"] = [child for child in block.get("blocks") or [] if _type(child) in keep]
            for child in block["blocks"]:
                if _type(child) == BlockType.CHART_BODY:
                    _clear_text(child)


def filter_image_analysis(pdf_info):
    def visit(block):
        for line in block.get("lines") or []:
            for span in line.get("spans") or []:
                if span.get("type") == "image" or span.get("generated") is True:
                    for key in ("text", "content"):
                        if isinstance(span.get(key), str):
                            span[key] = ""
        for child in block.get("blocks") or []:
            visit(child)

    for page in pdf_info:
        for block in page.get("para_blocks") or []:
            visit(block)


def relevel_titles(_pdf_info):
    return None


def apply_content_filters(
    pdf_info,
    *,
    filename="",
    keep_header_footer_enabled=False,
    remove_toc=False,
    remove_appendix=False,
    seal_enabled=True,
    chart_analysis_enabled=True,
    image_analysis_enabled=True,
):
    del filename, remove_toc, seal_enabled
    if keep_header_footer_enabled:
        keep_header_footer(pdf_info)
    else:
        filter_header_footer(pdf_info)
    if remove_appendix:
        filter_appendix(pdf_info)
    if not image_analysis_enabled:
        filter_image_analysis(pdf_info)
    if not chart_analysis_enabled:
        filter_chart_analysis(pdf_info)
