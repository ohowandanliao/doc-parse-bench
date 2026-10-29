"""Unlimited OCR 2 token grammar, based on the official format description.

Reference: baidu/Unlimited-OCR, utils/process_unlimitedOCR2.py at
6c5d1906ba638a7cd87bc00f14452a47fdabf16b. We retain pages and raw levels instead
of the official renderer's single-root title rewrite.
"""

import re

PAGE_RE = re.compile(r"<\s*/?\s*PAGE\s*\d*\s*>", re.I)
BLOCK_RE = re.compile(
    r"<\s*BLOCK\s*>\s*([a-zA-Z_][a-zA-Z_0-9]*)"
    r"\s*((?:(?:<LEVEL\s*\d*>|\[[\d\s,，.\-]+\])\s*)*)"
    r"(?:<FORK>)?",
    re.I,
)
BARE_RE = re.compile(
    r"(?m)(^|(?<=<PAGE>)|(?<=<FORK>))"
    r"((?:cross_|append_)?(?:title|text|table|image|chart|equation|header|footer)"
    r"(?:<LEVEL\d+>)?\s*\[[-\d\s,，.]+\])",
    re.I,
)


def parse_pages(text: str) -> list[list[dict]]:
    text = text.strip().removeprefix("```markdown").removesuffix("```").strip()
    text = BARE_RE.sub(lambda m: m.group(1) + "<BLOCK>" + m.group(2), text)
    segments = PAGE_RE.split(text)
    if PAGE_RE.match(text):
        segments = segments[1:]
    pages = []
    for segment in segments:
        matches = list(BLOCK_RE.finditer(segment))
        blocks = []
        if not matches:
            if segment.strip():
                blocks.append({"type": "__raw__", "content": segment.strip()})
        else:
            if segment[: matches[0].start()].strip():
                blocks.append({"type": "__raw__", "content": segment[: matches[0].start()].strip()})
            previous_merge = False
            for index, match in enumerate(matches):
                end = matches[index + 1].start() if index + 1 < len(matches) else len(segment)
                content = segment[match.end() : end]
                merge_next = "<MERGE>" in content
                level = re.search(r"<LEVEL\s*(\d+)>", match[2], re.I)
                bbox = re.search(r"\[([^]]+)\]", match[2])
                blocks.append(
                    {
                        "type": match[1].lower(),
                        "level": int(level[1]) if level else None,
                        "bbox": bbox[1] if bbox else None,
                        "content": content.replace("<MERGE>", "").strip(),
                        "merge_prev": previous_merge,
                    }
                )
                previous_merge = merge_next
        pages.append(blocks)
    return pages
