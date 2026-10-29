from pathlib import Path

import pytest

from doc_parse_bench.backends.runner import evaluate
from doc_parse_bench.charts import augment_charts
from doc_parse_bench.exporters import export_gt, export_predictions
from doc_parse_bench.io import read_json, write_json
from doc_parse_bench.metrics import compute_title_score, extract_title_lines, summarize
from doc_parse_bench.schema import Block, Document, Page


def test_historical_title_metric_matches_existing_129_document_outputs():
    root = Path(__file__).parents[1]
    source = root / "data/legacy/results/outputs"
    if not source.exists():
        pytest.skip("本地历史结果包未提供")
    golden = read_json(Path(__file__).parent / "fixtures/historical_title_scores.json")
    checked = 0
    for path in source.rglob("*.md"):
        gt = root / "data/legacy/groundtruth" / path.name
        if not gt.exists():
            continue
        a, b = extract_title_lines(gt.read_text()), extract_title_lines(path.read_text())
        assert compute_title_score(a, b) == golden[str(path.relative_to(source))]
        checked += 1
    assert checked >= 129


def test_missing_predictions_cannot_be_silently_skipped(tmp_path):
    gt = tmp_path / "gt.json"
    write_json(gt, [{"page_info": {"image_path": "missing.pdf"}}])
    pred = tmp_path / "pred"
    pred.mkdir()
    with pytest.raises(ValueError, match="缺少 1/1"):
        evaluate("MPDocBench", gt, pred, tmp_path / "report")


def test_gt_chart_table_requires_reviewed_transcription(tmp_path):
    doc = Document(
        "doc",
        [Page(1, [Block("chart", "chart", bbox=[0.1, 0.1, 0.9, 0.9])])],
        metadata={"origin": "annotations"},
    )
    doc.dump(tmp_path / "ir/doc.json")
    with pytest.raises(ValueError, match="缺少人工确认"):
        export_gt(tmp_path / "ir", tmp_path / "unreviewed", "chart-table")
    write_json(
        tmp_path / "sidecar.json",
        {"doc/chart": {"reviewed": True, "html": "<table><tr><td>42</td></tr></table>"}},
    )
    augment_charts(tmp_path / "ir", tmp_path / "enhanced", tmp_path / "sidecar.json")
    export_gt(tmp_path / "enhanced/documents", tmp_path / "reviewed", "chart-table")


def test_gt_relations_cannot_enter_prediction_export(tmp_path):
    Document("gt", [], metadata={"origin": "annotations"}).dump(tmp_path / "ir/gt.json")
    with pytest.raises(ValueError, match="禁止将 GT"):
        export_predictions(tmp_path / "ir", tmp_path / "out")


def test_formula_edit_is_never_reported_as_cdm_or_official_overall():
    flat = summarize({"display_formula": {"all": {"Edit_dist": {"ALL_page_avg": 0.2}}}}, 0.8)
    assert flat["formula_accuracy"] == 0.8
    assert "formula_cdm" not in flat
    assert flat["omnidocbench_overall"] is None


def test_official_overall_uses_three_modules_and_excludes_reading_order():
    raw = {
        "text_block": {"all": {"Edit_dist": {"ALL_page_avg": 0.1}}},
        "table": {"all": {"TEDS": {"all": 0.8}}},
        "display_formula": {"all": {"CDM": {"all": 0.7}}},
        "reading_order": {"all": {"Edit_dist": {"ALL_page_avg": 0.99}}},
    }
    assert summarize(raw, 0.2)["omnidocbench_overall"] == pytest.approx(0.8)
