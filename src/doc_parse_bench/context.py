"""Document assembly using native links or an explicitly selected conservative policy.

This module only consumes a prediction Document. Annotation relations are never
transferred to prediction documents. Every inferred relation records its evidence.
"""

import re
from copy import deepcopy

from bs4 import BeautifulSoup

from .markdown import merge_tables, render_block
from .schema import MARGINAL_TYPES, Document


def infer_context(doc: Document, policy: str = "native") -> Document:
    result = deepcopy(doc)
    original_pages = {b.id: p.metadata.get("original_page") for p in result.pages for b in p.blocks}
    blocked = []
    for relation in result.relations:
        left = original_pages.get(relation["source"])
        right = original_pages.get(relation["target"])
        if left is not None and right is not None and right - left > 1:
            blocked.append(relation)
    if blocked:
        result.relations = [r for r in result.relations if r not in blocked]
        result.metadata["blocked_native_source_gap_relations"] = blocked
    if policy == "native":
        return result
    if policy != "conservative":
        raise ValueError(f"未知合并策略：{policy}")
    existing = {(r["source"], r["target"]) for r in result.relations}
    events = []
    for left, right in zip(result.pages, result.pages[1:]):
        if right.number != left.number + 1:
            continue
        lp, rp = left.metadata.get("original_page"), right.metadata.get("original_page")
        if lp is not None and rp is not None and rp != lp + 1:
            events.append({"pages": [left.number, right.number], "action": "skip_source_gap"})
            continue

        def body(block):
            return block.type not in MARGINAL_TYPES and not (
                block.type == "text" and re.fullmatch(r"\s*\d{1,4}\s*", block.text)
            )

        tails = [b for b in left.blocks if body(b)]
        heads = [b for b in right.blocks if body(b)]
        if not tails or not heads:
            continue
        a, b = tails[-1], heads[0]
        if a.type != b.type or a.type not in {"text", "table"}:
            continue
        if (a.id, b.id) in existing:
            continue
        has_geometry = bool(a.bbox and b.bbox)
        if has_geometry:
            if a.bbox[3] < 0.80 or b.bbox[1] > 0.22:
                continue
            if abs(a.bbox[0] - b.bbox[0]) > 0.05 or abs(a.bbox[2] - b.bbox[2]) > 0.08:
                continue
        reason = ""
        if a.type == "text":
            tail, head = a.text.rstrip(), b.text.lstrip()
            if not tail or not head or re.search(r"[。！？.!?:：;；]$", tail):
                continue
            if re.match(r"(?:[第一二三四五六七八九十\d]+[章节、.)）]|[-*#])", head):
                continue
            # Without geometry, require long spans plus a constrained continuation cue.
            if (
                head[0].isascii()
                and head[0].islower()
                and (has_geometry or (len(tail) > 80 and len(head) > 50))
            ):
                reason = "open_english_sentence" + ("_aligned" if has_geometry else "_content_only")
            elif b.metadata.get("merge_prev"):
                reason = "native_merge_prev_with_geometry"
            elif (
                len(tail) > 80
                and len(head) > 50
                and tail[-1] in "的和与在为于以及而将从对把被由是"
                and re.match(r"[\u4e00-\u9fff]", head)
            ):
                reason = "open_chinese_connective" + (
                    "_aligned" if has_geometry else "_content_only"
                )
        else:
            rows_a = BeautifulSoup(a.html or a.text, "html.parser").find_all("tr")
            rows_b = BeautifulSoup(b.html or b.text, "html.parser").find_all("tr")
            if rows_a and rows_b:

                def key(row):
                    return [c.get_text(strip=True) for c in row.find_all(["td", "th"])]

                if key(rows_a[0]) == key(rows_b[0]) and len(key(rows_a[0])) > 1:
                    reason = "aligned_repeated_table_header"
        if reason:
            result.relations.append(
                {
                    "type": "truncated",
                    "source": a.id,
                    "target": b.id,
                    "method": "conservative",
                    "evidence": reason,
                }
            )
            events.append({"source": a.id, "target": b.id, "evidence": reason})
    result.metadata["context_policy"] = policy
    result.metadata["context_events"] = events
    return result


def relation_groups(doc: Document) -> list[list[str]]:
    ids = [b.id for p in doc.pages for b in p.blocks]
    parent = {key: key for key in ids}

    def find(key):
        while parent[key] != key:
            parent[key] = parent[parent[key]]
            key = parent[key]
        return key

    for relation in doc.relations:
        if relation["type"] != "truncated":
            continue
        a, b = relation["source"], relation["target"]
        if a not in parent or b not in parent:
            raise ValueError(f"{doc.id}: 关系引用缺失块 {a} -> {b}")
        parent[find(b)] = find(a)
    groups = {}
    for key in ids:
        groups.setdefault(find(key), []).append(key)
    return list(groups.values())


def render_document(doc: Document, chart_policy: str = "native") -> str:
    index = {b.id: (p.number, b) for p in doc.pages for b in p.blocks}
    contents = []
    for group in relation_groups(doc):
        blocks = [index[key][1] for key in group]
        if len(group) > 1 and all(b.type == "table" for b in blocks):
            contents.append(merge_tables([b.html or b.text for b in blocks]))
        elif len(group) > 1:
            contents.append(
                "".join(render_block(index[key][1], index[key][0], chart_policy) for key in group)
            )
        else:
            contents.append(render_block(blocks[0], index[group[0]][0], chart_policy))
    return "\n\n".join(value for value in contents if value) + "\n"
