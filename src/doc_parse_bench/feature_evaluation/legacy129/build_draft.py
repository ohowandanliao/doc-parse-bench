"""Build a source-only annotation draft from legacy-129 PDFs, v3, and review batches."""

import argparse
import json
import math
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

from pypdfium2 import PdfDocument

from ...io import read_json, sha256, write_json
from ...schema import Block, Document, Page
from ..feature_eval import _service_appendix_start
from ..feature_rubric import CONFIG, EVIDENCE_SCHEMA, _text, score_feature_rubric

ROOT = Path(__file__).resolve().parents[4]
OUTPUT = ROOT / "artifacts/legacy129-formal-gt-review-20261125"
STRUCTURE = ROOT / "artifacts/legacy-features-20261119/records.json"
PILOT = STRUCTURE.with_name("rubric-pilot-gt.json")
PDFS = ROOT / "data/legacy/dataset/pdf/source"
VISUAL_GROUPS = {"image_only_blocks": "image", "seal_blocks": "image", "chart_blocks": "chart"}


def normalized(value):
    return unicodedata.normalize("NFC", value)


def visual_key(case):
    return case["document_id"], case["page"], case["source_id"]


def source_case(record, feature, page, source_id=None):
    document_id = record["document_id"]
    suffix = source_id or f"p{page}:margins"
    result = {
        "id": f"{document_id}:{suffix}",
        "document_id": document_id,
        "source_pdf": f"{record['source_name']}.pdf",
        "page": page,
        "feature": feature,
    }
    if source_id is not None:
        result["source_id"] = source_id
    return result


def save_crop(image, bbox, output):
    left, top, right, bottom = bbox
    width, height = image.size
    padding = 4
    box = (
        max(0, math.floor(left * width) - padding),
        max(0, math.floor(top * height) - padding),
        min(width, math.ceil(right * width) + padding),
        min(height, math.ceil(bottom * height) + padding),
    )
    if box[0] >= box[2] or box[1] >= box[3]:
        raise ValueError(f"Invalid crop bounds for {output.name}: {bbox}")
    with image.crop(box) as crop:
        crop.save(output)


def build_appendix_cases(records, pilot):
    records_by_id = {record["document_id"]: record for record in records}
    pages_to_remove = {}
    for document_id, record in records_by_id.items():
        structure = record["new_gt"]
        pages = [Page(number) for number in range(1, structure["pages"] + 1)]
        for title in structure["title_blocks"]:
            pages[title["page"] - 1].blocks.append(Block(title["id"], "title", title["text"]))
        start = _service_appendix_start(Document(document_id, pages))
        pages_to_remove[document_id] = list(range(start, len(pages) + 1)) if start else []

    original = [case for case in pilot["cases"] if case["feature"] == "appendix"]
    for item in read_json(OUTPUT / "appendix-protections.json")["cases"]:
        record = records_by_id[item["document_id"]]
        case = source_case(record, "appendix", item["page"], item["source_id"])
        original.append(case | item | {"protected": True})

    cases = []
    for source in original:
        case = dict(source)
        document_id, page = case["document_id"], case["page"]
        suffix = pages_to_remove[document_id]
        if page in suffix and case.get("protected"):
            case.pop("protected")
            case.pop("source_id")
            case["id"] = f"{document_id}:p{page}:appendix"
            case["scope_note"] = f"旧版从第 {suffix[0]} 页截断到文末，本页属于截断范围。"
        elif page not in suffix and not case.get("protected"):
            case.update(
                id=f"{document_id}:p{page}:protect-before-cutoff",
                source_id=f"p{page}:截断前内容",
                protected=True,
                scope_note="旧版在后半段命中附录标题，本页位于截断起点之前，两个开关状态均应保留。",
            )
        cases.append(case)

    anchors_by_document = defaultdict(set)
    for case in cases:
        if not case.get("protected") and case.get("anchors"):
            anchors_by_document[case["document_id"]].add(case["page"])
    for document_id, pages in pages_to_remove.items():
        if anchors_by_document[document_id] != set(pages):
            raise ValueError(f"Appendix anchors do not cover the legacy cutoff for {document_id}")
    return cases, pages_to_remove


