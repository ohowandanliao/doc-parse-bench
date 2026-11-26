import json
from pathlib import Path

import pytest

from doc_parse_bench.feature_evaluation.feature_matrix import (
    _header_footer,
    build_feature_ir,
    evaluate_feature_matrix,
)
from doc_parse_bench.io import read_json, write_json
from doc_parse_bench.schema import Block, Document, Page

FILTER_SOURCE = Path(__file__).parent / "fixtures/mineru_filters.py"


def _response():
    page = {
        "page_idx": 0,
        "page_size": [1000, 1000],
        "para_blocks": [
            {
                "id": "header-1",
                "type": "header",
                "bbox": [100, 10, 400, 40],
                "lines": [{"spans": [{"type": "text", "content": "Header"}]}],
            },
            {
                "id": "image-1",
                "type": "image",
                "sub_type": "text_image",
                "bbox": [100, 100, 300, 300],
                "blocks": [
                    {
                        "type": "image_body",
                        "lines": [
                            {
                                "spans": [
                                    {
                                        "type": "image",
                                        "content": "generated description",
                                        "generated": True,
                                    }
                                ]
                            }
                        ],
                    }
                ],
            },
            {
                "id": "chart-1",
                "type": "chart",
                "bbox": [400, 400, 900, 800],
                "blocks": [
                    {
                        "type": "chart_body",
                        "lines": [{"spans": [{"type": "table", "content": "42"}]}],
                    }
                ],
            },
        ],
        "discarded_blocks": [],
    }
    return {
        "pages": 1,
        "results": {"sample.pdf": {"middle_json": json.dumps({"pdf_info": [page]})}},
    }


def _ground_truth(path: Path):
    write_json(
        path / "manifest.json",
        {
            "schema_version": "doc-parse-bench.feature-gt.v1",
            "gt_version": "legacy-129-feature-v3",
            "dataset_version": "test",
        },
    )
    write_json(
        path / "records.json",
        {
            "schema_version": "doc-parse-bench.feature-gt.v1",
            "records": [
                {
                    "document_id": "bc_001",
                    "source_name": "bc_001",
                    "old_gt": {"chart_content_candidate": True},
                    "new_gt": {
                        "pages": 1,
                        "appendix": {"pages": []},
                        "marginal_blocks": [{"page": 1, "type": "header", "text": "Header"}],
                        "header_footer_blocks": [{"page": 1, "type": "header", "text": "Header"}],
                        "page_number_blocks": [],
                        "image_blocks": [
                            {"page": 1, "type": "image", "bbox": [0.1, 0.1, 0.3, 0.3]}
                        ],
                        "image_only_blocks": [
                            {"page": 1, "type": "image", "bbox": [0.1, 0.1, 0.3, 0.3]}
                        ],
                        "seal_blocks": [],
                        "chart_blocks": [
                            {"page": 1, "type": "chart", "bbox": [0.4, 0.4, 0.9, 0.8]}
                        ],
                    },
                }
            ],
        },
    )


def test_build_and_score_feature_matrix_with_two_raw_sources(tmp_path):
    gt = tmp_path / "gt"
    _ground_truth(gt)
    raw_a = tmp_path / "raw-a"
    raw_b = tmp_path / "raw-b"
    write_json(raw_a / "bc_001.json", _response())
    write_json(raw_b / "bc_001.json", _response())

    replay = tmp_path / "replay"
    built = build_feature_ir(gt, raw_a, raw_b, FILTER_SOURCE, "mineru3", replay)
    assert built["documents"] == 1
    assert (replay / "off/documents/bc_001.json").is_file()
    assert (replay / "controls/image_off/documents/bc_001.json").is_file()

    result = evaluate_feature_matrix(gt, replay, tmp_path / "scores")
    assert result["metrics"]["header_footer"]["on_recall"]["rate"] == 1.0
    assert result["metrics"]["image"]["on_output_coverage"]["rate"] == 1.0
    assert result["metrics"]["image"]["content_output_recall"]["rate"] == 1.0
    assert result["metrics"]["chart"]["on_output_coverage"]["rate"] == 1.0
    assert result["metrics"]["chart"]["content_output_recall"]["rate"] == 1.0
    assert result["metrics"]["chart"]["off_downgrade_rate"]["rate"] == 1.0
    combined = result["metrics"]["combined_visual"]
    assert combined["strict_type"]["recall"]["rate"] == 1.0
    assert combined["location_only"]["output_coverage"]["rate"] == 1.0
    assert combined["counts"]["image_as_chart"] == 0


