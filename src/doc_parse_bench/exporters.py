"""Emit official GT JSON plus benchmark-specific Markdown from the same IR."""

from pathlib import Path

from .context import infer_context, relation_groups, render_document
from .io import fresh_directory, read_json, sha256, write_json
from .markdown import merge_tables, render_page, table_html
from .provenance import conversion_provenance, fingerprint
from .schema import VISUAL_TYPES, Block, Document, load_documents

CATEGORIES = {
    "text": "text_block",
    "formula": "equation_isolated",
    "image": "figure",
    "chart": "figure",
    "seal": "figure",
    "image_caption": "figure_caption",
    "image_footnote": "figure_footnote",
    "footnote": "page_footnote",
    "code": "code_txt",
    "ref_text": "reference",
    "algorithm": "code_algorithm",
}


def _layout(block: Block, page: int, order: int, width: float, height: float, policy: str) -> dict:
    category = CATEGORIES.get(block.type, block.type)
    if block.type == "chart" and policy == "chart-table":
        if not (block.html or block.text):
            raise ValueError(f"GT 图表 {block.id} 缺少人工确认的数据表，不能生成 chart-table GT")
        category = "table"
    bbox = block.bbox
    if bbox is None:
        raise ValueError(f"GT 块缺少坐标：{block.id}")
    x1, y1, x2, y2 = [v * s for v, s in zip(bbox, [width, height, width, height])]
    result = {
        "category_type": category,
        "poly": [x1, y1, x2, y1, x2, y2, x1, y2],
        "anno_id": block.id,
        "order": order,
        "ignore": False,
        "page_id": page,
        "attribute": {},
        "text": block.text,
    }
    if category == "table":
        result["html"] = table_html(block.html or block.text)
        if "<table" not in result["html"].lower():
            raise ValueError(f"GT 表格不是可识别的 HTML/Markdown table：{block.id}")
    elif category == "equation_isolated":
        result["latex"] = block.text
    if block.level is not None:
        result["level"] = block.level
    return result


def _title_relations(doc: Document) -> list[dict]:
    titles = [b for p in doc.pages for b in p.blocks if b.type == "title"]
    title_ids = {b.id for b in titles}
    stack = []
    relations = []
    for block in titles:
        level = block.level or 1
        while stack and stack[-1][0] >= level:
            stack.pop()
        parent_id = block.metadata.get("parent_id")
        if parent_id not in title_ids:
            parent_id = stack[-1][1] if stack else "root"
        if parent_id == block.id:
            raise ValueError(f"标题引用自身：{doc.id}/{block.id}")
        relations.append(
            {"source_anno_id": parent_id, "target_anno_id": block.id, "relation_type": "parent_son"}
        )
        stack.append((level, block.id))
    return relations


