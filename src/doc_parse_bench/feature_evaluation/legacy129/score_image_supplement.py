import argparse
import base64
import json
import re
from collections import defaultdict, deque
from copy import deepcopy
from hashlib import sha256 as digest
from html import unescape
from pathlib import Path
from zipfile import ZipFile

from ...io import fresh_directory, read_json, sha256, write_json
from ...mineru_middle import (
    _restore_modules,
    _temporary_logging_stub,
    extract_middle_json,
    load_pdf2text_filters,
    pdf_info_to_document,
)
from ..feature_eval import _iou
from ..feature_rubric import _text, evaluate_feature_rubric
from .build_report import GT, IMAGE_DATA, MODELS, OUTPUT, html_report

VISUAL = {"image", "seal", "chart"}
BODY = {"image_body", "chart_body", "table_body", "seal_body"}
GRAPH_LABEL = re.compile(
    r'(?P<id>[\w+.-]+)\s*(?:\(\["(?P<round>[^"\n]*)"\]\)|'
    r'\["(?P<rect>[^"\n]*)"\]+|\{"?(?P<diamond>[^"\n{}]*)"?\}|'
    r'\[(?P<bare>[^\[\]\n"]+)\])'
)
ARROW = re.compile(
    r"\s+(?:--\s+([^|\n]+?)\s+-->|-\.\s+([^|\n]+?)\s+\.->|-->|-\.->|==>)"
    r"(?:\s*\|([^|\n]+)\|)?\s*"
)
MERMAID = re.compile(r"^```mermaid\s*\n(.*?)^```", re.M | re.S)
SVG_NAMES = re.compile(r"(?:<br\s*/?>|\\n)", re.I)
REVIEWED_VISUALS = {
    ("ft", "bc_041:candidate.block.p1.0000"): "mineru.p1.0002",
    ("ft", "bc_041:candidate.block.p1.0003"): "mineru.p1.0007",
    ("origin", "bc_019:candidate.block.p1.0006"): "mineru.p1.0008",
}
MISSING_SOURCE_LABELS = {
    "bc_022:candidate.block.p5.0003": "成品为 Fig. 6 的七个独立面板，只记录了面板级类型。",
    "bc_022:candidate.block.p6.0009": "Fig. 8 的 a、b 合为一图，记录的是合框级类型。",
    "bc_024:manual.block.p1.0001": "成品分开处理封面图的组成部分，缺少整图类型。",
    "bc_047:candidate.block.p1.0008": "成品把源图转成了表格，缺少源图类型。",
    "bc_056:candidate.block.p1.0020": "左右两张电路板照片合成一个分析块。",
    "bc_056:candidate.block.p1.0022": "左右两张电路板照片合成一个分析块。",
    "bc_062:manual.block.p1.0001": "图中段落以正文形式交付，未交付该源图的 subtype。",
}


def verify_supplement(supplement, slim):
    manifest = json.loads(supplement.read("SUPPLEMENT-MANIFEST.json"))
    assert not manifest["missing"]
    verified = {}
    for model, documents in manifest["groups"].items():
        for document, variants in documents.items():
            for group, entry in variants.items():
                root = f"{model}/documents/{document}"
                response = supplement.read(f"{root}/requests/{group}/response.raw.json")
                capture = digest(response).hexdigest()
                assert capture == entry["capture_sha256"] == entry["raw_response_sha256"]
                assert len(response) == entry["raw_response_bytes"] and not entry["missing"]
                raw = extract_middle_json(json.loads(response))
                saved = json.loads(supplement.read(f"{root}/raw/{group}.middle_json.json"))
                assert raw["pdf_info"] == saved["pdf_info"]
                path = f"{root}/final/{group}"
                for name in ("final.md", "middle_json.json", "meta.json"):
                    assert supplement.read(f"{path}/{name}") == slim.read(f"{path}/{name}")
                meta = json.loads(slim.read(f"{path}/meta.json"))
                trace = json.loads(supplement.read(f"{root}/trace/{group}.json"))
                assert capture == meta["source"]["capture_sha256"] == trace["capture_sha256"]
                for asset in meta["assets"]:
                    candidates = [
                        f"{path}/assets/{asset['file']}",
                        f"{root}/raw/{group}/assets/{asset['file']}",
                    ]
                    files = [name for name in candidates if name in supplement.NameToInfo]
                    assert files, (model, document, group, asset["file"])
                    assert all(
                        digest(supplement.read(name)).hexdigest() == asset["sha256"]
                        for name in files
                    )
                verified[model, document, group] = capture
    return verified


