"""Versioned heading trees, independent of the downstream chunker and retriever."""

import re
import unicodedata
from dataclasses import dataclass, field
from html import unescape

import Levenshtein
from bs4 import BeautifulSoup
from markdown_it import MarkdownIt

TITLE_TREE_VERSION = "TitleTree-v2/commonmark-math-nfc-1"


@dataclass
class HeadingNode:
    text: str = ""
    children: list["HeadingNode"] = field(default_factory=list)
    anchor: bool = False


def normalize_heading(text: str) -> str:
    """Visible inline text; retain case, numbers and meaningful symbols."""
    rendered = MarkdownIt("commonmark").renderInline(text)
    if "<" not in rendered:
        return re.sub(r"\s+", " ", unicodedata.normalize("NFC", unescape(rendered))).strip()
    soup = BeautifulSoup(rendered, "html.parser")
    for image in soup.find_all("img"):
        image.replace_with(image.get("alt", ""))
    for br in soup.find_all("br"):
        br.replace_with(" ")
    return re.sub(r"\s+", " ", unicodedata.normalize("NFC", soup.get_text())).strip()


def extract_headings(markdown: str) -> list[tuple[int, str]]:
    """CommonMark ATX/Setext, excluding code, HTML and explicit display-math blocks."""
    parser = MarkdownIt("commonmark")
    lines = markdown.splitlines(keepends=True)
    initial_tokens = parser.parse(markdown)
    protected = set()
    for token in initial_tokens:
        if token.type in {"fence", "code_block", "html_block"} and token.map:
            protected.update(range(*token.map))
    # CommonMark has no display math. In particular '='/'-' in a LaTeX block
    # otherwise create spurious Setext headings. Preserve line positions.
    pattern = re.compile(r"(?m)^ {0,3}(?:\$\$[\s\S]*?\$\$|\\\[[\s\S]*?\\\])")
    math_source = "".join(
        re.sub(r"[^\r\n]", " ", line) if index in protected else line
        for index, line in enumerate(lines)
    )
    for match in pattern.finditer(math_source):
        first = markdown.count("\n", 0, match.start())
        last = markdown.count("\n", 0, match.end())
        if not any(line in protected for line in range(first, last + 1)):
            for index in range(first, min(last + 1, len(lines))):
                lines[index] = "\n" if lines[index].endswith("\n") else ""
    tokens = parser.parse("".join(lines))
    return [
        (int(token.tag[1:]), normalize_heading(tokens[index + 1].content))
        for index, token in enumerate(tokens)
        if token.type == "heading_open"
    ]


def markdown_heading_tree(markdown: str) -> tuple[HeadingNode, int]:
    root = HeadingNode(anchor=True)
    stack = [(0, root)]
    headings = extract_headings(markdown)
    for level, text in headings:
        while stack[-1][0] >= level:
            stack.pop()
        node = HeadingNode(text)
        stack[-1][1].children.append(node)
        stack.append((level, node))
    return root, len(headings)


def gt_heading_tree(sample: dict) -> tuple[HeadingNode, int]:
    """Use annotated parents and numeric reading order, never lexical annotation IDs."""
    root = HeadingNode(anchor=True)
    items = [item for item in sample["layout_dets"] if item["category_type"] == "title"]
    items.sort(key=lambda item: item["order"])
    nodes = {}
    for item in items:
        key = item["anno_id"]
        if key == "root" or key in nodes:
            raise ValueError(f"重复或保留的 GT 标题 ID：{key}")
        # Match the GT renderer's removal of an existing ATX marker.
        label = re.sub(r"^#{1,6}\s+", "", item["text"])
        nodes[key] = HeadingNode(normalize_heading(re.sub(r"\s+", " ", label)))
        if not nodes[key].text:
            raise ValueError(f"GT 标题文字为空：{key}")
    parents = {}
    for relation in sample.get("extra", {}).get("relation", []):
        if relation["relation_type"] != "parent_son":
            continue
        parent, child = relation["source_anno_id"], relation["target_anno_id"]
        if child not in nodes or (parent != "root" and parent not in nodes):
            raise ValueError(f"GT 标题关系指向未知节点：{parent}/{child}")
        if child in parents:
            raise ValueError(f"GT 标题存在多个父节点：{child}")
        parents[child] = parent
    if set(parents) != set(nodes):
        raise ValueError("GT 标题缺少明确的父子关系")
    for item in items:
        key = item["anno_id"]
        parent = root if parents[key] == "root" else nodes[parents[key]]
        parent.children.append(nodes[key])
    visited, pending = set(), list(root.children)
    while pending:
        node = pending.pop()
        if id(node) in visited:
            raise ValueError("GT 标题关系包含环或重复节点")
        visited.add(id(node))
        pending.extend(node.children)
    if len(visited) != len(nodes):
        raise ValueError("GT 标题关系包含不可达节点或环")
    return root, len(nodes)


def compare_heading_trees(gt: tuple[HeadingNode, int], pred: tuple[HeadingNode, int]) -> dict:
    from apted import APTED, Config

    gold_root, gold_count = gt
    pred_root, pred_count = pred
    # Deleting all real nodes then inserting all real nodes is an upper bound.
    # This finite cost strictly forbids an optimal mapping from editing the anchor.
    forbidden = gold_count + pred_count + 1

    class HeadingCosts(Config):
        def delete(self, node):
            return forbidden if node.anchor else 1

        def insert(self, node):
            return forbidden if node.anchor else 1

        def rename(self, left, right):
            if left.anchor or right.anchor:
                return 0 if left.anchor and right.anchor else forbidden
            size = max(len(left.text), len(right.text))
            return Levenshtein.distance(left.text, right.text) / size if size else 0

    distance = float(APTED(gold_root, pred_root, HeadingCosts()).compute_edit_distance())
    maximum = max(gold_count, pred_count)
    raw = 1 - distance / maximum if maximum else 1.0
    return {
        "metric_version": TITLE_TREE_VERSION,
        "gt_headings": gold_count,
        "pred_headings": pred_count,
        "tree_distance": distance,
        "raw_score": raw,
        "title_tree_v2": max(0.0, raw),
        "clipped": raw < 0,
        "head_teds_same_input": 1 - distance / (maximum + 1),
    }


def compute_title_tree_score(gt_markdown: str, pred_markdown: str) -> dict:
    return compare_heading_trees(
        markdown_heading_tree(gt_markdown), markdown_heading_tree(pred_markdown)
    )
