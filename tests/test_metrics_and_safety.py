from pathlib import Path

import pytest

from doc_parse_bench.backends.runner import evaluate
from doc_parse_bench.charts import augment_charts
from doc_parse_bench.exporters import export_gt, export_predictions
from doc_parse_bench.io import read_json, write_json
from doc_parse_bench.metrics import (
    compute_title_score,
    extract_title_lines,
    normalize_report_metrics,
    summarize,
)
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


MP_COMPLETE = {
    "text_edit": 0.1,
    "merged_text_edit": 0.2,
    "formula_cdm": 0.0,
    "table_teds": 0.6,
    "merged_table_teds": 0.5,
    "figure_f1": 0.4,
    "reading_order_edit": 0.3,
    "head_teds": 0.2,
}


def test_mp_official_overall_averages_eight_tasks_and_keeps_computed_zero():
    metrics = {
        **MP_COMPLETE,
        "title": 1.0,
        "text_relation_f1": 1.0,
        "table_relation_f1": 1.0,
        "agentbuilder_overall": 1.0,
    }
    normalized = normalize_report_metrics(metrics, "MPDocBench")
    assert normalized["mpdocbench_overall"] == pytest.approx(4.1 / 8)
    assert normalized["agentbuilder_overall"] is None
    assert normalized["omnidocbench_overall"] is None


@pytest.mark.parametrize("missing", MP_COMPLETE)
def test_mp_official_overall_requires_every_task_and_never_reweights_missing(missing):
    metrics = {name: value for name, value in MP_COMPLETE.items() if name != missing}
    metrics.update(formula_edit=0.0, formula_accuracy=1.0, mpdocbench_overall=1.0)
    assert normalize_report_metrics(metrics, "MPDocBench")["mpdocbench_overall"] is None


@pytest.mark.parametrize("backend", ["OmniDocBench", "legacy", "legacy_compat"])
def test_mp_official_overall_cannot_be_generated_from_another_backend(backend):
    assert normalize_report_metrics(MP_COMPLETE, backend)["mpdocbench_overall"] is None


@pytest.mark.parametrize("backend", ["OmniDocBench", "MPDocBench", "legacy", "legacy_compat"])
def test_agentbuilder_only_uses_omnidocbench_source_metrics(backend):
    raw = {
        "text_block": {"all": {"Edit_dist": {"ALL_page_avg": 0.1}}},
        "table": {"all": {"TEDS": {"all": 0.8}}},
        "reading_order": {"all": {"Edit_dist": {"ALL_page_avg": 0.3}}},
        "display_formula": {"all": {"CDM": {"all": 0.4}}},
        "merged_table": {"all": {"TEDS": {"all": 0.05}}},
        "head": {"all": {"HeadTEDS": {"all": 0.02}}},
    }
    metrics = summarize(raw, 0.6, backend)
    assert metrics["title"] == 0.6
    assert metrics["head_teds"] == 0.02
    if backend == "OmniDocBench":
        assert metrics["agentbuilder_overall"] == 0.78
        assert metrics["omnidocbench_overall"] == pytest.approx(0.7)
    else:
        assert metrics["agentbuilder_overall"] is None
        assert metrics["omnidocbench_overall"] is None
        if backend in {"legacy", "legacy_compat"}:
            assert metrics["historical_weighted_overall"] == 0.78


def test_agentbuilder_remains_available_without_cdm_and_never_substitutes_formula_edit():
    raw = {
        "text_block": {"all": {"Edit_dist": {"ALL_page_avg": 0.1}}},
        "table": {"all": {"TEDS": {"all": 0.8}}},
        "reading_order": {"all": {"Edit_dist": {"ALL_page_avg": 0.3}}},
        "display_formula": {"all": {"Edit_dist": {"ALL_page_avg": 0.2}}},
    }
    metrics = summarize(raw, 0.6, "OmniDocBench")
    assert metrics["agentbuilder_overall"] == 0.78
    assert metrics["formula_accuracy"] == 0.8
    assert metrics.get("formula_cdm") is None
    assert metrics["omnidocbench_overall"] is None


def test_normalize_recomputes_stale_page_score_and_keeps_zero_weight_components():
    original = {
        "text_accuracy": 0.9,
        "table_teds": 0.8,
        "reading_order_accuracy": None,
        "title": 0.0,
        "formula_accuracy": 1.0,
        "formula_cdm": None,
        "agentbuilder_overall": 1.0,
        "omnidocbench_overall": 1.0,
    }
    normalized = normalize_report_metrics(original, "OmniDocBench")
    assert normalized["agentbuilder_overall"] == pytest.approx(0.7286)
    assert normalized["title"] == 0.0
    assert normalized["omnidocbench_overall"] is None
    assert original["agentbuilder_overall"] == 1.0


@pytest.mark.parametrize("backend", ["MPDocBench", "legacy", "legacy_compat"])
def test_normalize_rejects_stored_cross_backend_agentbuilder_scores(backend):
    original = {
        "agentbuilder_overall": 0.9999,
        "text_accuracy": 0.9,
        "table_teds": 0.8,
        "reading_order_accuracy": 0.7,
        "title": 0.6,
        "omnidocbench_overall": 0.99,
    }
    normalized = normalize_report_metrics(original, backend)
    assert normalized["agentbuilder_overall"] is None
    assert normalized["omnidocbench_overall"] is None
    assert normalized["title"] == 0.6
    assert original["agentbuilder_overall"] == 0.9999
    if backend in {"legacy", "legacy_compat"}:
        assert normalized["historical_weighted_overall"] == 0.9999


def test_normalize_preserves_historical_aggregate_when_called_again():
    original = {
        "agentbuilder_overall": None,
        "historical_weighted_overall": 0.55,
        "legacy_stage_overall": 0.8,
        "text_accuracy": 0.9,
        "table_teds": 0.8,
        "reading_order_accuracy": 0.7,
        "title": 0.6,
    }
    normalized = normalize_report_metrics(original, "legacy_compat")
    assert normalized["agentbuilder_overall"] is None
    assert normalized["historical_weighted_overall"] == 0.55
    assert normalized["legacy_stage_overall"] == 0.8