def prepare(records, pilot, appendix_gt, pages_to_remove):
    pdfs = {normalized(path.stem): path for path in PDFS.glob("*.pdf")}
    pilot_margins = {
        (case["document_id"], case["page"]): case
        for case in pilot["cases"]
        if case["feature"] == "header_footer" and not case.get("protected")
    }
    appendix_cases = defaultdict(list)
    for case in appendix_gt:
        if not case.get("protected"):
            appendix_cases[case["document_id"]].append(case)
    documents, edges, margins, appendix = [], [], [], []
    crops = OUTPUT / "margin-crops"
    crops.mkdir(exist_ok=True)
    for record in records:
        document_id = record["document_id"]
        structure = record["new_gt"]
        source = pdfs[normalized(record["source_name"])]
        by_page = defaultdict(list)
        for block in structure["marginal_blocks"]:
            by_page[block["page"]].append(
                {key: block[key] for key in ("id", "type", "text", "bbox")}
            )
        appendix_pages = pages_to_remove[document_id]
        with PdfDocument(source) as pdf:
            if len(pdf) != structure["pages"]:
                raise ValueError(f"Page count differs: {source.name}")
            documents.append(
                {
                    "document_id": document_id,
                    "source_pdf": f"{record['source_name']}.pdf",
                    "pdf_sha256": sha256(source),
                    "pages": len(pdf),
                    "appendix_pages": appendix_pages,
                    "margin_pages": sorted(by_page),
                }
            )
            for case in appendix_cases[document_id]:
                page = pdf[case["page"] - 1]
                text_page = page.get_textpage()
                text = _text(text_page.get_text_bounded())
                appendix.append(
                    {
                        "case_id": case["id"],
                        "anchors_matching_text_layer": [
                            anchor for anchor in case["anchors"] if _text(anchor) in text
                        ],
                        "anchors": case["anchors"],
                    }
                )
                text_page.close()
                page.close()
            for page_number, blocks in sorted(by_page.items()):
                pilot_case = pilot_margins.get((document_id, page_number))
                reviewed = (
                    {block["id"]: block for block in pilot_case["blocks"]} if pilot_case else {}
                )
                candidate = source_case(record, "header_footer", page_number)
                candidate["blocks"] = [reviewed.get(block["id"], block) for block in blocks]
                edges.append(candidate)
                page = pdf[page_number - 1]
                width, height = page.get_size()
                text_page = page.get_textpage()
                pending = []
                for block in candidate["blocks"]:
                    left, top, right, bottom = block["bbox"]
                    source_text = text_page.get_text_bounded(
                        left * width, (1 - bottom) * height, right * width, (1 - top) * height
                    )
                    status = "check_original"
                    if block["id"] in reviewed:
                        status = "pilot_review"
                    elif block.get("text") and _text(block["text"]) == _text(source_text):
                        status = "pdf_text_matches"
                    row = {
                        "case_id": candidate["id"],
                        "block": block,
                        "pdf_text": source_text,
                        "status": status,
                    }
                    margins.append(row)
                    if status == "check_original":
                        pending.append(row)
                if pending:
                    bitmap = page.render(scale=4)
                    with bitmap.to_pil() as image:
                        for row in pending:
                            block = row["block"]
                            name = f"{document_id}__p{page_number:03d}__{block['id']}.png"
                            save_crop(image, block["bbox"], crops / name)
                            row["crop"] = f"margin-crops/{name}"
                    bitmap.close()
                text_page.close()
                page.close()
    write_json(
        OUTPUT / "sources.json",
        {
            "structure_sha256": sha256(STRUCTURE),
            "pilot_sha256": sha256(PILOT),
            "documents": documents,
        },
    )
    write_json(OUTPUT / "margin-draft.json", {"cases": edges, "blocks": margins})
    write_json(OUTPUT / "appendix-source-check.json", {"pages": appendix})
    print(
        json.dumps(
            {
                "documents": len(documents),
                "appendix_pages": len(appendix),
                "margin_pages": len(edges),
                "margin_blocks": dict(Counter(row["status"] for row in margins)),
            },
            ensure_ascii=False,
        )
    )


