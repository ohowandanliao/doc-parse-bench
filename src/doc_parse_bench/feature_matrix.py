"""Offline replay and paired scoring for the 129-document feature GT."""

from collections import Counter
from pathlib import Path

from .feature_eval import (
    FEATURE_GT_VERSION,
    _rate,
    _records_from_gt,
    _select_feature_records,
    _similarity,
)
from .io import fresh_directory, read_json, safe_name, sha256, write_json
from .mineru_middle import apply_pdf2text_filters, extract_pdf_info, pdf_info_to_document
from .schema import MARGINAL_TYPES, Block, Document

FEATURES = ("appendix", "header_footer", "image", "chart")
REPLAY_SCHEMA = "doc-parse-bench.feature-replay.v1"
RAW_SCHEMA = "doc-parse-bench.mineru-middle-json-run.v1"
BASE_CONFIG = dict.fromkeys(
    ("keep_appendix", "keep_header_footer", "image_analysis", "chart_analysis"), False
)
IMAGE_CONFIG = BASE_CONFIG | {"image_analysis": True}
GROUPS = {
    "off": ("A", BASE_CONFIG),
    "appendix": ("A", BASE_CONFIG | {"keep_appendix": True}),
    "header_footer": ("A", BASE_CONFIG | {"keep_header_footer": True}),
    "image": ("B", IMAGE_CONFIG),
    "chart": ("B", IMAGE_CONFIG | {"chart_analysis": True}),
    # Match image on/off on the same recognition output.
    "controls/image_off": ("B", BASE_CONFIG),
}
PAIRS = {
    "appendix": ("appendix", "off"),
    "header_footer": ("header_footer", "off"),
    "image": ("image", "controls/image_off"),
    "chart": ("chart", "image"),
}


def _ground_truth(gt: Path) -> tuple[dict, list[dict], dict]:
    manifest, records = _records_from_gt(gt)
    if manifest.get("gt_version") != FEATURE_GT_VERSION:
        raise ValueError(f"四功能矩阵要求 {FEATURE_GT_VERSION}：{gt}")
    return (
        manifest,
        records,
        {name: sha256(gt / name) for name in ("manifest.json", "records.json")},
    )


def _select_groups(manifest: dict, records: list[dict], subset: Path | None) -> dict:
    groups = {}
    for name in ("union", *FEATURES):
        selected, _ = _select_feature_records(manifest, records, subset, name if subset else None)
        groups[name] = [safe_name(record["document_id"]) for record in selected]
    expected = set().union(*(set(groups[name]) for name in FEATURES))
    if set(groups["union"]) != expected:
        raise ValueError("union 必须正好是 appendix、header_footer、image、chart 四个子集的并集")
    return groups


def _raw_manifest(directory: Path, enabled: bool, model: str) -> dict | None:
    path = directory / "manifest.json"
    if not path.is_file():
        return None  # Also accept native JSON collected manually.
    manifest = read_json(path)
    if (
        manifest.get("schema_version") != RAW_SCHEMA
        or manifest.get("image_analysis") is not enabled
    ):
        raise ValueError(f"采集清单的模型、格式或 image_analysis 与回放配置不符：{path}")
    if manifest.get("model") and manifest["model"] != model:
        raise ValueError(f"采集清单的模型与回放配置不符：{path}")
    return manifest


def _raw_path(directory: Path, record: dict) -> Path:
    names = {safe_name(record[key]) for key in ("document_id", "source_name")}
    paths = [
        directory / f"{name}{suffix}" for name in names for suffix in (".json", ".middle_json.json")
    ]
    found = [path for path in paths if path.is_file()]
    if len(found) != 1:
        raise ValueError(
            f"需要恰好一份原始 JSON：{directory}/{record['document_id']}，找到 {len(found)} 份"
        )
    return found[0]


def _read_raw(path: Path, record: dict, capture: dict | None) -> tuple[list[dict], str, str | None]:
    try:
        data = path.read_bytes()
        import json
        from hashlib import sha256 as hash_bytes

        digest = hash_bytes(data).hexdigest()
        pdf_info = extract_pdf_info(json.loads(data))
    except (ValueError, KeyError, TypeError) as exc:
        raise ValueError(f"无法读取 MinerU middle_json：{path}：{exc}") from exc
    indexes = [page.get("page_idx") for page in pdf_info]
    if indexes != list(range(record["new_gt"]["pages"])):
        raise ValueError(f"原始页号不完整或与 v3 的页数不符：{path}")
    if capture is not None:
        if not capture.get("ok") or capture.get("response_sha256") != digest:
            raise ValueError(f"原始 JSON 与采集清单不符：{path}")
        return pdf_info, digest, capture["sha256"]
    return pdf_info, digest, None


