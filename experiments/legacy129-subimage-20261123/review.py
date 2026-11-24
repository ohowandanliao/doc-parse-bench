"""Write a local case comparison from the real PDF2Text replay."""

from __future__ import annotations

import argparse
import os
from html import escape
from pathlib import Path
from urllib.parse import quote

from markdown_it import MarkdownIt

from doc_parse_bench.feature_eval import _iou
from doc_parse_bench.io import read_json
from doc_parse_bench.schema import Document

LABELS = {
    "ft-before": "FT 拆前",
    "ft-package": "FT 原包规则",
    "ft-all-split": "FT 强制全拆（对照）",
    "ft-adapted": "FT P2T 前置规则",
    "origin-6docs": "Origin",
}
RULES = {
    "text_majority": "重推后文字或空结果过半",
    "visual_majority": "重推后视觉结果过半",
    "no_text_only": "重推后无纯文字或空结果",
    "split_all_control": "全拆对照",
    "keep_multirow": "子框不构成单排或单列",
    "keep_shared_caption": "共用原页图注",
    "probe_chart_panels": "共图注下探测独立图表",
    "split_strip": "子框成排且无共图注",
    "keep_budget": "超出裁图预算",
}
STYLE = """
body { max-width: 1380px; margin: 24px auto; padding: 0 16px; font: 15px/1.5 system-ui; color: #242925; }
article { border-top: 1px solid #bbb; padding: 12px 0; }
h1 { font-size: 24px; } h2 { font-size: 18px; } h3 { font-size: 15px; }
a { color: #155e67; } .source { display: flex; flex-wrap: wrap; gap: 14px; }
.grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(230px, 100%), 1fr)); gap: 14px; }
img { max-height: 330px; max-width: 100%; } table { border-collapse: collapse; }
th, td { border: 1px solid #bbb; padding: 3px 7px; }
pre, code, td { white-space: pre-wrap; overflow-wrap: anywhere; }
section { min-width: 0; } details { margin: 6px 0; }
.block { border-top: 1px solid #ddd; padding-top: 8px; }
@media (max-width: 800px) { .grid { grid-template-columns: 1fr; } }
"""


def related(box: list[float], regions: list[list[float]]) -> bool:
    return any(_iou(box, region) >= 0.05 for region in regions)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pack", type=Path, required=True)
    parser.add_argument("--gt", type=Path, required=True)
    parser.add_argument("--replay", type=Path, required=True)
    args = parser.parse_args()
    pack, replay = args.pack / "review", args.replay
    labels = {key: label for key, label in LABELS.items() if (replay / key).is_dir()}
    comparison_path = replay / "split-comparison.json"
    comparison = read_json(comparison_path) if comparison_path.is_file() else {}
    records = {item["document_id"]: item for item in read_json(args.gt / "records.json")["records"]}
    markdown = MarkdownIt("commonmark", {"html": False}).enable("table")
    sections = []

    def link(path: Path) -> str:
        if not path.is_file():
            raise FileNotFoundError(path)
        return quote(os.path.relpath(path, replay))

    for filename, source in read_json(pack / "expansion.json")["documents"].items():
        document_id = source["gt_document_id"]
        outputs = {key: Document.load(replay / key / f"chart/documents/{document_id}.json") for key in labels}
        chart_markdown = {key: link(replay / key / f"chart/markdown/{document_id}.md") for key in labels}
        physical_pages = sorted({parent["page"] for parent in source["composites"]})
        for page_number in physical_pages:
            parents = [parent for parent in source["composites"] if parent["page"] == page_number]
            original = next(page for page in outputs["ft-before"].pages if page.number == page_number)
            scale = (original.width, original.height, original.width, original.height)
            regions = [
                [coord / dimension for coord, dimension in zip(parent["original_block"]["bbox"], scale, strict=True)]
                for parent in parents
            ]
            overlay = link(pack / f"overlays/{filename}__p{page_number:04d}.png")
            crops = sorted((pack / "crops/full").glob(f"{filename}__p{page_number:04d}__*.jpg"))
            crop_links = " · ".join(f'<a href="{link(crop)}">{escape(crop.stem.rsplit("__", 2)[-2])}/{crop.stem[-3:]}</a>'
                                    for crop in crops)
            gt_record = records[document_id]["new_gt"]
            truth = [block for key in ("image_blocks", "chart_blocks") for block in gt_record[key]
                     if block["page"] == page_number and related(block["bbox"], regions)]
            truth_text = "\n".join(f"{block['type']} {block['id']} {block['bbox']}" for block in truth)
            columns = []
            for key, label in labels.items():
                page = next(page for page in outputs[key].pages if page.number == page_number)
                blocks = [block for block in page.blocks if block.type in ("image", "chart", "seal")
                          and block.bbox and related(block.bbox, regions)]
                rendered = []
                for block in blocks:
                    spans = block.metadata.get("generated_spans", [])
                    payload = block.html or "\n\n".join(str(span.get("content") or span.get("text") or "") for span in spans)
                    caption = "\n".join(node["text"] for node in block.metadata["nested_blocks"]
                                        if node["type"].endswith(("_caption", "_footnote")) and node["text"])
                    subtype = block.metadata.get("sub_type") or "无标签"
                    evidence = ", ".join(sorted({span["subimage_source"] for span in spans if "subimage_source" in span}))
                    coords = [round(value, 4) for value in block.bbox]
                    kind = f"{block.id} · {block.type} / {subtype} · {coords} {evidence}"
                    content = markdown.render(payload) if payload.strip() else "<p>【空输出】</p>"
                    if payload.strip():
                        content += f'<details><summary>输出原文</summary><pre>{escape(payload)}</pre></details>'
                    rendered.append(f'<div class="block"><code>{escape(kind)}</code>{content}'
                                    f'<pre>{escape(caption)}</pre></div>')
                decisions = comparison.get(key, {}).get("groups", {}).get("chart", {}).get("documents", {})
                decision_text = "\n".join(
                    f'父块 {entry["parent_index"]}：{"拆" if entry["split"] else "保留"}，'
                    f'{RULES.get(entry["rule"], entry["rule"])}，{entry["requests"]} 张裁图'
                    for entry in decisions.get(document_id, []) if entry["page"] == page_number
                )
                columns.append(f'<section><h3>{label}</h3><a href="{chart_markdown[key]}">完整成品 Markdown</a>'
                               f'<pre>{escape(decision_text)}</pre>'
                               f'{"".join(rendered) if rendered else "<p>【无输出块】</p>"}</section>')
            sections.append(
                f'<article><h2>{escape(filename)}.pdf · 物理第 {page_number} 页</h2>'
                f'<div class="source"><a href="{overlay}"><img src="{overlay}" alt="PDF 原页与框"></a>'
                f'<div><h3>当前 v3 GT</h3><pre>{escape(truth_text)}</pre><p>裁图：{crop_links}</p></div></div>'
                f'<div class="grid">{"".join(columns)}</div></article>'
            )

    html = f'''<!doctype html><html lang="zh-CN"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>129 子图复评</title>
<style>{STYLE}</style><main><h1>129 子图复评 · 受影响页</h1>
<p>同一份修订 v3 GT；图片与图表均开启。裁图数来自离线回放，不是线上延迟。Origin 仅作对照。</p>
{"".join(sections)}</main></html>'''
    (replay / "review.html").write_text(html, encoding="utf-8")


if __name__ == "__main__":
    main()
