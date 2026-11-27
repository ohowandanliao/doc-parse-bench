"""Score one saved Legacy 129 batch using its final P2T products."""

import json
from collections import Counter, defaultdict
from pathlib import Path
from zipfile import ZipFile

from ...io import fresh_directory, read_json, sha256, write_json
from ..feature_contract import PAIRS
from ..feature_eval import _iou
from ..feature_rubric import _text, evaluate_feature_rubric
from . import build_report
from . import score_image_supplement as visual


def _visual_cases(cases):
    grouped = defaultdict(list)
    for case in cases:
        if case.get("protected"):
            continue
        if (case["feature"] == "image" and case["sub_type"] != "other") or (
            case["feature"] == "chart" and case.get("values")
        ):
            grouped[case["document_id"], case["feature"]].append(case)
    return grouped


def _observe_image(case, block, spans, image_available):
    kind = case["sub_type"]
    observation = {"block_id": block.id, "raw_content": [text for _, text in spans]}
    if kind == "seal":
        if block.type != "seal":
            return None, "seal_attribution"
    else:
        if block.type != "image" or "sub_type" not in block.metadata:
            return None, "source_subtype_unverified"
        actual = block.metadata["sub_type"]
        observation["sub_type"] = actual
        if actual is not None:
            observation["subtype_id"] = block.id
        if actual != kind:
            return observation, None

    if kind == "flowchart" and spans:
        return None, "flowchart_content_needs_review"
    expected = Counter(_text(field["text"]) for field in case["fields"])
    delivered = Counter(_text(text) for _, text in spans)
    if any(expected[text] != 1 or count != 1 for text, count in delivered.items()):
        return None, "field_attribution_needs_review"
    observation["fields"] = visual.field_rows(spans, case["fields"], block.id)
    if not case["fields"]:
        observation["image_available"] = image_available
    if "relations" in case:
        observation["relations"] = []
    return observation, None


def _observe_visual(case, candidates, owners, visible, assets, embedded):
    if not candidates:
        return None, "source_block_unverified"
    if len(candidates) != 1 or owners[candidates[0].id] != 1:
        return None, "ambiguous_source_block"
    (block,) = candidates
    if _iou(case["bbox"], block.bbox) < 0.5:
        return None, "ambiguous_source_block"
    spans = visual.literal_text(block, visible)
    image_available = bool(visual.image_hashes(block, assets) & embedded)
    if any(
        text and _text(text) and (index, text) not in spans
        for index, text in visual.body_fragments(block)
    ):
        return None, "body_not_verified_in_markdown"
    if not spans and not image_available:
        return None, "delivery_unverified"
    if case["feature"] == "chart":
        if block.type != "chart":
            return None, "chart_attribution"
        observation = build_report.chart_observation(block, build_report.MARKDOWN)
        payload = observation.get("payload")
        if (spans and not payload) or (payload and visual.visible_text(payload) not in visible):
            return None, "chart_payload_unverified"
        return observation, None
    return _observe_image(case, block, spans, image_available)


def _visual_evidence(archive, model, grouped, reviewed):
    charts, images, image_captures, pending = {}, {}, {}, {}
    for (document, feature), cases in grouped.items():
        group = "image_only" if feature == "image" else "both_on"
        _, pages, visible, assets, embedded, meta = visual.delivery(archive, model, document, group)
        if meta["filters"]["image_analysis"] != "true" or meta["filters"]["chart_analysis"] is not (
            feature == "chart"
        ):
            raise ValueError(f"{document} 的 {group} 开关与取证口径不符")
        if feature == "image":
            capture = meta["source"]["capture_sha256"]
            image_captures[document] = capture
            if (
                any(case["id"] in reviewed["cases"] for case in cases)
                and reviewed.get("image_only_captures", {}).get(document) != capture
            ):
                raise ValueError(f"{document} 的图片复核证据与 image_only 回包不符")

        pages_by_number = {page.number: page for page in pages}
        candidates_by_case = {
            case["id"]: [
                block
                for block in pages_by_number[case["page"]].blocks
                if _iou(case["bbox"], block.bbox) > 0
                and block.type in visual.VISUAL | {"table", "image_block"}
            ]
            for case in cases
        }
        owners = Counter(
            block.id for candidates in candidates_by_case.values() for block in candidates
        )
        for case in cases:
            case_id = case["id"]
            candidates = candidates_by_case[case_id]
            observed = reviewed["cases"].get(case_id)
            reason = None
            if observed is None:
                observed, reason = _observe_visual(
                    case, candidates, owners, visible, assets, embedded
                )
            if observed is not None:
                target = images if feature == "image" else charts
                target[case_id] = observed
                continue
            pending[case_id] = {
                "document_id": document,
                "page": case["page"],
                "source_bbox": case["bbox"],
                "group": group,
                "capture_sha256": meta["source"]["capture_sha256"],
                "reason": reason,
                "candidates": [
                    {
                        "block_id": block.id,
                        "type": block.type,
                        "sub_type": block.metadata.get("sub_type"),
                        "bbox": block.bbox,
                        "content": [span for _, span in visual.literal_text(block, visible)],
                        "body_fragments": [
                            span for _, span in visual.body_fragments(block) if span
                        ],
                        "image_available": bool(visual.image_hashes(block, assets) & embedded),
                    }
                    for block in candidates
                ],
            }
    return charts, images, image_captures, pending