def build_feature_ir(
    gt: Path,
    raw_off: Path,
    raw_on: Path,
    pdf2text_source: Path,
    model: str,
    output: Path,
    subset_manifest: Path | None = None,
) -> dict:
    """Apply the deployed content filters to copies of two MinerU outputs per PDF."""
    manifest, records, gt_hashes = _ground_truth(gt)
    subsets = _select_groups(manifest, records, subset_manifest)
    by_id = {record["document_id"]: record for record in records}
    directories = {"A": raw_off.resolve(), "B": raw_on.resolve()}
    if directories["A"] == directories["B"]:
        raise ValueError("A 和 B 必须是两份独立采集目录")
    captures = {
        mode: _raw_manifest(directory, mode == "B", model)
        for mode, directory in directories.items()
    }
    if (
        captures["A"]
        and captures["B"]
        and any(captures["A"][key] != captures["B"][key] for key in ("endpoint", "backend"))
    ):
        raise ValueError("A 和 B 的 MinerU 服务及 backend 必须一致")
    capture_records = {
        mode: {item["document"]: item for item in capture["records"]} if capture else None
        for mode, capture in captures.items()
    }
    paths = {
        doc_id: {
            mode: _raw_path(directory, by_id[doc_id]) for mode, directory in directories.items()
        }
        for doc_id in subsets["union"]
    }
    from .mineru_middle import load_pdf2text_filters

    filters = load_pdf2text_filters(pdf2text_source)
    output = fresh_directory(output)
    sources = {}
    target_config = {"mineru_provider": "mineru3", "relevel_titles": True, "title_rules": False}
    for doc_id, files in paths.items():
        sources[doc_id] = {}
        pdf_hashes = set()
        for mode, path in files.items():
            entries = capture_records[mode]
            capture = None if entries is None else entries.get(doc_id, entries.get(path.stem, {}))
            pdf_info, digest, pdf_hash = _read_raw(path, by_id[doc_id], capture)
            if pdf_hash:
                pdf_hashes.add(pdf_hash)
            sources[doc_id][mode] = {"file": path.name, "sha256": digest, "pdf_sha256": pdf_hash}
            for group, (group_mode, switches) in GROUPS.items():
                if group_mode != mode:
                    continue
                filtered = apply_pdf2text_filters(
                    pdf_info,
                    pdf2text_source=pdf2text_source,
                    relevel_titles=False,
                    title_rules=False,
                    **switches,
                )
                document = pdf_info_to_document(
                    filtered,
                    document_id=doc_id,
                    source=path,
                    original_reported_pages=len(pdf_info),
                    effective_config={
                        **switches,
                        "relevel_titles": True,
                        "title_rules": False,
                        "relevel_applied": False,
                    },
                )
                document.dump(output / group / "documents" / f"{doc_id}.json")
        if len(pdf_hashes) > 1:
            raise ValueError(f"A/B 采集所用 PDF 不同：{doc_id}")

    provenance = {
        "schema_version": REPLAY_SCHEMA,
        "model": model,
        "gt_version": manifest["gt_version"],
        "gt_sha256": gt_hashes,
        "subset_sha256": sha256(subset_manifest) if subset_manifest else None,
        "subsets": subsets,
        "groups": {name: {"raw": raw, **config} for name, (raw, config) in GROUPS.items()},
        "pdf2text_filters_sha256": sha256(Path(filters.__file__)),
        "pdf2text_target_config": target_config,
        "stage": "content_filters_before_title_levels_and_markdown",
        "captures": {
            mode: {key: capture[key] for key in ("endpoint", "backend", "image_analysis")}
            if capture
            else None
            for mode, capture in captures.items()
        },
        "raw_sources": sources,
    }
    write_json(output / "manifest.json", provenance)
    return {"output": str(output), "documents": len(paths), "raw_documents": 2 * len(paths)}


def _blocks(document: Document, types: set[str]) -> list[tuple[int, Block]]:
    return [
        (page.number, block)
        for page in document.pages
        for block in page.blocks
        if block.type in types
    ]


def _source_id(block: Block) -> str:
    return block.metadata.get("raw_block_id") or block.id


def _iou(left: list | None, right: list | None) -> float:
    if not left or not right:
        return 0.0
    x1, y1, x2, y2 = left
    a1, b1, a2, b2 = right
    intersection = max(0, min(x2, a2) - max(x1, a1)) * max(0, min(y2, b2) - max(y1, b1))
    union = (x2 - x1) * (y2 - y1) + (a2 - a1) * (b2 - b1) - intersection
    return intersection / union if union else 0.0


