"""Apply the pilot rubric to the saved appendix and header/footer replay pairs."""

from __future__ import annotations

import argparse
from pathlib import Path

from bs4 import BeautifulSoup

from ...io import fresh_directory, read_json, sha256, write_json
from ...schema import Block, Document, Page
from ..feature_contract import PAIRS
from ..feature_eval import _iou
from ..feature_rubric import (
    CONFIG,
    EDGE_TYPES,
    EVIDENCE_SCHEMA,
    _text,
    evaluate_feature_rubric,
)


def _image(block: Block) -> bool:
    return any(span.get("image_path") for span in block.metadata.get("spans", []))


def _visible_text(block: Block) -> str:
    chunks = [block.text, block.html]
    for span in block.metadata.get("spans", []):
        if span.get("type") != "image" and span.get("generated") is not True:
            chunks.extend(span.get(key) or "" for key in ("content", "text", "html"))
    return " ".join(
        BeautifulSoup(chunk, "html.parser").get_text(" ") if "<" in chunk else chunk
        for chunk in chunks
    )


def _blocks(page: Page | None, case: dict) -> list[Block]:
    return (
        [
            block
            for block in page.blocks
            if not case.get("bbox") or _iou(case["bbox"], block.bbox) >= 0.2
        ]
        if page
        else []
    )


def _anchor_evidence(page: Page | None, case: dict) -> list[str]:
    text = _text(" ".join(map(_visible_text, _blocks(page, case))))
    return [anchor for anchor in case["anchors"] if _text(anchor) in text]


def _state(page: Page | None, case: dict) -> str:
    anchors = _anchor_evidence(page, case)
    return (
        "complete" if len(anchors) == len(case["anchors"]) else "partial" if anchors else "missing"
    )


def _overlaps_reference(box: list[float], block: Block) -> bool:
    if block.bbox is None:
        return False
    left, top, right, bottom = box
    other_left, other_top, other_right, other_bottom = block.bbox
    overlap = max(0, min(right, other_right) - max(left, other_left)) * max(
        0, min(bottom, other_bottom) - max(top, other_top)
    )
    return overlap >= 0.5 * (right - left) * (bottom - top)


def _margin_observation(case: dict, on: Page, off: Page) -> dict:
    delivered = []
    for block in on.blocks:
        kind = block.metadata.get("raw_type", block.type)
        if kind not in EDGE_TYPES:
            continue
        references = sorted(
            (
                entry
                for entry in case["blocks"]
                if entry["type"] == kind and _overlaps_reference(entry["bbox"], block)
            ),
            key=lambda entry: (entry["bbox"][1], entry["bbox"][0]),
        )
        row = {"id": block.id, "text": block.text, "image_available": _image(block)}
        if len(references) == 1:
            row["source_id"] = references[0]["id"]
        if len(references) > 1:
            words = block.text.split()
            sizes = [len(reference["text"].split()) for reference in references]
            if _text(block.text) == _text(
                " ".join(reference["text"] for reference in references)
            ) and sum(sizes) == len(words):
                start = 0
                for index, (reference, size) in enumerate(
                    zip(references, sizes, strict=True), start=1
                ):
                    delivered.append(
                        {
                            "id": f"{block.id}:{index}",
                            "source_id": reference["id"],
                            "text": " ".join(words[start : start + size]),
                        }
                    )
                    start += size
                continue
            raise ValueError(f"Ambiguous margin attribution: {case['id']}/{block.id}")
        delivered.append(row)

    remaining = []
    for entry in case["blocks"]:
        actual = [row["text"] for row in delivered if row.get("source_id") == entry["id"]]
        for block in off.blocks:
            if not _overlaps_reference(entry["bbox"], block):
                continue
            if entry["type"].endswith("_image"):
                residual = _image(block) and _iou(entry["bbox"], block.bbox) >= 0.5
            else:
                residual = any(
                    _text(target) in _text(_visible_text(block))
                    for target in [entry["text"], *actual]
                    if target
                )
            if residual:
                remaining.append(entry["id"])
                break
    return {"on_blocks": delivered, "off_residual_ids": remaining}


def collect(cases: list[dict], directory: Path) -> tuple[dict, dict, dict]:
    manifest = read_json(directory / "manifest.json")
    groups, captures, sources, observations = {}, {}, {}, {}
    for case in cases:
        document = case["document_id"]
        on_name, off_name = PAIRS[case["feature"]]
        for group in (on_name, off_name):
            if (document, group) in groups:
                continue
            raw_group = manifest["groups"][group]["raw"]
            captures.setdefault(document, {})[group] = manifest["raw_sources"][document][raw_group][
                "sha256"
            ]
            path = directory / group / "documents" / f"{document}.json"
            loaded = Document.load(path)
            if loaded.id != document:
                raise ValueError(f"Document does not match: {path}")
            groups[document, group] = {page.number: page for page in loaded.pages}
            sources.setdefault(document, {})[group] = {
                "file": str(path.resolve()),
                "sha256": sha256(path),
            }
        on, off = (groups[document, group].get(case["page"]) for group in (on_name, off_name))
        if case.get("protected"):
            observed = {"on_state": _state(on, case), "off_state": _state(off, case)}
        elif case["feature"] == "appendix":
            observed = {
                "on_anchors": _anchor_evidence(on, case),
                "off_residual": any(
                    _visible_text(block).strip() or _image(block) for block in _blocks(off, case)
                ),
            }
        else:
            if on is None or off is None:
                raise ValueError(f"Missing page for header/footer: {case['id']}")
            observed = _margin_observation(case, on, off)
        observations[case["id"]] = observed
    return observations, captures, sources


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pilot-gt", type=Path, required=True)
    parser.add_argument("--legacy-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = fresh_directory(args.output)
    pilot = read_json(args.pilot_gt)
    if pilot["split"] != "calibration":
        raise ValueError("This replay is only for the calibration pilot")
    cases = [case for case in pilot["cases"] if case["feature"] in {"appendix", "header_footer"}]
    gt_path = output / "gt.json"
    write_json(gt_path, pilot | {"cases": cases, "base_rubric_gt_sha256": sha256(args.pilot_gt)})
    for variant in ("ft", "origin"):
        observations, captures, sources = collect(cases, args.legacy_root / variant / "ir")
        evidence_path = output / f"{variant}-evidence.json"
        write_json(
            evidence_path,
            {
                "schema_version": EVIDENCE_SCHEMA,
                "gt_sha256": sha256(gt_path),
                "model": variant,
                "config": CONFIG,
                "stage": "replay",
                "relevel_applied": False,
                "cases": observations,
                "captures": captures,
                "ir_sources": sources,
            },
        )
        result = evaluate_feature_rubric(gt_path, evidence_path, output / variant)
        print(
            variant,
            result["features"]["appendix"],
            result["features"]["header_footer"],
            result["deletion_gate"],
        )


if __name__ == "__main__":
    main()