def apply_margin_review(margin_draft, ocr, decisions):
    blocks_by_key = {
        (case["id"], block["id"]): block
        for case in margin_draft["cases"]
        for block in case["blocks"]
    }
    for row in margin_draft["blocks"]:
        if row["status"] != "check_original":
            continue
        name = Path(row["crop"]).name
        block = row["block"]
        evidence = ocr.get(name, "")
        if evidence:
            row["ocr_text"] = evidence
        decision = decisions.pop(name, None)
        if decision is not None:
            row["status"] = "visual_review"
            revision = decision
            row["review"] = decision
        elif evidence and _text(evidence) == _text(block["text"]):
            row["status"] = "ocr_matches"
            revision = {}
        elif row["pdf_text"].strip() and _text(evidence) == _text(row["pdf_text"]):
            row["status"] = "pdf_and_ocr_agree"
            revision = {"text": row["pdf_text"].strip()}
        else:
            continue
        blocks_by_key[row["case_id"], block["id"]].update(revision)
    if decisions:
        raise ValueError(f"Unmatched margin decisions: {list(decisions)}")


def check_sources(cases, records_by_id):
    for case in cases:
        source = records_by_id[case["document_id"]]
        if case["source_pdf"] != f"{source['source_name']}.pdf":
            raise ValueError(f"PDF name differs for {case['id']}")
        if type(case["page"]) is not int or not 1 <= case["page"] <= source["new_gt"]["pages"]:
            raise ValueError(f"Page outside PDF bounds for {case['id']}")
        if case.get("protected") or case["feature"] == "appendix":
            if "anchors" in case and not all(_text(anchor) for anchor in case["anchors"]):
                raise ValueError(f"Invalid anchor for {case['id']}")
        if case["feature"] == "image" and not case.get("protected") and case["sub_type"] != "other":
            if not all(_text(field["text"]) for field in case["fields"]):
                raise ValueError(f"Empty image field for {case['id']}")