def _match(
    expected: list[dict], predicted: list[tuple[int, Block]], *, visual: bool
) -> list[tuple[dict, Block]]:
    """Match once per page and give the closest candidates priority."""
    candidates = []
    for i, gt in enumerate(expected):
        for j, (page, block) in enumerate(predicted):
            predicted_type = block.metadata.get("raw_type", block.type)
            if page != gt["page"] or (not visual and gt["type"] != predicted_type):
                continue
            if visual:
                score = _iou(gt.get("bbox"), block.bbox)
                minimum = 0.5
            else:
                if not block.text.strip():
                    continue
                score = _similarity(gt.get("text", ""), block.text)
                minimum = 0.85
            if score >= minimum:
                candidates.append((-score, i, j))
    used_expected, used_predicted, pairs = set(), set(), []
    for _, i, j in sorted(candidates):
        if i not in used_expected and j not in used_predicted:
            used_expected.add(i)
            used_predicted.add(j)
            pairs.append((expected[i], predicted[j][1]))
    return pairs


def _appendix(gt: dict, on: Document, off: Document) -> dict:
    expected = set(gt["appendix"]["pages"])
    retained = {page.number for page in on.pages}
    remaining = {page.number for page in off.pages}
    body = set(range(1, gt["pages"] + 1)) - expected
    return {
        "gt": len(expected),
        "matched": len(expected & retained),
        "eligible": len(expected & retained),
        "cleared": len((expected & retained) - remaining),
        "body_pages": len(body),
        "body_retained": len(body & remaining),
        "off_exact": int(remaining == body),
        "positive_documents": int(bool(expected)),
        "negative_documents": int(not expected),
        "false_cuts": int(not expected and remaining != body),
    }


def _header_footer(gt: dict, on: Document, off: Document) -> dict:
    expected = gt["marginal_blocks"]
    predicted = [
        (page, block)
        for page, block in _blocks(on, set(MARGINAL_TYPES) | {"text"})
        if block.type in MARGINAL_TYPES or block.metadata.get("raw_type") in MARGINAL_TYPES
    ]
    pairs = _match(expected, predicted, visual=False)
    remainder = {
        _source_id(block) for page in off.pages for block in page.blocks if block.text.strip()
    }
    return {
        "gt": len(expected),
        "matched": len(pairs),
        "predicted": sum(bool(block.text.strip()) for _, block in predicted),
        "eligible": len(pairs),
        "cleared": sum(_source_id(block) not in remainder for _, block in pairs),
        "page_numbers": sum(item["type"] == "page_number" for item in expected),
        "page_numbers_matched": sum(item["type"] == "page_number" for item, _ in pairs),
    }


def _generated(block: Block) -> int:
    return sum(
        any(isinstance(span.get(key), str) and span[key].strip() for key in ("text", "content"))
        for span in block.metadata.get("generated_spans", [])
    )


def _image(gt: dict, on: Document, off: Document) -> dict:
    expected = gt["image_blocks"]  # Image and seal share the GT matching pool.
    predicted = [
        (page, block)
        for page, block in _blocks(on, {"image", "seal"})
        if block.metadata.get("raw_type") != "chart"
    ]
    pairs = _match(expected, predicted, visual=True)
    remainder = {_source_id(block): block for _, block in _blocks(off, {"image", "seal"})}
    return {
        "gt": len(expected),
        "matched": len(pairs),
        "predicted": len(predicted),
        "gt_with_output": sum(_generated(block) > 0 for _, block in pairs),
        "eligible": sum(_generated(block) for _, block in predicted),
        "cleared": sum(
            max(0, _generated(block) - _generated(remainder.get(_source_id(block), Block("", ""))))
            for _, block in predicted
        ),
        "visuals_retained": sum(_source_id(block) in remainder for _, block in predicted),
        "seal_gt": sum(item["type"] == "seal" for item in expected),
        "seal_matched": sum(item["type"] == "seal" for item, _ in pairs),
    }


def _chart_payload(block: Block) -> bool:
    # The adapter puts chart body HTML here even when the parent was downgraded.
    return bool(block.html.strip() or block.text.strip())


