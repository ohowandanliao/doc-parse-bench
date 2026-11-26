"""Score the reviewed chart pilot using the literal data in replayed tables."""

from __future__ import annotations

import argparse
import re
import unicodedata
from collections import defaultdict
from pathlib import Path

from bs4 import BeautifulSoup
from markdown_it import MarkdownIt

from ...io import fresh_directory, read_json, sha256, write_json
from ...schema import Block, Document
from ..feature_eval import _iou
from ..feature_matrix import _match
from ..feature_rubric import CONFIG, EVIDENCE_SCHEMA, evaluate_feature_rubric

HEADER_WITH_UNIT = re.compile(r"(.*?)\s*\(([^()]*)\)")
BARE_UNITS = {"万人", "缺陷数/千功能点"}
ROW_LABELS = {"category", "group", "year", "类别", "年份", "支出类别"}


def chart_observation(block: Block, markdown: MarkdownIt) -> dict:
    payload = block.html or block.text
    if not payload.strip():
        return {"table_status": "missing", "block_id": block.id}
    tables = BeautifulSoup(markdown.render(payload), "html.parser").find_all("table")
    if len(tables) != 1:
        return {"table_status": "unparseable", "block_id": block.id, "payload": payload}
    matrix = [
        [
            unicodedata.normalize("NFKC", cell.get_text(" ", strip=True))
            for cell in row.find_all(["th", "td"])
        ]
        for row in tables[0].find_all("tr")
    ]
    if len(matrix) < 2 or len(matrix[0]) < 2 or any(len(row) != len(matrix[0]) for row in matrix):
        return {"table_status": "unparseable", "block_id": block.id, "payload": payload}
    headers, *rows = matrix
    points = []
    for column, header in enumerate(headers[1:], start=1):
        explicit = HEADER_WITH_UNIT.fullmatch(header)
        if explicit:
            series, unit = explicit.groups()
        elif header in BARE_UNITS:
            series = (
                headers[0] if len(headers) == 2 and headers[0].lower() not in ROW_LABELS else ""
            )
            unit = header
        else:
            series = header
            unit = "%" if all(row[column].endswith("%") for row in rows) else ""
        for row_number, row in enumerate(rows, start=1):
            if not row[column]:
                continue
            category = row[0]
            if headers[0].lower() in {"year", "年份"} and re.fullmatch(r"[0-9]{4}", category):
                category += "年"
            points.append(
                {
                    "id": f"{block.id}:{row_number}:{column}",
                    "column_id": f"{block.id}:{column}",
                    "series": series,
                    "category": category,
                    "unit": unit,
                    "value": row[column],
                }
            )
    return {"table_status": "parsed", "block_id": block.id, "payload": payload, "values": points}


def collect(
    cases: list[dict], input_dirs: tuple[Path, ...], markdown: MarkdownIt
) -> tuple[dict, dict]:
    by_document = defaultdict(list)
    for case in cases:
        by_document[case["document_id"]].append(case)
    observations, sources = {}, {}
    for document_id, expected in by_document.items():
        candidates = [root / "chart" / "documents" / f"{document_id}.json" for root in input_dirs]
        path = next(path for path in candidates if path.is_file())
        document = Document.load(path)
        if document.id != document_id or not {case["page"] for case in expected} <= {
            page.number for page in document.pages
        }:
            raise ValueError(f"Wrong document or missing page: {path}")
        sources[document_id] = {"file": str(path.resolve()), "sha256": sha256(path)}
        predicted = [
            (page.number, block)
            for page in document.pages
            for block in page.blocks
            if block.type == "chart"
        ]
        pairs = {case["id"]: block for case, block in _match(expected, predicted, visual=True)}
        for case in expected:
            block = pairs.get(case["id"])
            nearby = [
                candidate
                for page, candidate in predicted
                if page == case["page"] and _iou(case["bbox"], candidate.bbox) >= 0.25
            ]
            if not nearby:
                observations[case["id"]] = {"table_status": "missing"}
            elif len(nearby) == 1 and block is nearby[0] and _iou(case["bbox"], block.bbox) >= 0.9:
                observations[case["id"]] = chart_observation(block, markdown)
            else:
                raise ValueError(
                    f"Ambiguous chart attribution needs review: {case['id']} in {path}"
                )
    return observations, sources


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pilot-gt", type=Path, required=True)
    parser.add_argument("--p2t-replay", type=Path, required=True)
    parser.add_argument("--legacy-origin", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = fresh_directory(args.output)
    pilot = read_json(args.pilot_gt)
    if pilot["split"] != "calibration":
        raise ValueError("This replay is only for the calibration pilot")
    charts = [case for case in pilot["cases"] if case["feature"] == "chart" and case.get("values")]
    markdown = MarkdownIt("commonmark", {"html": True}).enable("table")
    variants = {
        "ft-before": (args.p2t_replay / "ft-before",),
        "ft-package": (args.p2t_replay / "ft-package",),
        "ft-all-split": (args.p2t_replay / "ft-all-split",),
        "ft-adapted": (args.p2t_replay / "ft-adapted",),
        "origin": (args.p2t_replay / "origin-6docs", args.legacy_origin),
    }
    for scope, cases in (
        ("all-pilot-charts", charts),
        (
            "bar-and-wind-controls",
            [case for case in charts if case["document_id"] in {"bc_022", "bc_091"}],
        ),
    ):
        folder = output / scope
        gt_path = folder / "gt.json"
        write_json(
            gt_path, pilot | {"cases": cases, "base_rubric_gt_sha256": sha256(args.pilot_gt)}
        )
        for variant, roots in variants.items():
            if variant in {"ft-package", "ft-all-split"} and not roots[0].is_dir():
                continue
            evidence_path = folder / f"{variant}-evidence.json"
            observations, sources = collect(cases, roots, markdown)
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
                    "ir_sources": sources,
                },
            )
            metrics = evaluate_feature_rubric(gt_path, evidence_path, folder / variant)
            print(scope, variant, metrics["features"]["chart"])


if __name__ == "__main__":
    main()
