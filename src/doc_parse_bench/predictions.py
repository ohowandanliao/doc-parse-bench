"""Model output adapters: exported pages, MinerU content lists, native Unlimited OCR 2 and Markdown."""

import re
from pathlib import Path

from .io import fresh_directory, read_json, sha256, write_json
from .markdown import parse_markdown, table_html
from .schema import Block, Document, Page

MODELS = ("MinerU", "NaviDC-OCR", "OvisOCR2", "Unlimited-OCR-2", "Markdown")
TYPE_ALIASES = {
    "equation": "formula",
    "equation_isolated": "formula",
    "figure": "image",
    "picture": "image",
    "image_block": "image",
    "text_block": "text",
    "ref_text": "text",
    "cross_ref_text": "text",
    "append_ref_text": "text",
    "table_footnote": "footnote",
    "page_footnote": "footnote",
}


def normalize_bbox(value, scale: float = 1) -> list[float] | None:
    if value is None:
        return None
    if isinstance(value, str):
        value = [float(x) for x in re.findall(r"-?\d+(?:\.\d+)?", value)]
    if len(value) != 4:
        raise ValueError(f"bbox 必须有四个坐标：{value}")
    return [max(0.0, min(1.0, float(x) / scale)) for x in value]


def _convert_block(raw: dict, page: int, index: int, model: str) -> Block:
    kind = raw.get("type", raw.get("label", "text"))
    if kind.startswith(("cross_", "append_")):
        kind = kind.split("_", 1)[1]
    kind = TYPE_ALIASES.get(kind, kind)
    text = raw.get("content", raw.get("text", "")) or ""
    html = raw.get("html", raw.get("table_body", "")) or ""
    if isinstance(text, dict):
        raise ValueError("结构化 content 尚未支持，请先导出为 pages/blocks 格式")
    level = raw.get("level", raw.get("text_level"))
    bbox = raw.get("bbox")
    scale = (
        1000
        if model == "Unlimited-OCR-2" or (bbox and not isinstance(bbox, str) and max(bbox) > 1)
        else 1
    )
    return Block(
        raw.get("block_id", f"{model}.p{page}.{index:04d}"),
        kind,
        str(text),
        table_html(html or text) if kind == "table" else html,
        normalize_bbox(bbox, scale),
        level,
        dict(raw),
    )


def parse_unlimited_ocr2(raw: str, doc_id: str) -> Document:
    """Parse LEVEL-first/bbox-first blocks without flattening page or chain markers."""
    from .unlimited_ocr2_parser import parse_pages

    pages = []
    open_chains: dict[str, Block] = {}
    relations = []
    for number, parsed in enumerate(parse_pages(raw), 1):
        blocks = []
        for index, item in enumerate(parsed):
            if item["type"] == "__raw__":
                blocks.extend(
                    parse_markdown(item["content"], number, f"unlimited-ocr-2-raw-{index}")
                )
                continue
            block = _convert_block(item, number, index, "Unlimited-OCR-2")
            label = item["type"]
            base = block.type
            if label.startswith("append_") and base in open_chains:
                relations.append(
                    {
                        "type": "truncated",
                        "source": open_chains[base].id,
                        "target": block.id,
                        "method": "native_append",
                    }
                )
                open_chains[base] = block
            elif label.startswith("cross_") or base == "table":
                open_chains[base] = block
            if item.get("merge_prev") and blocks and blocks[-1].type == base:
                relations.append(
                    {
                        "type": "truncated",
                        "source": blocks[-1].id,
                        "target": block.id,
                        "method": "native_merge",
                    }
                )
            blocks.append(block)
        pages.append(Page(number, blocks))
    return Document(doc_id, pages, relations)