def _chart(gt: dict, on: Document, off: Document) -> dict:
    expected = gt["chart_blocks"]
    predicted = _blocks(on, {"chart"})
    pairs = _match(expected, predicted, visual=True)
    remainder = {_source_id(block): block for _, block in _blocks(off, {"chart", "image"})}
    contentful = [block for _, block in predicted if _chart_payload(block)]
    return {
        "gt": len(expected),
        "matched": len(pairs),
        "predicted": len(predicted),
        "gt_with_output": sum(_chart_payload(block) for _, block in pairs),
        "eligible": len(contentful),
        "cleared": sum(
            not _chart_payload(remainder.get(_source_id(block), Block("", "")))
            for block in contentful
        ),
        "downgraded": sum(
            remainder.get(_source_id(block), Block("", "")).type == "image"
            for _, block in predicted
        ),
    }


SCORERS = {"appendix": _appendix, "header_footer": _header_footer, "image": _image, "chart": _chart}
MEASURES = {
    "appendix": {
        "on_recall": ("matched", "gt"),
        "off_body_retention": ("body_retained", "body_pages"),
    },
    "header_footer": {
        "on_recall": ("matched", "gt"),
        "on_precision": ("matched", "predicted"),
        "on_page_number_recall": ("page_numbers_matched", "page_numbers"),
    },
    "image": {
        "on_recall": ("matched", "gt"),
        "on_precision": ("matched", "predicted"),
        "on_output_coverage": ("gt_with_output", "gt"),
        "on_seal_recall": ("seal_matched", "seal_gt"),
        "off_visual_retention": ("visuals_retained", "predicted"),
    },
    "chart": {
        "on_recall": ("matched", "gt"),
        "on_precision": ("matched", "predicted"),
        "on_output_coverage": ("gt_with_output", "gt"),
        "off_downgrade_rate": ("downgraded", "predicted"),
    },
}


def evaluate_feature_matrix(gt: Path, predictions: Path, output: Path) -> dict:
    """Score on/off pairs on each feature's own frozen list of PDFs."""
    _, records, hashes = _ground_truth(gt)
    by_id = {record["document_id"]: record["new_gt"] for record in records}
    source = read_json(predictions / "manifest.json")
    if source.get("schema_version") != REPLAY_SCHEMA or source.get("gt_sha256") != hashes:
        raise ValueError("IR 回放清单与当前 v3 GT 不一致，请重新生成 IR")

    def load(group: str, doc_id: str) -> Document:
        doc = Document.load(predictions / group / "documents" / f"{safe_name(doc_id)}.json")
        if doc.id != doc_id or doc.metadata.get("page_boundaries") != "explicit":
            raise ValueError(f"IR 文档 ID 或页号不符：{group}/{doc_id}")
        return doc

    metrics, per_document = {}, {}
    for feature, (on, off) in PAIRS.items():
        totals = Counter()
        rows = {}
        for doc_id in source["subsets"][feature]:
            rows[doc_id] = SCORERS[feature](by_id[doc_id], load(on, doc_id), load(off, doc_id))
            totals.update(rows[doc_id])
        metrics[feature] = {
            "documents": len(rows),
            "on_group": on,
            "off_group": off,
            "counts": dict(totals),
            **{
                name: {
                    "numerator": totals[num],
                    "denominator": totals[den],
                    "rate": _rate(totals[num], totals[den]),
                }
                for name, (num, den) in {
                    "clear_rate": ("cleared", "eligible"),
                    **MEASURES[feature],
                }.items()
            },
        }
        per_document[feature] = rows

    output = fresh_directory(output)
    write_json(output / "metrics.json", metrics)
    write_json(output / "per_document.json", per_document)
    write_json(
        output / "provenance.json",
        source | {"replay_sha256": sha256(predictions / "manifest.json")},
    )
    lines = [
        "# 129 四功能开关对照",
        "",
        f"模型：`{source['model']}`；GT：`{FEATURE_GT_VERSION}`。",
        "",
        "| 功能 | 样本数 | 指标 | 分子 / 分母 | 比例 |",
        "| --- | ---: | --- | ---: | ---: |",
    ]
    for feature, values in metrics.items():
        for label in ("clear_rate", *MEASURES[feature]):
            value = values[label]
            rate = "不可计分" if value["rate"] is None else f"{value['rate']:.2%}"
            lines.append(
                f"| {feature} | {values['documents']} | `{label}` | "
                f"{value['numerator']} / {value['denominator']} | {rate} |"
            )
    lines.extend(["", "清除率检测关闭前已有的输出；image/chart 的覆盖率仅统计是否产出内容。", ""])
    (output / "report.md").write_text("\n".join(lines), encoding="utf-8")
    return {"output": str(output), "metrics": metrics}
