import pytest

from doc_parse_bench.feature_evaluation.feature_eval import (
    FEATURE_GT_SCHEMA,
    FEATURE_SUBSET_SCHEMA,
    _apply_appendix_override,
    evaluate_features,
)
from doc_parse_bench.io import write_json
from doc_parse_bench.schema import Block, Document, Page


def _feature_record():
    return {
        "document_id": "bc_001",
        "source_name": "sample",
        "old_gt": {"chart_content_candidate": True},
        "new_gt": {
            "appendix": {"pages": [2]},
            "marginal_blocks": [{"page": 1, "type": "header", "text": "Header"}],
            "image_blocks": [{"page": 1, "type": "image", "text": ""}],
            "chart_blocks": [{"page": 2, "type": "chart", "text": ""}],
        },
    }


def test_appendix_override_replaces_heuristic_range_and_leaves_references_outside():
    features = {
        "pages": 35,
        "appendix": {"has_appendix": True, "start_page": 20, "pages": list(range(20, 36))},
    }

    _apply_appendix_override("bc_003", features, {"appendix_page_ranges": [[15, 34]]})

    assert features["appendix"]["start_page"] == 15
    assert features["appendix"]["pages"] == list(range(15, 35))


@pytest.mark.parametrize("bounds", [[0, 34], [34, 15], [15, 36], [True, 34]])
def test_appendix_override_rejects_invalid_physical_pages(bounds):
    with pytest.raises(ValueError, match="bc_003.*附录页码范围无效"):
        _apply_appendix_override("bc_003", {"pages": 35}, {"appendix_page_ranges": [bounds]})


def test_feature_evaluator_scores_all_four_capabilities(tmp_path):
    gt = tmp_path / "gt"
    write_json(
        gt / "manifest.json",
        {"schema_version": FEATURE_GT_SCHEMA, "dataset_version": "test"},
    )
    write_json(
        gt / "records.json", {"schema_version": FEATURE_GT_SCHEMA, "records": [_feature_record()]}
    )
    prediction = Document(
        "bc_001",
        [
            Page(
                1,
                [
                    Block("h", "header", "Header"),
                    Block("i", "image", bbox=[0.1, 0.1, 0.2, 0.2]),
                ],
            ),
            Page(
                2,
                [
                    Block("body", "text", "Appendix body"),
                    Block("c", "chart", html="<table><tr><td>42</td></tr></table>"),
                ],
            ),
        ],
        metadata={"origin": "prediction"},
    )
    prediction.dump(tmp_path / "pred/documents/bc_001.json")

    result = evaluate_features(gt, tmp_path / "pred", tmp_path / "result")

    assert result["appendix_page_recall"] == 1.0
    assert result["header_footer_f1"] == 1.0
    assert result["image_analysis_f1"] == 1.0
    assert result["chart_location_recall"] == 1.0
    assert result["chart_content_recall"] == 1.0


def test_feature_evaluator_keeps_chart_content_status_explicit(tmp_path):
    gt = tmp_path / "gt"
    write_json(
        gt / "manifest.json",
        {"schema_version": FEATURE_GT_SCHEMA, "dataset_version": "test"},
    )
    write_json(
        gt / "records.json", {"schema_version": FEATURE_GT_SCHEMA, "records": [_feature_record()]}
    )
    prediction = Document("bc_001", [Page(1, [])], metadata={"origin": "prediction"})
    prediction.dump(tmp_path / "pred/documents/bc_001.json")

    result = evaluate_features(gt, tmp_path / "pred", tmp_path / "result")

    assert result["chart_gt_content_status"] == "legacy_markdown_candidate_only"
    assert result["chart_content_recall"] == 0.0


def test_feature_evaluator_reads_pdf2text_json_response(tmp_path):
    gt = tmp_path / "gt"
    write_json(
        gt / "manifest.json",
        {"schema_version": FEATURE_GT_SCHEMA, "dataset_version": "test"},
    )
    write_json(
        gt / "records.json",
        {
            "schema_version": FEATURE_GT_SCHEMA,
            "records": [_feature_record()],
        },
    )
    write_json(
        tmp_path / "pred/sample.json",
        {
            "pages": 2,
            "markdown": "Header\n\n![image](figure.jpg)\n\nAppendix body",
            "error": None,
        },
    )

    result = evaluate_features(gt, tmp_path / "pred", tmp_path / "result")

    assert result["appendix_page_recall"] == 1.0
    assert result["header_footer_recall"] == 1.0
    assert result["image_analysis_recall"] == 1.0


def test_feature_evaluator_skips_non_appendix_pages_in_reported_page_prefix(tmp_path):
    gt = tmp_path / "gt"
    record = _feature_record()
    record["new_gt"]["appendix"]["pages"] = [2, 4]
    write_json(gt / "manifest.json", {"schema_version": FEATURE_GT_SCHEMA})
    write_json(gt / "records.json", {"schema_version": FEATURE_GT_SCHEMA, "records": [record]})
    write_json(tmp_path / "pred/sample.json", {"pages": 3, "markdown": "Body", "error": None})

    result = evaluate_features(gt, tmp_path / "pred", tmp_path / "result")

    assert result["appendix_page_recall"] == 0.5


def test_feature_evaluator_scores_a_named_subset_without_missing_zeroes(tmp_path):
    gt = tmp_path / "gt"
    record = _feature_record()
    second = {**record, "document_id": "bc_002", "source_name": "other"}
    write_json(
        gt / "manifest.json",
        {
            "schema_version": FEATURE_GT_SCHEMA,
            "gt_version": "legacy-129-feature-v3",
            "dataset_version": "test",
        },
    )
    write_json(
        gt / "records.json",
        {"schema_version": FEATURE_GT_SCHEMA, "records": [record, second]},
    )
    subset = tmp_path / "subset.json"
    write_json(
        subset,
        {
            "schema_version": FEATURE_SUBSET_SCHEMA,
            "gt_version": "legacy-129-feature-v3",
            "subsets": {"union": ["bc_001"], "other": ["bc_002"]},
        },
    )
    prediction = Document("bc_001", [Page(1, [])], metadata={"origin": "prediction"})
    prediction.dump(tmp_path / "pred/documents/bc_001.json")

    result = evaluate_features(
        gt,
        tmp_path / "pred",
        tmp_path / "result",
        subset_manifest=subset,
        subset_name="union",
    )

    assert result["subset"] == "union"
    assert result["expected_documents"] == 1
    assert result["missing_documents"] == 0