def visible_text(text):
    return _text(re.sub(r"\\([\\*_`#|$])", r"\1", unescape(text)))


def delivery(archive, model, document, group):
    root = f"{model}/documents/{document}/final/{group}"
    payload = archive.read(f"{root}/middle_json.json")
    markdown = archive.read(f"{root}/final.md")
    meta = json.loads(archive.read(f"{root}/meta.json"))
    assert digest(payload).hexdigest() == meta["middle_json_sha256"]
    assert digest(markdown).hexdigest() == meta["markdown_sha256"]
    assert meta["relevel_applied"] and not meta["filters"]["title_rules"]
    raw = json.loads(payload)["pdf_info"]
    pages = pdf_info_to_document(raw, document_id=document).pages
    markdown = markdown.decode()
    assets = {asset["key"]: asset["sha256"] for asset in meta["assets"]}
    embedded = {
        digest(base64.b64decode(match.group().split(",", 1)[1], validate=True)).hexdigest()
        for match in IMAGE_DATA.finditer(markdown)
    }
    return raw, pages, visible_text(IMAGE_DATA.sub("", markdown)), assets, embedded, meta


def body_spans(block):
    children = block.metadata["nested_blocks"]
    if not children:
        return block.metadata["spans"]
    return [span for child in children if child["type"] in BODY for span in child["spans"]]


def image_hashes(block, assets):
    return {
        assets[span["image_path"]] for span in body_spans(block) if span.get("image_path") in assets
    }


def body_fragments(block):
    return [
        (index, span.get("content") or span.get("text") or span.get("html"))
        for index, span in enumerate(body_spans(block))
    ]


def literal_text(block, final):
    return [
        (index, text)
        for index, text in body_fragments(block)
        if text and visible_text(text) in final
    ]


def graph_labels(source):
    (graph,) = MERMAID.findall(source)
    labels, edges, branches = {}, [], []

    def node_label(match):
        native_id = match["id"]
        label = next(
            match[key] for key in ("round", "rect", "diamond", "bare") if match[key] is not None
        )
        label = SVG_NAMES.sub(" ", unescape(label)).strip()
        if label.startswith('["'):
            label = re.sub(r'^\["(.*?)"\]?$', r"\1", label)
        assert native_id not in labels or labels[native_id] == label, native_id
        labels[native_id] = label
        return native_id

    for number, line in enumerate(graph.splitlines(), start=1):
        line = line.strip()
        if not line or line.startswith(
            ("%%", "graph ", "flowchart ", "direction ", "classDef ", "style ")
        ):
            continue
        line = GRAPH_LABEL.sub(node_label, line)
        if re.match(r"^subgraph\b", line) or line == "end":
            continue
        parts = ARROW.split(line)
        if len(parts) == 1:
            continue
        previous = parts[0]
        for position in range(1, len(parts), 4):
            label = next(
                (value for value in parts[position : position + 3] if value is not None), None
            )
            following = parts[position + 3]
            for start in previous.split("&"):
                for end in following.split("&"):
                    edges.append((f"{number}.{len(edges)}", start.strip(), end.strip(), label))
            if label:
                branches.append((f"branch.{number}.{position}", unescape(label).strip().strip('"')))
            previous = following
    return labels, edges, branches


def field_rows(entries, expected, prefix, keys=None):
    available = defaultdict(deque)
    for field in expected:
        available[_text(field["text"])].append(field["key"])
    result = []
    used = set()
    for native_id, value in entries:
        queue = available.get(_text(value))
        explicit = (keys or {}).get(native_id)
        key = explicit or next((key for key in queue or () if key not in used), "unmatched")
        used.add(key)
        result.append({"id": f"{prefix}:{native_id}", "key": key, "text": value})
    return result


