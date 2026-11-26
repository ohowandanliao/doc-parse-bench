"""Offline replay and paired scoring for the 129-document feature GT."""

from collections import Counter
from pathlib import Path

from ..io import fresh_directory, read_json, safe_name, sha256, write_json
from ..mineru_middle import apply_pdf2text_filters, extract_pdf_info, pdf_info_to_document
from ..schema import MARGINAL_TYPES, Block, Document
from .feature_contract import FEATURE_GT_VERSION, FEATURES, PAIRS
from .feature_eval import (
    MARGINAL_IMAGE_TYPES,
    _iou,
    _rate,
    _records_from_gt,
    _select_feature_records,
    _similarity,
)

VISUAL_FEATURES = ("image", "chart")
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


def _ground_truth(gt: Path) -> tuple[dict, list[dict], dict]:
    manifest, records = _records_from_gt(gt)
    if manifest.get("gt_version") != FEATURE_GT_VERSION:
        raise ValueError(f"四功能矩阵要求 {FEATURE_GT_VERSION}：{gt}")
    return (
        manifest,
        records,
        {name: sha256(gt / name) for name in ("manifest.json", "records.json")},
    )


def _select_groups(
    manifest: dict, records: list[dict], subset: Path | None, features: tuple[str, ...]
) -> dict:
    groups = {}
    for name in ("union", *features):
        selected, _ = _select_feature_records(manifest, records, subset, name if subset else None)
        groups[name] = [safe_name(record["document_id"]) for record in selected]
    expected = set().union(*(set(groups[name]) for name in features))
    if set(groups["union"]) != expected:
        raise ValueError(f"union 必须正好是 {', '.join(features)} 子集的并集")
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
    raw_off: Path | None,
    raw_on: Path,
    pdf2text_source: Path,
    model: str,
    output: Path,
    subset_manifest: Path | None = None,
    *,
    visual_only: bool = False,
) -> dict:
    """Replay paired switches on A/B, or only image and chart switches on B."""
    manifest, records, gt_hashes = _ground_truth(gt)
    subsets = _select_groups(
        manifest, records, subset_manifest, VISUAL_FEATURES if visual_only else FEATURES
    )
    by_id = {record["document_id"]: record for record in records}
    if visual_only and raw_off is not None:
        raise ValueError("--visual-only 仅使用 raw-B，不接受 --raw-off")
    if not visual_only and raw_off is None:
        raise ValueError("完整四功能回放需要 --raw-off；只评图片、图表请用 --visual-only")
    directories = {"A": raw_off.resolve()} if raw_off is not None else {}
    directories["B"] = raw_on.resolve()
    if directories.get("A") == directories["B"]:
        raise ValueError("A 和 B 必须是两份独立采集目录")
    groups = {name: spec for name, spec in GROUPS.items() if spec[0] in directories}
    captures = {
        mode: _raw_manifest(directory, mode == "B", model)
        for mode, directory in directories.items()
    }
    if (
        captures.get("A")
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
    from ..mineru_middle import load_pdf2text_filters

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
            for group, (group_mode, switches) in groups.items():
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
        "groups": {name: {"raw": raw, **config} for name, (raw, config) in groups.items()},
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
    if visual_only:
        provenance["scope"] = "visual_only"
    write_json(output / "manifest.json", provenance)
    return {
        "output": str(output),
        "documents": len(paths),
        "raw_documents": len(directories) * len(paths),
    }


def _blocks(document: Document, types: set[str]) -> list[tuple[int, Block]]:
    return [
        (page.number, block)
        for page in document.pages
        for block in page.blocks
        if block.type in types
    ]


def _source_id(block: Block) -> str:
    return block.metadata.get("raw_block_id") or block.id


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


def _match_visual_types(
    expected: list[dict], predicted: list[tuple[int, Block]], *, strict_types: bool
) -> list[tuple[dict, Block]]:
    """Match the combined image/chart view, optionally enforcing visual types."""
    if not strict_types:
        return _match(expected, predicted, visual=True)

    candidates = []
    for i, gt in enumerate(expected):
        for j, (page, block) in enumerate(predicted):
            if page != gt["page"]:
                continue
            predicted_is_chart = block.type == "chart"
            expected_is_chart = gt["type"] == "chart"
            if expected_is_chart != predicted_is_chart:
                continue
            if not expected_is_chart and block.metadata.get("raw_type") == "chart":
                continue
            score = _iou(gt.get("bbox"), block.bbox)
            if score >= 0.5:
                candidates.append((-score, i, j))
    used_expected, used_predicted, pairs = set(), set(), []
    for _, i, j in sorted(candidates):
        if i not in used_expected and j not in used_predicted:
            used_expected.add(i)
            used_predicted.add(j)
            pairs.append((expected[i], predicted[j][1]))
    return pairs


def _visual_output(block: Block) -> bool:
    """Whether a visual block carries analysis output in the combined view."""
    if block.type == "chart":
        return _chart_payload(block)
    return bool(_generated(block))


def _f1(numerator: int, predicted: int, expected: int) -> float | None:
    precision = _rate(numerator, predicted)
    recall = _rate(numerator, expected)
    if precision is None or recall is None or precision + recall == 0:
        return None
    return 2 * precision * recall / (precision + recall)


def _combined_visual(gt: dict, document: Document) -> dict:
    """Score image and chart as one visual inventory without double counting."""
    expected = gt["image_blocks"] + gt["chart_blocks"]
    predicted = _blocks(document, {"image", "seal", "chart"})
    strict_pairs = _match_visual_types(expected, predicted, strict_types=True)
    location_pairs = _match_visual_types(expected, predicted, strict_types=False)
    strict_image = sum(item["type"] != "chart" for item, _ in strict_pairs)
    strict_chart = sum(item["type"] == "chart" for item, _ in strict_pairs)
    location_image = sum(item["type"] != "chart" for item, _ in location_pairs)
    location_chart = sum(item["type"] == "chart" for item, _ in location_pairs)
    image_as_chart = sum(
        item["type"] != "chart" and block.type == "chart" for item, block in location_pairs
    )
    chart_as_image = sum(
        item["type"] == "chart" and block.type != "chart" for item, block in location_pairs
    )
    return {
        "gt": len(expected),
        "image_gt": len(gt["image_blocks"]),
        "chart_gt": len(gt["chart_blocks"]),
        "predicted": len(predicted),
        "strict_matched": len(strict_pairs),
        "strict_image_matched": strict_image,
        "strict_chart_matched": strict_chart,
        "strict_gt_with_output": sum(_visual_output(block) for _, block in strict_pairs),
        "location_matched": len(location_pairs),
        "location_image_matched": location_image,
        "location_chart_matched": location_chart,
        "location_gt_with_output": sum(_visual_output(block) for _, block in location_pairs),
        "image_as_chart": image_as_chart,
        "chart_as_image": chart_as_image,
    }


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
    expected_images = [item for item in expected if item["type"] in MARGINAL_IMAGE_TYPES]
    predicted = [
        (page, block)
        for page, block in _blocks(on, set(MARGINAL_TYPES) | {"text"})
        if block.type in MARGINAL_TYPES or block.metadata.get("raw_type") in MARGINAL_TYPES
    ]
    pairs = _match(
        [item for item in expected if item["type"] in MARGINAL_TYPES], predicted, visual=False
    )
    remainder = {
        _source_id(block) for page in off.pages for block in page.blocks if block.text.strip()
    }

    def image_blocks(document: Document) -> list[tuple[int, Block]]:
        return [
            (page.number, block)
            for page in document.pages
            for block in page.blocks
            if block.bbox
            and (
                block.type in MARGINAL_IMAGE_TYPES | {"image"}
                or any(span.get("image_path") for span in block.metadata.get("spans", []))
            )
        ]

    on_images = image_blocks(on)
    matched_images = []
    predicted_images = 0
    for kind in sorted(MARGINAL_IMAGE_TYPES):
        typed_images = [
            (page, block)
            for page, block in on_images
            if block.metadata.get("raw_type", block.type) == kind
        ]
        predicted_images += len(typed_images)
        matched_images.extend(
            _match(
                [item for item in expected_images if item["type"] == kind],
                typed_images,
                visual=True,
            )
        )
    off_images = image_blocks(off)
    residual_images = _match(expected_images, off_images, visual=True)
    cleared_images = sum(
        not any(
            page == item["page"] and _iou(item.get("bbox"), block.bbox) >= 0.5
            for page, block in off_images
        )
        for item, _ in matched_images
    )
    return {
        "gt": len(expected),
        "matched": len(pairs) + len(matched_images),
        "predicted": sum(bool(block.text.strip()) for _, block in predicted) + predicted_images,
        "eligible": len(pairs) + len(matched_images),
        "cleared": sum(_source_id(block) not in remainder for _, block in pairs) + cleared_images,
        "page_numbers": sum(item["type"] == "page_number" for item in expected),
        "page_numbers_matched": sum(item["type"] == "page_number" for item, _ in pairs),
        "image_gt": len(expected_images),
        "images_matched": len(matched_images),
        "images_remaining": len(residual_images),
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
    content_output = sum(_generated(block) > 0 for _, block in pairs)
    return {
        "gt": len(expected),
        "matched": len(pairs),
        "predicted": len(predicted),
        "content_output": content_output,
        "gt_with_output": content_output,
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
    content_output = sum(_chart_payload(block) for _, block in pairs)
    return {
        "gt": len(expected),
        "matched": len(pairs),
        "predicted": len(predicted),
        "content_output": content_output,
        "gt_with_output": content_output,
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
        "on_marginal_image_recall": ("images_matched", "image_gt"),
        "off_marginal_image_residual_rate": ("images_remaining", "image_gt"),
    },
    "image": {
        "on_recall": ("matched", "gt"),
        "on_precision": ("matched", "predicted"),
        "content_output_recall": ("content_output", "gt"),
        "on_output_coverage": ("gt_with_output", "gt"),
        "on_seal_recall": ("seal_matched", "seal_gt"),
        "off_visual_retention": ("visuals_retained", "predicted"),
    },
    "chart": {
        "on_recall": ("matched", "gt"),
        "on_precision": ("matched", "predicted"),
        "content_output_recall": ("content_output", "gt"),
        "on_output_coverage": ("gt_with_output", "gt"),
        "off_downgrade_rate": ("downgraded", "predicted"),
    },
}


def evaluate_feature_matrix(
    gt: Path,
    predictions: Path,
    output: Path,
    allow_gt_revision: bool = False,
) -> dict:
    """Score on/off pairs on each feature's own frozen list of PDFs.

    A replay directory normally has to be built from the exact GT hash it
    records in its manifest.  ``allow_gt_revision`` is an explicit escape
    hatch for a reviewed GT revision when the raw MinerU responses are no
    longer available.  The resulting provenance keeps both hashes visible.
    """
    manifest, records, hashes = _ground_truth(gt)
    by_id = {record["document_id"]: record["new_gt"] for record in records}
    source = read_json(predictions / "manifest.json")
    if source.get("schema_version") != REPLAY_SCHEMA:
        raise ValueError("不是四功能 IR 回放清单")
    features = VISUAL_FEATURES if source.get("scope") == "visual_only" else FEATURES
    source_hashes = source.get("gt_sha256")
    gt_revision = source_hashes != hashes
    if gt_revision and not allow_gt_revision:
        raise ValueError("IR 回放清单与当前 v3 GT 不一致，请重新生成 IR")
    if gt_revision:
        source_ids = {
            document_id for subset in source.get("subsets", {}).values() for document_id in subset
        }
        if not source_ids.issubset(by_id):
            missing = sorted(source_ids - set(by_id))
            raise ValueError(f"GT 修订后缺少 IR 中的文档：{missing[:5]}")
        source["gt_revision"] = {
            "allowed": True,
            "source_gt_sha256": source_hashes,
            "evaluated_gt_sha256": hashes,
            "evaluated_gt_version": manifest.get("gt_version"),
        }

    def load(group: str, doc_id: str) -> Document:
        doc = Document.load(predictions / group / "documents" / f"{safe_name(doc_id)}.json")
        if doc.id != doc_id or doc.metadata.get("page_boundaries") != "explicit":
            raise ValueError(f"IR 文档 ID 或页号不符：{group}/{doc_id}")
        return doc

    metrics, per_document = {}, {}
    for feature in features:
        on, off = PAIRS[feature]
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

    combined_rows = {}
    combined_totals = Counter()
    for doc_id in source["subsets"]["union"]:
        row = _combined_visual(by_id[doc_id], load("chart", doc_id))
        combined_rows[doc_id] = row
        combined_totals.update(row)
    metrics["combined_visual"] = {
        "documents": len(combined_rows),
        "on_group": "chart",
        "counts": dict(combined_totals),
        "strict_type": {
            "recall": {
                "numerator": combined_totals["strict_matched"],
                "denominator": combined_totals["gt"],
                "rate": _rate(combined_totals["strict_matched"], combined_totals["gt"]),
            },
            "precision": {
                "numerator": combined_totals["strict_matched"],
                "denominator": combined_totals["predicted"],
                "rate": _rate(combined_totals["strict_matched"], combined_totals["predicted"]),
            },
            "f1": _f1(
                combined_totals["strict_matched"],
                combined_totals["predicted"],
                combined_totals["gt"],
            ),
            "output_coverage": {
                "numerator": combined_totals["strict_gt_with_output"],
                "denominator": combined_totals["gt"],
                "rate": _rate(combined_totals["strict_gt_with_output"], combined_totals["gt"]),
            },
        },
        "location_only": {
            "recall": {
                "numerator": combined_totals["location_matched"],
                "denominator": combined_totals["gt"],
                "rate": _rate(combined_totals["location_matched"], combined_totals["gt"]),
            },
            "precision": {
                "numerator": combined_totals["location_matched"],
                "denominator": combined_totals["predicted"],
                "rate": _rate(combined_totals["location_matched"], combined_totals["predicted"]),
            },
            "f1": _f1(
                combined_totals["location_matched"],
                combined_totals["predicted"],
                combined_totals["gt"],
            ),
            "output_coverage": {
                "numerator": combined_totals["location_gt_with_output"],
                "denominator": combined_totals["gt"],
                "rate": _rate(combined_totals["location_gt_with_output"], combined_totals["gt"]),
            },
        },
        "image_recall_with_chart_confusion": {
            "numerator": combined_totals["location_image_matched"],
            "denominator": combined_totals["image_gt"],
            "rate": _rate(combined_totals["location_image_matched"], combined_totals["image_gt"]),
        },
    }
    per_document["combined_visual"] = combined_rows

    output = fresh_directory(output)
    write_json(output / "metrics.json", metrics)
    write_json(output / "per_document.json", per_document)
    write_json(
        output / "provenance.json",
        source
        | {
            "replay_sha256": sha256(predictions / "manifest.json"),
            "evaluated_gt_sha256": hashes,
        },
    )
    lines = [
        "# 129 图片／图表开关对照" if features == VISUAL_FEATURES else "# 129 四功能开关对照",
        "",
        f"模型：`{source['model']}`；GT：`{FEATURE_GT_VERSION}`。",
        "",
        "| 功能 | 样本数 | 指标 | 分子 / 分母 | 比例 |",
        "| --- | ---: | --- | ---: | ---: |",
    ]
    for feature, values in metrics.items():
        if feature == "combined_visual":
            continue
        for label in ("clear_rate", *MEASURES[feature]):
            value = values[label]
            rate = "不可计分" if value["rate"] is None else f"{value['rate']:.2%}"
            lines.append(
                f"| {feature} | {values['documents']} | `{label}` | "
                f"{value['numerator']} / {value['denominator']} | {rate} |"
            )
    combined = metrics["combined_visual"]
    lines.extend(
        [
            "",
            "## image + chart 合并诊断",
            "",
            "合并只使用 `chart_analysis=true` 的 chart 组，避免 image 组降级后的重复计数。",
            "",
            "| 口径 | 召回 | 精确率 | F1 | 输出覆盖 |",
            "| --- | ---: | ---: | ---: | ---: |",
        ]
    )
    for label, values in (
        ("类型严格", combined["strict_type"]),
        ("只看视觉位置", combined["location_only"]),
    ):
        recall = values["recall"]
        precision = values["precision"]
        coverage = values["output_coverage"]
        f1 = values["f1"]
        recall_rate = "不可计分" if recall["rate"] is None else f"{recall['rate']:.2%}"
        precision_rate = "不可计分" if precision["rate"] is None else f"{precision['rate']:.2%}"
        coverage_rate = "不可计分" if coverage["rate"] is None else f"{coverage['rate']:.2%}"
        f1_value = "不可计分" if f1 is None else f"{f1:.2%}"
        lines.append(
            f"| {label} | {recall['numerator']}/{recall['denominator']} "
            f"({recall_rate}) | {precision['numerator']}/{precision['denominator']} "
            f"({precision_rate}) | {f1_value} | "
            f"{coverage['numerator']}/{coverage['denominator']} ({coverage_rate}) |"
        )
    lines.extend(
        [
            "",
            f"image GT 被 chart 框覆盖：{combined['counts']['image_as_chart']}；"
            f"chart GT 被 image 框覆盖：{combined['counts']['chart_as_image']}。",
        ]
    )
    lines.extend(
        [
            "",
            "清除率检测关闭前已有的输出；`content_output_recall` 是匹配视觉块后是否产出非空内容的能力分，",
            "`on_output_coverage` 作为兼容字段保留。两者都不判断图内数字或字符的严格正确性。",
            "",
        ]
    )
    (output / "report.md").write_text("\n".join(lines), encoding="utf-8")
    return {"output": str(output), "metrics": metrics}