def import_predictions(
    source: Path, output: Path, model: str, document_map: Path | None = None
) -> dict:
    if model not in MODELS:
        raise ValueError(f"未知模型适配器：{model}")
    if source.is_file():
        files = [source]
    else:
        # Never recursively pick up two representations of the same document.
        files = (
            sorted(source.glob("*.json"))
            or sorted(source.glob("*.md"))
            or sorted(source.glob("*.txt"))
        )
    if not files:
        raise ValueError(f"没有模型输出：{source}")
    mapping = read_json(document_map) if document_map else {}
    output = fresh_directory(output)
    report = {
        "model": model,
        "documents": 0,
        "pages": 0,
        "sources": [],
        "issues": [],
        "repeated_output_tails": [],
    }
    seen = set()
    for path in files:
        doc_id = path.stem.removesuffix("_content_list")
        obj = read_json(path) if path.suffix == ".json" else None
        if isinstance(obj, dict):
            doc_id = obj.get("stem", doc_id)
        if doc_id in seen:
            raise ValueError(f"重复的文档输出：{doc_id}")
        seen.add(doc_id)
        if model == "Unlimited-OCR-2" and isinstance(obj, dict) and isinstance(obj.get("raw"), str):
            doc = parse_unlimited_ocr2(obj["raw"], doc_id)
            expected = obj.get("n_pages", len(obj.get("pages", [])))
            if expected and len(doc.pages) != expected:
                report["issues"].append(
                    {
                        "document": doc_id,
                        "issue": "raw_page_count_mismatch",
                        "expected": expected,
                        "actual": len(doc.pages),
                    }
                )
        elif obj is None:
            text = path.read_text(encoding="utf-8")
            if model == "Unlimited-OCR-2" and "<PAGE>" in text:
                doc = parse_unlimited_ocr2(text, doc_id)
            else:
                # Multi-page plain Markdown needs explicit <PAGE> or form-feed boundaries.
                texts = re.split(r"<PAGE>|\f", text)
                if texts and not texts[0].strip() and "<PAGE>" in text:
                    texts = texts[1:]
                doc = Document(
                    doc_id, [Page(n, parse_markdown(t, n)) for n, t in enumerate(texts, 1)]
                )
        else:
            if isinstance(obj, list):
                by_page: dict[int, list[dict]] = {}
                for block in obj:
                    by_page.setdefault(int(block.get("page_idx", 0)) + 1, []).append(block)
                input_pages = [
                    {"page": p, "blocks": by_page.get(p, [])}
                    for p in range(1, max(by_page, default=1) + 1)
                ]
            else:
                input_pages = obj["pages"]
            pages = []
            for item in sorted(input_pages, key=lambda p: p["page"]):
                number = int(item["page"])
                if item.get("blocks") is None:
                    blocks = parse_markdown(item.get("md", ""), number)
                else:
                    raw_blocks = item["blocks"]
                    blocks = [
                        _convert_block(b, number, n, model)
                        for n, b in enumerate(raw_blocks)
                        if not (b.get("type") == "list" and not b.get("content"))
                    ]
                    # Some exporters omit container content but retain all child text blocks.
                pages.append(Page(number, blocks))
            doc = Document(doc_id, pages)
        doc.metadata.update(
            {
                "origin": "prediction",
                "model": model,
                "source": str(path),
                "source_sha256": sha256(path),
                "continuity": "unknown",
                "native_meta": obj.get("meta", {}) if isinstance(obj, dict) else {},
                "declared_pages": obj.get("n_pages") if isinstance(obj, dict) else None,
                **mapping.get(doc_id, {}),
            }
        )
        original = doc.metadata.get("original_page_numbers")
        if original is not None:
            if len(set(original)) != len(original) or any(
                p.number > len(original) for p in doc.pages
            ):
                raise ValueError(f"{doc_id}: original_page_numbers 无法覆盖已返回的页码")
            for page in doc.pages:
                page.metadata["original_page"] = original[page.number - 1]
        for page in doc.pages:
            for block in page.blocks:
                if block.type == "title" and block.level is None:
                    block.level = 1
                    block.metadata["level_source"] = "default_missing_native_level"
        if model in {"MinerU", "NaviDC-OCR"}:
            _native_merge_prev(doc)
        for page in doc.pages:
            tail = [b.text.strip() for b in page.blocks[-100:] if b.text.strip()]
            if len(tail) >= 20 and len(set(tail[-20:])) == 1:
                report["repeated_output_tails"].append(
                    {"document": doc.id, "page": page.number, "repeated_text": tail[-1][:100]}
                )
                page.metadata["repeated_output_tail"] = True
        doc.dump(output / "documents" / f"{doc.id}.json")
        report["documents"] += 1
        report["pages"] += len(doc.pages)
        report["sources"].append({"path": str(path), "sha256": sha256(path)})
    write_json(output / "audit.json", report)
    return report


def _native_merge_prev(doc: Document) -> None:
    """MinerU's merge_prev applies to text flow, possibly around intervening figures."""
    previous_text = None
    for page in doc.pages:
        for block in page.blocks:
            if block.type != "text":
                if block.type in {"title", "table"}:
                    previous_text = None
                continue
            if block.metadata.get("merge_prev") and previous_text is not None:
                prior_page, prior = previous_text
                if page.number - prior_page <= 1:
                    doc.relations.append(
                        {
                            "type": "truncated",
                            "source": prior.id,
                            "target": block.id,
                            "method": "native_merge_prev",
                        }
                    )
            previous_text = (page.number, block)