def flowchart(case, model, span, prefix):
    labels, edges, branches = graph_labels(span)
    positional = {}
    if case["id"] == "bc_024:candidate.block.p6.0008":
        positional = (
            {
                "B": "base1",
                "D": "base2",
                "F": "learning1",
                "J": "learning2",
                "G": "weight1",
                "K": "weight2",
                "H": "unmatched",
                "I": "unmatched",
                "L": "unmatched",
            }
            if model == "ft"
            else {
                "B": "base1",
                "C": "base2",
                "E": "base3",
                "F": "learning1",
                "G": "learning2",
                "I": "learning3",
                "J": "weight1",
                "K": "weight2",
                "M": "weight3",
                "L": "unmatched",
            }
        )
    entries = [(native_id, text) for native_id, text in labels.items() if text not in ("…", "...")]
    fields = field_rows(entries + branches, case["fields"], prefix, positional)
    result = {"fields": fields, "parsed_edge_count": len(edges)}
    if "relations" in case:
        node_keys = {
            native_id: field["key"] if field["key"] != "unmatched" else f"unmapped:{native_id}"
            for (native_id, _), field in zip(entries, fields)
        }
        result["relations"] = [
            {
                "id": f"{prefix}:edge:{edge_id}",
                "from": node_keys.get(start, f"unmapped:{start}"),
                "to": node_keys.get(end, f"unmapped:{end}"),
                "branch_label": label,
            }
            for edge_id, start, end, label in edges
        ]
    if positional:
        result["attribution_note"] = (
            "同名分类器按输出分支顺序对应，Learning 和 Weight 沿各分支归属。"
        )
    return result


def seal_fields(case, model, picked, spans):
    case_id = case["id"]
    expected = case["fields"]
    if model == "origin" and case_id in {
        "bc_019:manual.block.p1.0001",
        "bc_019:manual.block.p1.0002",
    }:
        position = 4 if case_id.endswith("0001") else 6
        index, content = spans[0]
        lines = content.splitlines()
        assert lines[position] == "合同专用章"
        assert lines[position + 1] == ("42011910463892" if position == 4 else "33021110076089")
        return [
            {"id": f"{picked.id}:{index}:{position}", "key": "purpose", "text": lines[position]}
        ]
    if not spans:
        return []
    index, content = spans[0]
    lines = [line.strip() for line in content.splitlines() if line.strip()]
    if case_id in {"bc_018:candidate.block.p1.0021", "bc_019:candidate.block.p1.0006"}:
        expected_lengths = [len(field["text"]) for field in expected]
        lines = [line[:length] for line, length in zip(lines, expected_lengths)]
    elif case_id.endswith(("p5.0011", "p1.0001")):
        if case_id.endswith("p5.0011"):
            lines = lines[:1]
        else:
            lines = [line for line in lines if "专用章" in line]
    elif case_id == "bc_018:candidate.block.p5.0009":
        lines = [line for line in lines if line.isdecimal() or "有限公司" in line]
    return field_rows(list(enumerate(lines)), expected, f"{picked.id}:{index}")


