import json
from pathlib import Path

from doc_parse_bench.feature_matrix import build_feature_ir, evaluate_feature_matrix
from doc_parse_bench.io import write_json

FILTER_SOURCE = Path(
    "archives/pdf2text-feature-20261119/source-ditto/"
    "pdf2text-78712-pdf-rule-toggle-test-1806ec1/src"
)


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
    assert result["metrics"]["chart"]["on_output_coverage"]["rate"] == 1.0
    assert result["metrics"]["chart"]["off_downgrade_rate"]["rate"] == 1.0
