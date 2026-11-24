"""Explain visual replay differences by GT block and score paired image controls."""

from __future__ import annotations

import argparse
import re
from collections import Counter
from pathlib import Path

from doc_parse_bench.feature_eval import _iou
from doc_parse_bench.feature_matrix import _chart_payload, _generated, _match
from doc_parse_bench.feature_rubric import CONFIG, EVIDENCE_SCHEMA, _text, evaluate_feature_rubric
from doc_parse_bench.io import fresh_directory, read_json, sha256, write_json
from doc_parse_bench.schema import Block, Document

IMAGE_CONTROLS = {
    "bc_022:candidate.block.p2.0002",
    "bc_059:candidate.block.p1.0014",
    "bc_065:candidate.block.p1.0017",
    "bc_065:candidate.block.p1.0018",
    "bc_078:candidate.block.p1.0001",
    "bc_078:candidate.block.p1.0002",
}


def load_group(root: Path, group: str, document: str) -> Document:
    result = Document.load(root / group / "documents" / f"{document}.json")
    if result.id != document:
        raise ValueError(f"Document mismatch: {root}/{group}/{document}")
    return result


def output_text(block: Block) -> str:
    return block.html or "\n\n".join(
        str(span.get("content") or span.get("text") or "")
        for span in block.metadata.get("generated_spans", [])
    )


def visual_blocks(document: Document, group: str) -> list[tuple[int, Block]]:
    return [
        (page.number, block)
        for page in document.pages
        for block in page.blocks
        if (
            block.type == "chart"
            if group == "chart"
            else block.type in ("image", "seal") and block.metadata.get("raw_type") != "chart"
        )
    ]


def diagnostic(reference: dict, match: Block | None, all_visual: list[tuple[int, Block]]) -> dict:
    def evidence(block: Block) -> dict:
        return {
            "block_id": block.id,
            "bbox": block.bbox,
            "iou": _iou(reference["bbox"], block.bbox),
            "type": block.type,
            "sub_type": block.metadata.get("sub_type"),
            "content": output_text(block),
            "content_sources": sorted(
                {
                    span["subimage_source"]
                    for span in block.metadata.get("generated_spans", [])
                    if "subimage_source" in span
                }
            ),
        }

    if match:
        contentful = bool(_chart_payload(match) if match.type == "chart" else _generated(match))
        return {"status": "nonempty" if contentful else "empty", **evidence(match)}
    nearby = [
        (float(_iou(reference["bbox"], block.bbox)), block)
        for page, block in all_visual
        if page == reference["page"]
    ]
    nearby.sort(key=lambda item: item[0], reverse=True)
    return {
        "status": "unmatched",
        "nearby": [evidence(block) for overlap, block in nearby[:2] if overlap >= 0.2],
    }