def assemble(records, pilot, appendix_gt, pages_to_remove, args):
    pilot_visual = {
        visual_key(case): case
        for case in pilot["cases"]
        if case["feature"] in {"image", "chart"} and not case.get("protected")
    }
    reviews = {}
    for path in args.review:
        for review in read_json(path)["cases"]:
            key = visual_key(review)
            if key in reviews or key in pilot_visual:
                raise ValueError(f"Duplicate source in review {path.name}: {key}")
            reviews[key] = (path.stem, review)
    for path in args.follow_up:
        for review in read_json(path)["cases"]:
            key = visual_key(review)
            if key not in reviews:
                raise ValueError(f"Follow-up requires an initial review: {key}")
            prior_batch, prior_review = reviews[key]
            reviews[key] = (
                path.stem,
                review | {"previous_batch": prior_batch, "previous_review": prior_review},
            )
    cases = [
        case for case in pilot["cases"] if case.get("protected") and case["feature"] != "appendix"
    ]
    cases.extend(appendix_gt)
    margin_draft = read_json(OUTPUT / "margin-draft.json")
    margin_ocr = read_json(args.margin_ocr) if args.margin_ocr else {}
    margin_review = read_json(args.margin_review) if args.margin_review else {}
    apply_margin_review(margin_draft, margin_ocr, margin_review)
    cases.extend(margin_draft["cases"])
    records_by_id = {record["document_id"]: record for record in records}
    source_manifest = read_json(OUTPUT / "sources.json")
    if {
        row["document_id"]: row["appendix_pages"] for row in source_manifest["documents"]
    } != pages_to_remove:
        raise ValueError("The source manifest has a different appendix scope. Run --prepare first.")
    visual_audit = []
    for record in records:
        for group, feature in VISUAL_GROUPS.items():
            for block in record["new_gt"][group]:
                case = source_case(record, feature, block["page"], block["id"])
                case["bbox"] = block["bbox"]
                key = visual_key(case)
                if key in pilot_visual:
                    reference = pilot_visual.pop(key)
                    cases.append(reference)
                    visual_audit.append(
                        case
                        | {
                            "status": "pilot_review",
                            "score_scope": "diagnostic"
                            if reference.get("sub_type") == "other"
                            or feature == "chart"
                            and not reference["values"]
                            else "main",
                        }
                    )
                    continue
                batch, review = reviews.pop(key, (None, {"status": "unreviewed"}))
                status = review["status"]
                if status not in {"proposed", "diagnostic", "needs_review", "unreviewed"}:
                    raise ValueError(f"Unknown review state for {key}: {status}")
                visual_audit.append(case | {"status": status, "batch": batch, "review": review})
                if status in {"needs_review", "unreviewed"}:
                    continue
                keep = (
                    ("values", "unscored", "scope_note")
                    if feature == "chart"
                    else ("sub_type", "fields", "relations", "readability", "scope_note")
                )
                case.update({field: review[field] for field in keep if field in review})
                if status == "diagnostic":
                    if feature == "image":
                        original_subtype = case.get("sub_type")
                        case.update(sub_type="other", fields=[], reviewed_subtype=original_subtype)
                        case.pop("relations", None)
                    else:
                        case["values"] = []
                cases.append(case)
    if reviews or pilot_visual:
        raise ValueError(f"Review targets absent from v3: {list(reviews) + list(pilot_visual)}")
    feature_order = {"appendix": 0, "header_footer": 1, "image": 2, "chart": 3}
    cases.sort(
        key=lambda case: (
            case["document_id"],
            case["page"],
            feature_order[case["feature"]],
            case["id"],
        )
    )
    visual_pending = [
        item["id"] for item in visual_audit if item["status"] in {"needs_review", "unreviewed"}
    ]
    margin_pending = sum(row["status"] == "check_original" for row in margin_draft["blocks"])
    if args.finalize and (visual_pending or margin_pending):
        raise ValueError(f"Open reviews: visual={visual_pending!r}, margin={margin_pending}")
    check_sources(cases, records_by_id)
    ground_truth = {
        "schema_version": pilot["schema_version"],
        "gt_version": pilot["gt_version"],
        "split": "evaluation" if args.finalize else "calibration",
        "review_status": "reviewed" if args.finalize else "draft",
        "appendix_policy": "MinerU3 8b747ca 的附录标题截断规则",
        "source_files": {
            "structure_sha256": sha256(STRUCTURE),
            "pilot_sha256": sha256(PILOT),
            "sources_sha256": sha256(OUTPUT / "sources.json"),
        },
        "cases": cases,
    }
    validated = score_feature_rubric(
        ground_truth,
        {
            "schema_version": EVIDENCE_SCHEMA,
            "stage": "replay",
            "model": "draft-schema-check",
            "config": CONFIG,
            "cases": {},
            "captures": {},
        },
    )
    assert validated["overall"] is None
    filename = "rubric-evaluation-gt.json" if args.finalize else "rubric-draft-gt.json"
    write_json(OUTPUT / filename, ground_truth)
    pending = {
        "visual_targets": visual_audit,
        "margin_blocks": margin_draft["blocks"],
        "summary": {
            "visual_review": {
                feature: dict(
                    Counter(item["status"] for item in visual_audit if item["feature"] == feature)
                )
                for feature in ("image", "chart")
            },
            "margin_review": dict(Counter(item["status"] for item in margin_draft["blocks"])),
            "denominators": {
                feature: item["denominator"] for feature, item in validated["features"].items()
            },
        },
    }
    write_json(OUTPUT / "review-status.json", pending)
    print(json.dumps(pending["summary"], ensure_ascii=False, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepare", action="store_true")
    parser.add_argument("--finalize", action="store_true")
    parser.add_argument("--review", action="append", type=Path, default=[])
    parser.add_argument("--follow-up", action="append", type=Path, default=[])
    parser.add_argument("--margin-ocr", type=Path)
    parser.add_argument("--margin-review", type=Path)
    args = parser.parse_args()
    records = read_json(STRUCTURE)["records"]
    pilot = read_json(PILOT)
    appendix_gt, pages_to_remove = build_appendix_cases(records, pilot)
    if args.prepare:
        prepare(records, pilot, appendix_gt, pages_to_remove)
    else:
        assemble(records, pilot, appendix_gt, pages_to_remove, args)


if __name__ == "__main__":
    main()