def test_visual_only_replay_uses_one_capture_and_keeps_subtype(tmp_path):
    gt = tmp_path / "gt"
    _ground_truth(gt)
    raw_b = tmp_path / "raw-b"
    write_json(raw_b / "bc_001.json", _response())
    replay = tmp_path / "replay"

    with pytest.raises(ValueError, match="需要 --raw-off"):
        build_feature_ir(gt, None, raw_b, FILTER_SOURCE, "mineru3", replay)

    built = build_feature_ir(gt, None, raw_b, FILTER_SOURCE, "mineru3", replay, visual_only=True)
    assert built["raw_documents"] == 1
    manifest = read_json(replay / "manifest.json")
    assert set(manifest["groups"]) == {"image", "chart", "controls/image_off"}
    assert set(manifest["raw_sources"]["bc_001"]) == {"B"}
    document = Document.load(replay / "image/documents/bc_001.json")
    assert document.pages[0].blocks[0].metadata["sub_type"] == "text_image"
    result = evaluate_feature_matrix(gt, replay, tmp_path / "scores")
    assert set(result["metrics"]) == {"image", "chart", "combined_visual"}
    assert result["metrics"]["image"]["on_output_coverage"]["rate"] == 1.0


@pytest.mark.parametrize(
    ("image_on", "image_off", "expected"),
    [(True, False, (1, 1, 0)), (True, True, (1, 0, 1)), (False, False, (0, 0, 0))],
)
def test_header_image_needs_image_evidence_and_detects_untyped_residue(
    image_on, image_off, expected
):
    bbox = [0.1, 0.01, 0.2, 0.08]
    gt = {"marginal_blocks": [{"page": 1, "type": "header_image", "bbox": bbox}]}
    on_block = Block("header", "text", "ROYAL SOCIETY OF CHEMISTRY", bbox=bbox)
    if image_on:
        on_block = Block(
            "logo",
            "text",
            bbox=bbox,
            metadata={"raw_type": "header_image", "spans": [{"image_path": "logo.jpg"}]},
        )
    off_blocks = [Block("renamed", "image", bbox=bbox)] if image_off else []

    result = _header_footer(
        gt, Document("doc", [Page(1, [on_block])]), Document("doc", [Page(1, off_blocks)])
    )

    assert result["image_gt"] == 1
    assert (result["images_matched"], result["cleared"], result["images_remaining"]) == expected
    assert result["eligible"] == result["images_matched"]


def test_score_allows_explicit_reviewed_gt_revision(tmp_path):
    gt = tmp_path / "gt"
    _ground_truth(gt)
    raw_a = tmp_path / "raw-a"
    raw_b = tmp_path / "raw-b"
    write_json(raw_a / "bc_001.json", _response())
    write_json(raw_b / "bc_001.json", _response())
    replay = tmp_path / "replay"
    build_feature_ir(gt, raw_a, raw_b, FILTER_SOURCE, "mineru3", replay)

    revised = tmp_path / "revised-gt"
    revised.mkdir()
    manifest = read_json(gt / "manifest.json")
    records = read_json(gt / "records.json")
    records["records"][0]["new_gt"]["chart_blocks"][0]["bbox"] = [0.39, 0.39, 0.9, 0.8]
    write_json(revised / "manifest.json", manifest)
    write_json(revised / "records.json", records)

    with pytest.raises(ValueError, match="GT 不一致"):
        evaluate_feature_matrix(revised, replay, tmp_path / "strict")

    result = evaluate_feature_matrix(revised, replay, tmp_path / "allowed", allow_gt_revision=True)
    assert result["metrics"]["chart"]["on_recall"]["rate"] == 1.0
    provenance = read_json(tmp_path / "allowed" / "provenance.json")
    assert provenance["gt_revision"]["allowed"] is True
    assert provenance["evaluated_gt_sha256"] != provenance["gt_revision"]["source_gt_sha256"]
