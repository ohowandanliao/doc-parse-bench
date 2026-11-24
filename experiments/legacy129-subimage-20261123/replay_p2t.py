"""Compare the packaged policy, all-split and the P2T pre-crop rule on legacy 129."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import logging
from collections import Counter, defaultdict
from copy import deepcopy
from dataclasses import asdict
from pathlib import Path
from unittest.mock import patch

import structlog
from pdf2text.config.settings import MinerUConfig
from pdf2text.core.parse import mineru_filters, mineru_subimages
from pdf2text.core.parse.mineru_client import _replace_images_with_base64, render_mineru_markdown

from doc_parse_bench.feature_matrix import (
    GROUPS,
    REPLAY_SCHEMA,
    _ground_truth,
    _raw_path,
    evaluate_feature_matrix,
)
from doc_parse_bench.io import fresh_directory, read_json, sha256, write_json
from doc_parse_bench.mineru_middle import _mark_raw_types, extract_pdf_info, pdf_info_to_document
from doc_parse_bench.schema import Document

VARIANTS = (
    ("ft-before", "ft/raw-B-original", "none"),
    ("ft-package", "ft/raw-B-expanded", "package"),
    ("ft-all-split", "ft/raw-B-original", "all_split"),
    ("ft-adapted", "ft/raw-B-original", "pre_crop"),
    ("origin-6docs", "origin/raw-B-6docs", "none"),
)


def _mark_capture_ids(pages: list[dict]) -> None:
    for page in pages:
        for key in ("para_blocks", "discarded_blocks"):
            for position, block in enumerate(page.get(key) or []):
                block["_docbench_raw_id"] = (
                    block.get("id") or block.get("block_id") or f"capture.p{page['page_idx'] + 1}.{key}.{position}"
                )


def _mark_crop_ids(pages: list[dict]) -> None:
    for page in pages:
        for block in page.get("para_blocks") or []:
            if not block.get("subimage_expanded"):
                continue
            identity = json.dumps(block["bbox"], separators=(",", ":"))
            digest = hashlib.sha256(identity.encode("ascii")).hexdigest()
            block["_docbench_raw_id"] = f"crop.p{page['page_idx'] + 1}.{digest}"


def unchanged_blocks(document: Document, parent_indices: set[tuple[int, int]]) -> list:
    return [
        (page.number, page.width, page.height, [
            (block.type, block.bbox, block.text, block.html, block.level, block.metadata)
            for block in page.blocks
            if (type(block.metadata["native_index"]) is not int
                or (page.number, block.metadata["native_index"]) not in parent_indices)
            and not any("subimage_source" in span for span in block.metadata["spans"])
        ])
        for page in document.pages
    ]


async def replay(args: argparse.Namespace) -> None:
    pack, gt = args.pack, args.gt
    review = pack / "review"
    output = fresh_directory(args.output)
    budget = MinerUConfig()
    manifest, records, gt_hashes = _ground_truth(gt)
    rows = read_json(review / "analysis.json")
    affected = {row["gt_document_id"] for row in rows}
    crop_rows = {}
    for row in rows:
        digest = sha256(review / row["crop_path"])
        if digest != row["crop_sha256"] or digest in crop_rows:
            raise ValueError(f"Unexpected crop SHA-256: {row['crop_path']}")
        crop_rows[digest] = row
    package_decisions = read_json(review / "expansion.json")["documents"]
    package_runs = {
        info["gt_document_id"]: [
            {"page": parent["page"], "parent_index": parent["parent_index"], "panels": parent["sub_count"],
             "rule": parent["reason"], "requests": parent["sub_count"], "split": parent["decision"] == "split"}
            for parent in info["composites"]
        ]
        for info in package_decisions.values()
    }
    visual_groups = {group: switches for group, (capture, switches) in GROUPS.items() if capture == "B"}
    comparison = {}

    for name, raw_dir, policy in VARIANTS:
        target = output / name
        sources = {}
        requests = defaultdict(Counter)
        decisions = {group: {} for group in visual_groups}
        failures = []
        subset = name == "origin-6docs"
        for record in records:
            document_id = record["document_id"]
            if subset and document_id not in affected:
                continue
            raw = _raw_path(pack / raw_dir, record)
            response = read_json(raw)
            pages = extract_pdf_info(response)
            images = next(iter(response["results"].values()))["images"]
            if [page.get("page_idx") for page in pages] != list(range(record["new_gt"]["pages"])):
                raise ValueError(f"Page mismatch: {raw}")
            _mark_capture_ids(pages)
            sources[document_id] = {"B": {"file": raw.name, "sha256": sha256(raw)}}
            async def analyze_crop(jpeg: bytes) -> list[dict]:
                digest = hashlib.sha256(jpeg).hexdigest()
                try:
                    entry = crop_rows[digest]
                    if entry["gt_document_id"] != document_id:
                        raise ValueError(f"Crop associated with a different document: {digest}")
                    return extract_pdf_info(read_json(review / entry["analysis"]["response"]))
                except Exception as exc:
                    failures.append(f"{name}/{group}/{document_id}/{digest}: {exc}")
                    raise
                finally:
                    requests[group][digest] += 1

            for group, switches in visual_groups.items():
                filtered = deepcopy(pages)
                assets = images.copy()
                enabled = switches["image_analysis"] or switches["chart_analysis"]
                if policy == "package" and enabled and document_id in package_runs:
                    decisions[group][document_id] = package_runs[document_id]
                if policy == "all_split" and enabled:
                    with (
                        patch.object(mineru_subimages, "_split_rule", return_value="split_all_control"),
                        patch.object(mineru_subimages, "_split_supported", return_value=True),
                    ):
                        outcomes = await mineru_subimages.expand_subimages(
                            filtered, assets, analyze_crop, max_crops=len(crop_rows), timeout=120,
                            chart_analysis_enabled=switches["chart_analysis"],
                            image_analysis_enabled=switches["image_analysis"],
                        )
                    if outcomes:
                        decisions[group][document_id] = [asdict(outcome) for outcome in outcomes]
                if policy == "pre_crop" and enabled:
                    outcomes = await mineru_subimages.expand_subimages(
                        filtered, assets, analyze_crop, max_crops=budget.subimage_max_crops,
                        timeout=budget.subimage_timeout, chart_analysis_enabled=switches["chart_analysis"],
                        image_analysis_enabled=switches["image_analysis"],
                    )
                    if outcomes:
                        decisions[group][document_id] = [asdict(outcome) for outcome in outcomes]
                _mark_crop_ids(filtered)
                _mark_raw_types(filtered)
                mineru_filters.apply_filters(
                    filtered,
                    keep_header_footer_enabled=switches["keep_header_footer"],
                    remove_appendix=not switches["keep_appendix"],
                    image_analysis_enabled=switches["image_analysis"],
                    chart_analysis_enabled=switches["chart_analysis"],
                    preserve_printed_image_text=True,
                    relevel_titles_enabled=args.relevel_titles,
                    title_rules_enabled=False,
                )
                document = pdf_info_to_document(filtered, document_id=document_id, source=raw)
                document.dump(target / group / "documents" / f"{document_id}.json")
                if policy == "pre_crop":
                    baseline = Document.load(output / "ft-before" / group / "documents" / f"{document_id}.json")
                    parent_indices = {
                        (parent["page"], parent["parent_index"]) for parent in package_runs.get(document_id, [])
                    } if enabled else set()
                    if unchanged_blocks(document, parent_indices) != unchanged_blocks(baseline, parent_indices):
                        raise ValueError(f"Unrelated block or page changed: {group}/{document_id}")
                if document_id in affected:
                    rendered, _ = _replace_images_with_base64(render_mineru_markdown(filtered), assets)
                    rendered_path = target / group / "markdown" / f"{document_id}.md"
                    rendered_path.parent.mkdir(parents=True, exist_ok=True)
                    rendered_path.write_text(rendered, encoding="utf-8")

        if failures:
            raise ValueError("Crop cache could not be replayed:\n" + "\n".join(failures))
        expected_digests = Counter(crop_rows.keys())
        for group, switches in visual_groups.items():
            active = switches["image_analysis"] or switches["chart_analysis"]
            counts = requests[group]
            if policy == "all_split" and active and counts != expected_digests:
                raise ValueError(f"All-split control did not replay each crop once: {group}")
            if not counts <= expected_digests or (not active and counts):
                raise ValueError(f"Unexpected crop requests: {name}/{group}")
            if policy in {"all_split", "pre_crop"} and sum(counts.values()) != sum(
                parent["requests"] for parents in decisions[group].values() for parent in parents
            ):
                raise ValueError(f"Crop accounting mismatch: {name}/{group}")
        write_json(target / "manifest.json", {
            "schema_version": REPLAY_SCHEMA,
            "scope": "visual_only",
            "model": name,
            "gt_version": manifest["gt_version"],
            "gt_sha256": gt_hashes,
            "subsets": {key: list(sources) for key in ("union", "image", "chart")},
            "groups": {key: {"raw": mode, **switches} for key, (mode, switches) in GROUPS.items() if mode == "B"},
            "raw_sources": sources,
            "capture_package": str(pack.resolve()),
            "pdf2text_source_commit": "8b747ca",
            "pdf2text_filters_sha256": sha256(Path(mineru_filters.__file__)),
            "pdf2text_subimages_sha256": sha256(Path(mineru_subimages.__file__)),
            "pdf2text_target_config": {"mineru_provider": "mineru3", "relevel_titles": True, "title_rules": False},
            "relevel_applied": args.relevel_titles,
            "subimage_policy": policy,
            "subimage_limits": {"max_crops": budget.subimage_max_crops, "timeout": budget.subimage_timeout}
            if policy == "pre_crop" else None,
            "preserve_printed_image_text": "composite_only",
            "block_ids": "native or pre-split capture ID; new crops keyed by physical page and box",
            "stage": "content_filter_ir; markdown rendered for affected documents",
        })
        result = evaluate_feature_matrix(gt, target, output / f"{name}-scores")
        comparison[name] = {
            "metrics": result["metrics"],
            "groups": {
                group: {
                    "crop_requests": sum(parent["requests"] for parents in runs.values() for parent in parents),
                    "split_parents": sum(parent["split"] for parents in runs.values() for parent in parents),
                    "documents": runs,
                    "crop_response_sha256_keys": sorted(requests[group]),
                }
                for group, runs in decisions.items()
            },
        }
        print(name, {key: result["metrics"][key]["counts"] for key in ("image", "chart")}, flush=True)

    write_json(output / "split-comparison.json", comparison)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pack", type=Path, required=True)
    parser.add_argument("--gt", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--relevel-titles", action="store_true", help="Requires the deployed PaddleX title-level module")
    logging.getLogger("fast-langdetect").setLevel(logging.ERROR)
    structlog.configure(wrapper_class=structlog.make_filtering_bound_logger(logging.WARNING))
    asyncio.run(replay(parser.parse_args()))


if __name__ == "__main__":
    main()