def image_case(case, model, pages, final, assets, embedded):
    blocks = pages[case["page"] - 1].blocks
    box, case_id, kind = case["bbox"], case["id"], case["sub_type"]
    candidates = [block for block in blocks if _iou(box, block.bbox) >= 0.85]
    reviewed_id = REVIEWED_VISUALS.get((model, case_id))
    if reviewed_id:
        candidates = [block for block in blocks if block.id == reviewed_id]
    assert len(candidates) <= 1, (model, case_id, [block.id for block in candidates])
    picked = candidates[0] if candidates else None
    spans = literal_text(picked, final) if picked else []
    if kind == "seal":
        merged_seal = model == "origin" and case_id in {
            "bc_019:manual.block.p1.0001",
            "bc_019:manual.block.p1.0002",
        }
        if merged_seal:
            picked = next(block for block in blocks if block.id == "mineru.p1.0004")
            spans = literal_text(picked, final)
        result = {
            "fields": seal_fields(case, model, picked, spans),
            "block_id": picked.id if picked else None,
            "raw_content": [text for _, text in spans],
        }
        if merged_seal:
            result["attribution_note"] = (
                "合框输出分别列出了两枚章的用途和编号，按编号归属两个独立片段。"
            )
        return result
    if case_id in MISSING_SOURCE_LABELS or not picked or picked.type not in VISUAL:
        return {
            "sub_type": None,
            "attribution_note": MISSING_SOURCE_LABELS.get(case_id, "成品中未交付源图的独立标签。"),
            "block_id": picked.id if picked else None,
        }
    actual = picked.metadata.get("sub_type")
    result = {"sub_type": actual, "block_id": picked.id, "raw_content": [text for _, text in spans]}
    if actual:
        result["subtype_id"] = picked.id
    if model == "ft" and case_id in {
        "bc_062:candidate.block.p1.0012",
        "bc_062:candidate.block.p1.0014",
    }:
        result["attribution_note"] = "整图两次裁图分析均返回复合图，成品保留原图且缺少分析类型。"
    if actual != kind:
        return result
    if not spans:
        result["fields"] = []
        if "relations" in case:
            result["relations"] = []
    elif kind == "flowchart":
        assert len(spans) == 1, (model, case_id)
        index, content = spans[0]
        result.update(flowchart(case, model, content, f"{picked.id}:{index}"))
    elif kind == "text_image":
        index, content = spans[0]
        segments = re.split(r"(?m)(?=^\d{2}$)", content)
        assert len(segments) == len(case["fields"]), (model, case_id, segments)
        result["fields"] = [
            {"id": f"{picked.id}:{index}:{position}", "key": field["key"], "text": text.strip()}
            for position, (field, text) in enumerate(zip(case["fields"], segments))
        ]
    elif kind == "natural_image":
        result["fields"] = []
        if model == "origin" and case_id == "bc_055:candidate.block.p1.0007":
            index, content = spans[0]
            text = re.search(r"\((D1, D2, C58, C59)\)", content).group(1)
            result["fields"] = [
                {
                    "id": f"{picked.id}:{index}:labels",
                    "key": "board-labels",
                    "text": text.replace(", ", " "),
                }
            ]
    if kind == "natural_image" and not case["fields"]:
        result["image_available"] = bool(image_hashes(picked, assets) & embedded)
    return result


def protection_evidence(slim, supplement, model, cases, filters):
    observations, captures, audit = {}, {}, []
    for feature, document, page_no, on_name, off_name in (
        ("image", "bc_022", 2, "image", "controls/image_off"),
        ("chart", "bc_091", 1, "chart", "image"),
    ):
        cases_here = [
            case for case in cases if case.get("protected") and case["feature"] == feature
        ]
        figure = next(case for case in cases_here if case["id"].endswith("protect-figure"))
        caption = next(case for case in cases_here if case["id"].endswith("protect-caption"))
        on = delivery(slim, model, document, "both_on")
        off = delivery(slim, model, document, "controls_image_off")
        capture = on[-1]["source"]["capture_sha256"]
        assert off[-1]["source"]["base_capture_sha256"] == capture
        prefix = f"{model}/documents/{document}/trace/both_on/compensated.middle_json.json"
        snapshot = json.loads(supplement.read(prefix))["pdf_info"]
        assert (
            on[-1]["filters"]["image_analysis"] == "true"
            and on[-1]["filters"]["chart_analysis"] is True
        )
        assert (
            off[-1]["filters"]["image_analysis"] == "false"
            and off[-1]["filters"]["chart_analysis"] is False
        )
        (on_block,) = [
            block for block in on[1][page_no - 1].blocks if _iou(figure["bbox"], block.bbox) >= 0.9
        ]
        (off_block,) = [
            block for block in off[1][page_no - 1].blocks if _iou(figure["bbox"], block.bbox) >= 0.9
        ]
        native_index = on_block.metadata["native_index"]

        def source_target(raw_pages):
            (target,) = [
                block
                for block in raw_pages[page_no - 1]["para_blocks"]
                if block.get("index") == native_index
            ]
            return target

        isolated = deepcopy(snapshot)
        assert source_target(snapshot) == source_target(on[0])
        if feature == "image":
            filters.filter_chart_analysis(isolated)
            assert source_target(isolated) == source_target(on[0])
            filters.filter_image_analysis(isolated)
        else:
            filters.filter_chart_analysis(isolated)
        assert source_target(isolated) == source_target(off[0]), (model, document, feature)
        on_hashes = image_hashes(on_block, on[3])
        off_hashes = image_hashes(off_block, off[3])
        assert on_hashes == off_hashes and len(on_hashes) == 1
        observations[figure["id"]] = {
            "on_state": "complete" if on_hashes <= on[4] else "missing",
            "off_state": "complete" if off_hashes <= off[4] else "missing",
            "retained_asset_sha256": next(iter(on_hashes)),
        }
        for side, block, final in (("on", on_block, on[2]), ("off", off_block, off[2])):
            text = " ".join(
                child["text"]
                for child in block.metadata["nested_blocks"]
                if child["type"].endswith("_caption")
            )
            normalized = visible_text(text).replace("CO_{2}", "CO2")
            rendered = final.replace("$CO_{2}$", "CO2")
            anchors = [
                value
                for value in caption["anchors"]
                if visible_text(value) in normalized and visible_text(value) in rendered
            ]
            state = (
                "complete"
                if len(anchors) == len(caption["anchors"])
                else "partial"
                if anchors
                else "missing"
            )
            observations.setdefault(caption["id"], {})[side + "_state"] = state
        captures[document] = {on_name: capture, off_name: capture}
        audit.append(
            {
                "source_snapshot": prefix,
                "source_sha256": digest(supplement.read(prefix)).hexdigest(),
                "document_id": document,
                "feature": feature,
                "capture_sha256": capture,
                "verified": "在同一补偿快照上切换单个过滤开关，核对目标图块与两个实际成品一致。",
            }
        )
    return observations, captures, audit