def export_gt(source: Path, output: Path, chart_policy: str = "native") -> dict:
    documents = load_documents(source)
    if any(d.metadata.get("origin") != "annotations" for d in documents):
        raise ValueError("export-gt 只接受标注数据")
    source_hashes = {p.name: sha256(p) for p in sorted(source.glob("*.json"))}
    audit_path = source.parent / "audit.json"
    audit = read_json(audit_path) if audit_path.exists() else {}
    # A sidecar from before manual edits must not be claimed as the current input audit.
    linked_audit = bool(audit.get("output_documents_sha256") == source_hashes)
    versions = {d.metadata.get("dataset_version") for d in documents}
    if len(versions) != 1:
        raise ValueError("同一次 GT 导出包含多个 dataset_version，请先整理版本")
    output = fresh_directory(output)
    omnidocbench, mpdocbench, page_manifest, document_manifest = [], [], {}, {}
    for doc in documents:
        layout = []
        order = 1
        for page in doc.pages:
            name = f"{doc.id}__p{page.number:04d}"
            entries = [
                _layout(b, page.number, order + n, page.width, page.height, chart_policy)
                for n, b in enumerate(page.blocks)
            ]
            order += len(entries)
            layout.extend(entries)
            omnidocbench.append(
                {
                    "layout_dets": entries,
                    "page_info": {
                        "page_no": page.number - 1,
                        "width": page.width,
                        "height": page.height,
                        "image_path": name + ".jpg",
                        "page_attribute": {"data_source": "custom", "language": "mixed"},
                    },
                    "extra": {"relation": []},
                }
            )
            page_manifest[name + ".md"] = {"document": doc.id, "page": page.number}
            path = output / "OmniDocBench" / "markdown" / (name + ".md")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(render_page(page, chart_policy), encoding="utf-8")
        relations = [
            {
                "source_anno_id": r["source"],
                "target_anno_id": r["target"],
                "relation_type": "truncated",
            }
            for r in doc.relations
            if r["type"] == "truncated"
        ]
        # MPDocBench groups incrementally. Reading-order edges keep multi-page
        # chains connected (lexical p10-before-p9 ordering creates partial groups).
        reading_order = {b.id: n for n, b in enumerate(b for p in doc.pages for b in p.blocks)}
        relations.sort(
            key=lambda r: (reading_order[r["source_anno_id"]], reading_order[r["target_anno_id"]])
        )
        relations += _title_relations(doc)
        index = {entry["anno_id"]: entry for entry in layout}
        for group in relation_groups(doc):
            if len(group) > 1 and index[group[0]]["category_type"] == "table":
                index[group[0]]["merged_html"] = merge_tables([index[key]["html"] for key in group])
        mpdocbench.append(
            {
                "layout_dets": layout,
                "page_info": {
                    "image_path": doc.id + ".pdf",
                    "images_list": [f"{doc.id}/page_{p.number}.jpg" for p in doc.pages],
                    "width": [p.width for p in doc.pages],
                    "height": [p.height for p in doc.pages],
                    "page_attribute": {"data_source": "custom", "language": "mixed"},
                },
                "extra": {"relation": relations, "continuity": doc.metadata.get("continuity")},
            }
        )
        path = output / "MPDocBench" / "markdown" / f"{doc.id}.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(render_document(doc, chart_policy), encoding="utf-8")
        document_manifest[doc.id + ".md"] = {
            "pages": [p.number for p in doc.pages],
            "continuity": doc.metadata.get("continuity", "unknown"),
        }
    write_json(output / "OmniDocBench" / "gt.json", omnidocbench)
    write_json(output / "MPDocBench" / "gt.json", mpdocbench)
    report = {
        "kind": "ground_truth",
        "chart_policy": chart_policy,
        "omnidocbench_files": page_manifest,
        "mpdocbench_files": document_manifest,
        "documents": len(documents),
        "pages": len(omnidocbench),
        "dataset_version": next(iter(versions)),
        "conversion": conversion_provenance(),
        "source_documents_sha256": source_hashes,
        "source_documents_fingerprint": fingerprint(source_hashes),
        "source_dataset_sha256": audit.get("dataset_sha256") if linked_audit else None,
        "source_audit_sha256": sha256(audit_path) if linked_audit else None,
        "gt_sha256": {
            name: sha256(output / name / "gt.json") for name in ("OmniDocBench", "MPDocBench")
        },
    }
    if linked_audit:
        write_json(output / "source_audit.json", audit)
    write_json(output / "manifest.json", report)
    return report


def export_predictions(
    source: Path, output: Path, chart_policy: str = "native", context_policy: str = "native"
) -> dict:
    documents = load_documents(source)
    if any(d.metadata.get("origin") != "prediction" for d in documents):
        raise ValueError("export-pred 只接受预测数据，禁止将 GT 关系用于预测合并")
    output = fresh_directory(output)
    report = {
        "kind": "prediction",
        "chart_policy": chart_policy,
        "context_policy": context_policy,
        "documents": len(documents),
        "pages": 0,
        "models": sorted({d.metadata["model"] for d in documents}),
        "context_events": {},
        "untranscribed_visuals": 0,
        "incomplete_documents": [],
        "repeated_output_tail_pages": [],
    }
    for doc in documents:
        expected = doc.metadata.get("declared_pages")
        finish = doc.metadata.get("native_meta", {}).get("finish")
        if (expected and expected != len(doc.pages)) or finish == "length":
            report["incomplete_documents"].append(
                {
                    "document": doc.id,
                    "expected_pages": expected,
                    "observed_pages": len(doc.pages),
                    "finish": finish,
                }
            )
        for page in doc.pages:
            if page.metadata.get("repeated_output_tail"):
                report["repeated_output_tail_pages"].append(
                    {"document": doc.id, "page": page.number}
                )
            path = output / "OmniDocBench" / f"{doc.id}__p{page.number:04d}.md"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(render_page(page, chart_policy), encoding="utf-8")
            report["pages"] += 1
            report["untranscribed_visuals"] += sum(
                b.type in VISUAL_TYPES and not b.html for b in page.blocks
            )
        merged = infer_context(doc, context_policy)
        path = output / "MPDocBench" / f"{doc.id}.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(render_document(merged, chart_policy), encoding="utf-8")
        report["context_events"][doc.id] = merged.metadata.get("context_events", [])
        report["context_events"][doc.id].extend(
            {**r, "action": "skip_native_source_gap"}
            for r in merged.metadata.get("blocked_native_source_gap_relations", [])
        )
    write_json(output / "manifest.json", report)
    return report
