"""Prediction-only conversion between benchmark blocks and composition source fragments."""

import re
from dataclasses import asdict

from .markdown import render_block
from .schema import VISUAL_TYPES, Block, Document


def composition_input(doc: Document) -> dict:
    """Expand native annotations before the composer and retain each original block."""
    pages = []
    for page in doc.pages:
        blocks = []
        for block in page.blocks:
            raw = {
                "type": "image" if block.type in VISUAL_TYPES else block.type,
                "content": block.text,
                "bench_block": asdict(block),
            }
            if block.bbox is not None:
                raw["bbox"] = block.bbox
            if block.level is not None:
                raw["level"] = block.level
            if block.type == "table":
                raw["table_body"] = block.html or block.text
            for key in ("merge_prev", "continues_prev"):
                if key in block.metadata:
                    raw[key] = block.metadata[key]
            if raw.get("continues_prev") and "merge_prev" not in raw:
                raw["merge_prev"] = True
            blocks.append(raw)
        pages.append({"page": page.number, "blocks": blocks})
    return {"pages": pages, "prediction_document": doc.id, "n_pages": len(pages)}


def render_composition(ir: dict, render_table, *, drop_furniture=True) -> tuple[dict, str, dict]:
    """Project source fragments to their pages; keep full logical merges in the document.

    A cross-page logical table is scored as the original fragment on each source
    page and as the composed table for MPDocBench. No GT or GT links are consumed.
    """
    fragments = {f["id"]: f for f in ir["fragments"]}
    elements = {e["id"]: e for e in ir["elements"]}
    by_page = {p["page"]: [] for p in ir["pages"]}
    document, hidden, cross_page = [], [], []

    def visual(fragment):
        raw = fragment["content"]["mineru_block"]["bench_block"]
        return render_block(Block(**raw), fragment["page"])

    def render(element, sources):
        content = element["content"]
        if element["type"] == "title":
            text = re.sub(r"\s+", " ", content.get("text", "")).strip()
            return "#" * (element.get("heading_level") or 1) + " " + text if text else ""
        if element["type"] == "table":
            return render_table(content)
        if element["type"] == "formula":
            return "$$\n" + content.get("latex", "") + "\n$$"
        if element["type"] in {"figure", "figure_group"}:
            # The composer merges duplicate boxes into one logical figure.
            # Its exporter uses the first figure's pixels; keep that same choice.
            return visual(sources[0])
        return content.get("text", "")

    for key in ir["reading_order"]:
        element = elements[key]
        sources = [fragments[f] for f in element["fragments"]]
        if drop_furniture and element.get("role") in {"header", "footer", "page_number"}:
            hidden.extend(f["id"] for f in sources)
            continue
        text = render(element, sources)
        if text.strip():
            document.append(text)
        pages = {f["page"] for f in sources}
        if len(pages) == 1:
            if text.strip():
                by_page[sources[0]["page"]].append(text)
            continue
        cross_page.append({"element": key, "type": element["type"], "pages": sorted(pages)})
        for source in sources:
            if element["type"] in {"figure", "figure_group"}:
                value = visual(source)
            elif element["type"] == "title":
                value = source["content"].get("text", source["raw_markdown"])
                value = re.sub(r"^#{1,6}\s+", "", value).strip()
                value = "#" * (element.get("heading_level") or 1) + " " + value
            else:
                value = source["raw_markdown"]
            if value.strip():
                by_page[source["page"]].append(value)
    pages = {number: "\n\n".join(parts) + "\n" for number, parts in by_page.items()}
    return (
        pages,
        "\n\n".join(document) + "\n",
        {
            "projection": "source-page fragments; whole logical elements for document evaluation",
            "hidden_furniture_fragments": hidden,
            "cross_page_elements": cross_page,
            "source_fragments": len(fragments),
            "logical_elements": len(elements),
            "ground_truth_used": False,
        },
    )