def _add_visual_protection(archive, model, cases, reviewed, evidence):
    for case in cases:
        case_id, feature, document = case["id"], case["feature"], case["document_id"]
        if not case.get("protected") or feature not in {"image", "chart"}:
            continue
        observed = reviewed["cases"].get(case_id)
        if observed is None:
            continue
        prefix = f"{model}/documents/{document}/final"
        on = json.loads(archive.read(f"{prefix}/both_on/meta.json"))
        off = json.loads(archive.read(f"{prefix}/controls_image_off/meta.json"))
        capture = on["source"]["capture_sha256"]
        if off["source"]["base_capture_sha256"] != capture:
            raise ValueError(f"{case_id} 的开关对照来自不同回包")
        groups = PAIRS[feature]
        reviewed_captures = reviewed.get("captures", {}).get(document, {})
        if any(reviewed_captures.get(group) != capture for group in groups):
            raise ValueError(f"{case_id} 的保护项复核与成品回包不符")
        evidence["captures"][document].update(dict.fromkeys(groups, capture))
        evidence["cases"][case_id] = observed


def _add_reviewed_margins(cases, reviewed, evidence):
    for case in cases:
        case_id = case["id"]
        if case["feature"] != "header_footer" or case_id in evidence["cases"]:
            continue
        observed = reviewed["cases"].get(case_id)
        if observed is None:
            continue
        document = case["document_id"]
        actual = evidence["captures"][document]
        reviewed_captures = reviewed.get("captures", {}).get(document, {})
        if any(reviewed_captures.get(group) != actual[group] for group in PAIRS["header_footer"]):
            raise ValueError(f"{case_id} 的页眉页脚复核与成品回包不符")
        evidence["cases"][case_id] = observed


def evaluate_legacy129_batch(
    archive_path: Path,
    model: str,
    output: Path,
    *,
    model_name: str | None = None,
    reviewed_path: Path | None = None,
    gt_path: Path | None = None,
    sources_path: Path | None = None,
) -> dict:
    gt_path = gt_path or build_report.GT
    sources_path = sources_path or build_report.INPUT
    gt_sha256 = sha256(gt_path)
    cases = read_json(gt_path)["cases"]
    documents = read_json(sources_path)["documents"]
    missing = {case["document_id"] for case in cases} - {doc["document_id"] for doc in documents}
    if missing:
        raise ValueError(f"来源清单缺少 GT 文档：{', '.join(sorted(missing))}")
    products_sha256 = sha256(archive_path)
    reviewed = {"cases": {}}
    if reviewed_path is not None:
        reviewed = read_json(reviewed_path)
        if (
            reviewed.get("gt_sha256") != gt_sha256
            or reviewed.get("products_sha256") != products_sha256
        ):
            raise ValueError("复核证据须关联本批 GT 和 P2T 成品 ZIP 的 SHA-256")

    with ZipFile(archive_path) as archive:
        charts, images, image_captures, pending = _visual_evidence(
            archive, model, _visual_cases(cases), reviewed
        )
        evidence, _ = build_report.collect(
            archive,
            model,
            documents,
            cases,
            {"cases": charts, "gt_sha256": gt_sha256},
            model_name=model_name or model,
            strict=False,
        )
        evidence["cases"].update(images)
        _add_reviewed_margins(cases, reviewed, evidence)
        _add_visual_protection(archive, model, cases, reviewed, evidence)

    evidence["image_only_captures"] = image_captures
    evidence["products_sha256"] = products_sha256
    evidence["sources_sha256"] = sha256(sources_path)
    evidence["extractor_sha256"] = {
        Path(module_file).name: sha256(Path(module_file))
        for module_file in (__file__, build_report.__file__, visual.__file__)
    }
    output = fresh_directory(output)
    evidence_path = output / "evidence.json"
    write_json(evidence_path, evidence)
    write_json(output / "visual_review.json", pending)
    return evaluate_feature_rubric(gt_path, evidence_path, output / "scores")