def compare(records: list[dict], ft: Path, origin: Path, output: Path) -> None:
    results = []
    for record in records:
        doc = record["document_id"]
        for group, key in (("image", "image_blocks"), ("chart", "chart_blocks")):
            references = record["new_gt"][key]
            if not references:
                continue
            models = {}
            for name, root in (("ft", ft), ("origin", origin)):
                document = load_group(root, group, doc)
                if group == "image":
                    document_for_types = load_group(root, "chart", doc)
                else:
                    document_for_types = document
                all_visual = visual_blocks(document_for_types, "image") + visual_blocks(
                    document_for_types, "chart"
                )
                matched = {
                    ref["id"]: block
                    for ref, block in _match(
                        references, visual_blocks(document, group), visual=True
                    )
                }
                models[name] = {
                    ref["id"]: diagnostic(ref, matched.get(ref["id"]), all_visual)
                    for ref in references
                }
            results.extend(
                {
                    "document": doc,
                    "pdf": f"{record['source_name']}.pdf",
                    "page": ref["page"],
                    "gt_id": ref["id"],
                    "gt_type": ref["type"],
                    "bbox": ref["bbox"],
                    **{name: data[ref["id"]] for name, data in models.items()},
                }
                for ref in references
            )
    write_json(output / "visual-blocks.json", results)
    lines = [
        "# FT 与 Origin：逐块差距",
        "",
        "当前 v3 GT；同页一对一位置匹配。非空不代表内容正确。",
        "",
    ]
    for feature in ("image", "seal", "chart"):
        counts = Counter(
            (row["ft"]["status"], row["origin"]["status"])
            for row in results
            if row["gt_type"] == feature
        )
        lines.extend([f"## {feature}", "", "| FT | Origin | 标注块 |", "| --- | --- | ---: |"])
        lines.extend(
            f"| {left} | {right} | {count} |" for (left, right), count in sorted(counts.items())
        )
        lines.append("")
    lines.extend(
        [
            "## 状态不同的块",
            "",
            "| PDF／物理页 | v3 ID | FT | Origin |",
            "| --- | --- | --- | --- |",
        ]
    )
    for row in results:
        ft_result, origin_result = row["ft"], row["origin"]
        if ft_result["status"] == origin_result["status"]:
            continue
        labels = []
        for outcome in (ft_result, origin_result):
            best = outcome if "block_id" in outcome else next(iter(outcome["nearby"]), {})
            block_name = (
                f" `{best['block_id']}`（{best['type']}，IoU {best['iou']:.2f}）" if best else ""
            )
            labels.append(outcome["status"] + block_name)
        lines.append(
            f"| {row['pdf']}／{row['page']} | `{row['gt_id']}` | {labels[0]} | {labels[1]} |"
        )
    (output / "visual-gaps.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def image_observation(case: dict, document: Document, rendered: str) -> dict:
    candidates = [
        block
        for page, block in visual_blocks(document, "image")
        if page == case["page"] and _iou(case["bbox"], block.bbox) >= 0.2
    ]
    distinct = [block for block in candidates if _iou(case["bbox"], block.bbox) >= 0.9]
    if not distinct:
        if any(block.metadata.get("sub_type") or _generated(block) for block in candidates):
            return {"reason": "Ambiguous source attribution"}
        return {"sub_type": None, "fields": [], "reason": "No attributable subtype or content"}
    if len(distinct) != 1:
        return {"reason": "Multiple candidate blocks"}
    block = distinct[0]
    content = output_text(block)
    result = {
        "sub_type": block.metadata.get("sub_type"),
        "block_id": block.id,
        "raw_content": content,
    }
    if result["sub_type"]:
        result["subtype_id"] = block.id
    if case["document_id"] == "bc_022":
        if not content.strip():
            result["fields"] = []
        return result
    if not case["fields"]:
        if "no text or symbols visible" not in content.lower() or not re.search(
            r"!\[.*?\]\(data:image/", rendered
        ):
            raise ValueError(f"No-text or rendered asset evidence needs review: {case['id']}")
        return result | {"fields": [], "image_available": True}
    if case["document_id"] == "bc_059":
        if _text(content) != _text("音量调节"):
            raise ValueError(f"Unexpected dial-label evidence: {case['id']}")
        return result | {
            "fields": [{"id": f"{block.id}:1", "key": "dial-label", "text": content.strip()}]
        }

    lines = [
        (index, label.strip())
        for index, label in enumerate(content.splitlines(), start=1)
        if label.strip()
    ]
    labels = {_text(field["text"]): field["key"] for field in case["fields"]}
    observed = []
    for index, label in lines:
        if label.startswith(("(a)", "(b)", "图 B")):
            continue
        key = labels.get(_text(label))
        if key is None and label.startswith("保护线("):
            key = "protective-bar"
        observed.append(
            {"id": f"{block.id}:{index}", "key": key or "unmatched-label", "text": label}
        )
    return result | {"fields": observed}


def image_controls(gt: Path, replay: Path, output: Path) -> None:
    pilot = read_json(gt)
    if pilot["split"] != "calibration":
        raise ValueError("Image controls are calibration only")
    cases = [case for case in pilot["cases"] if case["id"] in IMAGE_CONTROLS]
    if {case["id"] for case in cases} != IMAGE_CONTROLS:
        raise ValueError("Image control roster mismatch")
    gt_path = output / "image-controls-gt.json"
    write_json(gt_path, pilot | {"cases": cases, "base_rubric_gt_sha256": sha256(gt)})
    for model in ("ft-before", "ft-adapted", "origin-6docs"):
        observations, sources = {}, {}
        for case in cases:
            doc = case["document_id"]
            root = replay / model
            path = root / "image" / "markdown" / f"{doc}.md"
            sources[doc] = {
                "rendered_sha256": sha256(path),
                "ir_sha256": sha256(root / "image" / "documents" / f"{doc}.json"),
            }
            observations[case["id"]] = image_observation(
                case, load_group(root, "image", doc), path.read_text(encoding="utf-8")
            )
        evidence_path = output / f"{model}-images.json"
        write_json(
            evidence_path,
            {
                "schema_version": EVIDENCE_SCHEMA,
                "gt_sha256": sha256(gt_path),
                "model": model,
                "config": CONFIG,
                "stage": "replay",
                "relevel_applied": False,
                "cases": observations,
                "sources": sources,
            },
        )
        evaluate_feature_rubric(gt_path, evidence_path, output / f"{model}-images")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gt", type=Path, required=True)
    parser.add_argument("--p2t-replay", type=Path, required=True)
    parser.add_argument("--legacy-origin", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = fresh_directory(args.output)
    compare(
        read_json(args.gt / "records.json")["records"],
        args.p2t_replay / "ft-adapted",
        args.legacy_origin,
        output,
    )
    image_controls(args.gt / "rubric-pilot-gt.json", args.p2t_replay, output)


if __name__ == "__main__":
    main()