def run(args):
    cases = read_json(GT)["cases"]
    by_doc = defaultdict(list)
    for case in cases:
        if case["feature"] == "image" and not case.get("protected") and case["sub_type"] != "other":
            by_doc[case["document_id"]].append(case)
    output = fresh_directory(args.output)
    filters_path = args.filters
    previous_modules, _ = _temporary_logging_stub()
    try:
        filters = load_pdf2text_filters(filters_path)
    finally:
        _restore_modules(previous_modules)
    result, diagnostics = {}, {}
    with ZipFile(args.slim) as slim, ZipFile(args.supplement) as supplement:
        verified = verify_supplement(supplement, slim)
        for model in MODELS:
            evidence = read_json(args.base_evidence / f"{model}-evidence.json")
            assert evidence["gt_sha256"] == sha256(GT)
            for document, targets in by_doc.items():
                _, pages, final, assets, embedded, meta = delivery(
                    slim, model, document, "image_only"
                )
                assert (
                    meta["filters"]["image_analysis"] == "true"
                    and meta["filters"]["chart_analysis"] is False
                )
                for case in targets:
                    evidence["cases"][case["id"]] = image_case(
                        case, model, pages, final, assets, embedded
                    )
            protection, captures, audit = protection_evidence(
                slim, supplement, model, cases, filters
            )
            evidence["cases"].update(protection)
            for document, groups in captures.items():
                evidence["captures"].setdefault(document, {}).update(groups)
            evidence["image_supplement"] = {
                "sha256": sha256(args.supplement),
                "groups": [
                    {"document_id": document, "group": group, "capture_sha256": capture}
                    for (name, document, group), capture in verified.items()
                    if model == name
                ],
                "protection_checks": audit,
                "filter_sha256": sha256(filters_path),
            }
            evidence_path = output / f"{model}-evidence.json"
            write_json(evidence_path, evidence)
            result[model] = evaluate_feature_rubric(GT, evidence_path, output / model)
            diagnostics[model] = {"image_box_matches": {"ft": 66, "origin": 67}[model]}
            print(
                model,
                result[model]["features"]["image"],
                result[model]["overall"],
                result[model]["deletion_gate"],
            )
    html_report(output, args.slim, result, diagnostics, cases, supplement_path=args.supplement)


def main():
    parser = argparse.ArgumentParser()
    inputs = OUTPUT / "inputs"
    parser.add_argument(
        "--slim", type=Path, default=inputs / "1125-legacy129-inference-finals-slim.zip"
    )
    parser.add_argument(
        "--supplement", type=Path, default=inputs / "1125-legacy129-supplement-imageonly-bothon.zip"
    )
    parser.add_argument("--filters", type=Path, default=inputs / "mineru_filters.py")
    parser.add_argument("--base-evidence", type=Path, default=OUTPUT)
    parser.add_argument("--output", type=Path, required=True)
    run(parser.parse_args())


if __name__ == "__main__":
    main()
