import os
import subprocess
import sys
from pathlib import Path

import pytest

from doc_parse_bench.cli import main
from doc_parse_bench.feature_evaluation.feature_rubric import (
    CONFIG,
    EVIDENCE_SCHEMA,
    GT_SCHEMA,
    RUBRIC_VERSION,
    evaluate_feature_rubric,
    score_feature_rubric,
)
from doc_parse_bench.io import read_json, sha256, write_json


def _case(case_id, feature, document_id="bc_022", page=1, **payload):
    return {
        "id": case_id,
        "feature": feature,
        "document_id": document_id,
        "page": page,
        "source_id": case_id,
        **payload,
    }


def _gt(cases, split="evaluation"):
    return {
        "schema_version": GT_SCHEMA,
        "gt_version": "legacy-129-feature-v3",
        "split": split,
        "cases": cases,
    }


def _evidence(observations, stage="final"):
    return {
        "schema_version": EVIDENCE_SCHEMA,
        "model": "test",
        "stage": stage,
        "config": dict(CONFIG),
        "cases": observations,
        "captures": {
            "bc_022": {
                "off": "raw-a",
                "appendix": "raw-a",
                "header_footer": "raw-a",
                "image": "raw-b",
                "chart": "raw-b",
                "controls/image_off": "raw-b",
            },
            "bc_003": {"off": "raw-doc-3", "appendix": "raw-doc-3"},
        },
    }


def _point(value, series="占比", category="D-1", unit="%", **payload):
    return {"series": series, "category": category, "value": value, "unit": unit, **payload}


def _image(case_id, kind, *, fields=None, **payload):
    fields = [{"key": "label", "text": "Label"}] if fields is None else fields
    case = _case(case_id, "image", sub_type=kind, fields=fields, **payload)
    observed = {"fields": [{**field, "id": f"{case_id}/field/{field['key']}"} for field in fields]}
    if kind != "seal":
        observed.update(sub_type=kind, subtype_id=f"{case_id}/subtype")
    return case, observed


def test_appendix_page_pairs_macro_average_and_distinguish_residue():
    gt = _gt(
        [
            _case("p15", "appendix", "bc_003", 15, anchors=["heading", "text"]),
            _case("p16", "appendix", "bc_003", 16, anchors=["text"]),
            _case("p2", "appendix", page=2, anchors=["text"]),
        ]
    )
    evidence = _evidence(
        {
            "p15": {"on_anchors": ["heading"], "off_residual": False},
            "p16": {"on_anchors": ["text"], "off_residual": True},
            "p2": {"on_anchors": ["text"], "off_residual": False},
        }
    )
    result = score_feature_rubric(gt, evidence)
    assert result["features"]["appendix"]["score"] == 50
    assert result["features"]["appendix"]["off_residual_pages"] == 1
    assert result["cases"]["p15"]["missing_anchors"] == ["text"]
    assert result["cases"]["p16"]["score"] == 0


def test_header_image_not_present_is_not_a_successful_removal():
    gt = _gt(
        [
            _case(
                "margins",
                "header_footer",
                blocks=[
                    {"id": "title", "type": "header", "text": "RSC Advances"},
                    {"id": "logo", "type": "header_image"},
                    {"id": "number", "type": "page_number", "text": "17694"},
                ],
            )
        ]
    )
    evidence = _evidence(
        {
            "margins": {
                "on_blocks": [
                    {"id": "header-text", "source_id": "title", "text": "RSC\nAdvances"},
                    {"id": "page-text", "source_id": "number", "text": "１７６９４"},
                    {"id": "extra", "text": "invented header"},
                ],
                "off_residual_ids": ["number"],
            }
        }
    )
    result = score_feature_rubric(gt, evidence)
    metrics = result["features"]["header_footer"]
    assert (metrics["tp"], metrics["fp"], metrics["fn"], metrics["score"]) == (1, 1, 2, 40)
    blocks = result["cases"]["margins"]["blocks"]
    assert not blocks["logo"]["on_seen"] and not blocks["logo"]["hit"]
    assert blocks["number"]["on_correct"] and blocks["number"]["off_residual"]


@pytest.mark.parametrize(
    ("observed_label", "expected_status", "expected_score"),
    [
        ("flowchart", "correct", 100),
        ("text_image", "wrong", 0),
        (None, "missing", 0),
        ("not_collected", "evidence_missing", None),
    ],
)
def test_correct_text_does_not_cover_wrong_or_missing_subtype(
    observed_label, expected_status, expected_score
):
    case, observation = _image("fig1", "flowchart")
    if observed_label == "not_collected":
        observation.pop("sub_type")
    else:
        observation["sub_type"] = observed_label
    result = score_feature_rubric(_gt([case]), _evidence({"fig1": observation}))
    scored = result["cases"]["fig1"]
    assert scored["content_score"] == 100
    assert scored["score"] == expected_score
    assert scored["subtype"]["status"] == expected_status


def test_flowchart_relations_are_directed_and_require_correct_endpoints():
    case, observed = _image(
        "flow",
        "flowchart",
        fields=[{"key": name, "text": name} for name in ("start", "middle", "end")],
        relations=[{"from": "start", "to": "middle"}, {"from": "middle", "to": "end"}],
    )
    observed["relations"] = [
        {"id": "edge-1", "from": "start", "to": "middle"},
        {"id": "edge-2", "from": "end", "to": "middle"},
    ]
    result = score_feature_rubric(_gt([case]), _evidence({"flow": observed}))["cases"]["flow"]
    assert result["relations"]["score"] == 50
    assert result["score"] == 80
    observed["fields"][1]["text"] = "wrong middle label"
    result = score_feature_rubric(_gt([case]), _evidence({"flow": observed}))["cases"]["flow"]
    assert result["relations"]["tp"] == 0


def test_merged_crop_cannot_lend_the_same_output_fact_to_two_figures():
    first, first_output = _image("left", "text_image")
    second, second_output = _image("right", "text_image")
    second_output["fields"][0]["id"] = first_output["fields"][0]["id"]
    evidence = _evidence({"left": first_output, "right": second_output})
    with pytest.raises(ValueError, match="不能重复归属"):
        score_feature_rubric(_gt([first, second]), evidence)
    second_output["fields"][0]["id"] = "same-crop/second-attributed-field"
    result = score_feature_rubric(_gt([first, second]), evidence)
    assert result["cases"]["left"]["score"] == result["cases"]["right"]["score"] == 100
    second_output["subtype_id"] = first_output["subtype_id"]
    with pytest.raises(ValueError, match="subtype 证据不能重复归属"):
        score_feature_rubric(_gt([first, second]), evidence)


def test_chart_matches_exact_values_with_estimates_outside_the_gt_denominator():
    case = _case(
        "wind",
        "chart",
        "bc_091",
        values=[_point("7.46"), _point("11.15", category="D-2")],
        unscored=[{"series": "理论蕴藏量", "unit": "亿kWh"}],
    )
    evidence = _evidence(
        {
            "wind": {
                "table_status": "parsed",
                "values": [
                    _point("７．４６０％", id="correct"),
                    _point("~11.15", category="D-2", id="approximate"),
                    _point("~1300", series="理论蕴藏量", unit="亿kWh", id="estimate"),
                ],
            }
        }
    )
    result = score_feature_rubric(_gt([case]), evidence)
    metrics = result["features"]["chart"]
    assert metrics["score"] == 50
    assert metrics["matched_values"] == 1
    assert metrics["denominator"]["count"] == 2
    assert result["cases"]["wind"]["unmatched_output_cells"] == 2


@pytest.mark.parametrize(
    ("unit", "cell", "hits"),
    [
        ("%", "12.5", 1),
        ("%", "１２．５０ ％", 1),
        ("%", "0.125", 0),
        ("kg", "12.5", 1),
        ("kg", "12.5%", 0),
        ("", "12.5%", 0),
    ],
)
def test_chart_treats_cell_percent_as_formatting_for_percentage_values_only(unit, cell, hits):
    gt = _gt([_case("table", "chart", values=[_point("12.5", unit=unit)])])
    predictions = [_point(cell, series="Value", unit="", id="cell")]
    evidence = _evidence({"table": {"table_status": "parsed", "values": predictions}})
    result = score_feature_rubric(gt, evidence)
    assert result["features"]["chart"]["matched_values"] == hits


@pytest.mark.parametrize(
    ("first_column", "second_column", "hits"),
    [(("90", "80"), ("12", "23"), 4), (("90", "23"), ("12", "80"), 2)],
)
def test_chart_aligns_reordered_columns_with_identical_headers(first_column, second_column, hits):
    reference = [
        _point(value, series=series, category=f"{year}年", unit=unit)
        for series, unit, cells in (("Revenue", "USD", ("12", "23")), ("Mass", "kg", ("90", "80")))
        for year, value in zip((2023, 2024), cells)
    ]
    predictions = [
        _point(
            value,
            series="Value",
            category=str(year),
            unit="",
            column_id=column_id,
            id=f"{column_id}/{year}",
        )
        for column_id, cells in (("first", first_column), ("second", second_column))
        for year, value in zip((2023, 2024), cells)
    ]
    gt = _gt([_case("table", "chart", values=reference)])
    evidence = _evidence({"table": {"table_status": "parsed", "values": predictions}})
    result = score_feature_rubric(gt, evidence)
    metric = result["features"]["chart"]
    assert (metric["matched_values"], metric["score"]) == (hits, 25 * hits)
    assert metric["header_conflict_cases"] == []
    matches = result["cases"]["table"]["column_matches"]
    assert {match["column_id"] for match in matches} == {"first", "second"}


def test_chart_maximizes_matches_across_columns():
    categories = ("A", "B", "C", "D")
    reference = [
        _point(value, series=series, category=category, unit="kg")
        for series, cells in (
            ("North", ("10", "20", "30", "40")),
            ("South", ("10", "20", "300", "400")),
        )
        for category, value in zip(categories, cells)
    ]
    predictions = [
        _point(value, series="Value", category=category, unit="", id=f"table:{row}:{column}")
        for column, cells in ((1, ("10", "20", "30", "400")), (2, ("50", "60", "30", "40")))
        for row, (category, value) in enumerate(zip(categories, cells), start=1)
    ]
    gt = _gt([_case("table", "chart", values=reference)])
    evidence = _evidence(
        {"table": {"table_status": "parsed", "values": predictions, "block_id": "table"}}
    )
    result = score_feature_rubric(gt, evidence)
    matches = result["cases"]["table"]["column_matches"]
    assert {match["series"]: match["matched_values"] for match in matches} == {
        "North": 2,
        "South": 3,
    }
    assert result["features"]["chart"]["score"] == 62.5


def test_chart_reports_the_conflicting_header_on_its_actual_column():
    reference = [
        _point("8.0", series="Efficiency", category="A"),
        _point("19", series="Mass", category="A", unit="kg"),
    ]
    predictions = [
        _point("８％", series="Mass (kg)", category="A", unit="kg", id="cell-1", column_id="1"),
        _point("19", series="Efficiency", category="A", unit="%", id="cell-2", column_id="2"),
        _point("~100", series="Estimate", category="A", unit="kg", id="cell-3", column_id="3"),
    ]
    gt = _gt([_case("table", "chart", values=reference)])
    evidence = _evidence({"table": {"table_status": "parsed", "values": predictions}})
    result = score_feature_rubric(gt, evidence)
    metric = result["features"]["chart"]
    assert (metric["score"], metric["parsed_tables"], metric["unmatched_output_cells"]) == (
        100,
        1,
        1,
    )
    assert metric["header_conflict_cases"] == ["table"]
    matches = {row["series"]: row for row in result["cases"]["table"]["column_matches"]}
    assert matches["Efficiency"]["column_id"] == "1"
    assert matches["Efficiency"]["header_conflicts"] == ["series", "unit"]
    assert matches["Mass"]["column_id"] == "2"
    assert matches["Mass"]["header_conflicts"] == ["series", "unit"]
    predictions[1]["column_id"] = "1"
    with pytest.raises(ValueError, match="同一输出列"):
        score_feature_rubric(gt, evidence)


@pytest.mark.parametrize(("observation", "score"), [({}, None), ({"table_status": "missing"}, 0)])
def test_chart_distinguishes_missing_table_from_missing_evidence(observation, score):
    gt = _gt([_case("table", "chart", values=[_point("5")])])
    result = score_feature_rubric(gt, _evidence({"table": observation}))
    assert result["features"]["chart"]["score"] == score


def _complete_review():
    cases = [
        _case("page", "appendix", "bc_003", 15, anchors=["body"]),
        _case("margins", "header_footer", blocks=[{"id": "margin", "type": "header_image"}]),
        _case("chart", "chart", values=[_point("7.46")]),
    ]
    observed = {
        "page": {"on_anchors": ["body"], "off_residual": False},
        "margins": {
            "on_blocks": [{"id": "logo", "source_id": "margin", "image_available": True}],
            "off_residual_ids": [],
        },
        "chart": {"table_status": "parsed", "values": [_point("7.460", id="value")]},
    }
    for name, kind, fields in (
        ("text", "text_image", None),
        ("flow", "flowchart", None),
        ("signed", "natural_image", None),
        ("no-text", "natural_image", []),
        ("seal", "seal", None),
    ):
        case, observation = _image(name, kind, fields=fields)
        cases.append(case)
        observed[name] = observation | {"image_available": True}
    for feature in ("appendix", "header_footer", "image", "chart"):
        case_id = f"protect-{feature}"
        document, page = ("bc_003", 35) if feature == "appendix" else ("bc_022", 1)
        cases.append(_case(case_id, feature, document, page, protected=True))
        observed[case_id] = {"on_state": "complete", "off_state": "complete"}
    return _gt(cases), _evidence(observed)


def test_overall_is_equal_weight_and_deletion_is_independent():
    gt, evidence = _complete_review()
    result = score_feature_rubric(gt, evidence)
    assert result["overall"] == 100
    assert result["deletion_gate"]["status"] == "pass"
    evidence["cases"]["protect-appendix"]["off_state"] = "missing"
    result = score_feature_rubric(gt, evidence)
    assert result["overall"] == 100
    assert result["deletion_gate"]["status"] == "fail"
    assert result["deletion_gate"]["confirmed_deletions"] == ["protect-appendix"]
    evidence["cases"]["no-text"]["fields"] = [{"id": "invented", "key": "fake", "text": "Fake"}]
    result = score_feature_rubric(gt, evidence)
    assert result["features"]["image"]["score"] == 87.5
    assert result["overall"] == 96.875


def test_no_overall_on_incomplete_evidence_or_calibration():
    gt, evidence = _complete_review()
    del evidence["cases"]["chart"]
    result = score_feature_rubric(gt, evidence)
    assert result["features"]["chart"]["score"] is None
    assert result["cases"]["chart"]["missing_reasons"] == ["table_status"]
    assert result["overall"] is None
    gt, evidence = _complete_review()
    evidence["captures"]["bc_003"]["off"] = "different-raw"
    result = score_feature_rubric(gt, evidence)
    assert result["cases"]["page"]["status"] == "pair_unverified"
    assert result["cases"]["page"]["missing_reasons"] == ["capture_pair_unverified"]
    assert result["deletion_gate"]["status"] == "pending"
    gt, evidence = _complete_review()
    evidence["stage"] = "replay"
    result = score_feature_rubric(gt, evidence)
    assert result["overall"] is None
    assert result["deletion_gate"]["status"] == "calibration_only"
    gt["split"], evidence["stage"] = "calibration", "final"
    assert score_feature_rubric(gt, evidence)["overall"] is None


def test_incomplete_image_stratum_blocks_image_score_and_preserves_valid_zero():
    gt, evidence = _complete_review()
    evidence["cases"]["flow"]["sub_type"] = "text_image"
    del evidence["cases"]["seal"]
    result = score_feature_rubric(gt, evidence)
    image = result["features"]["image"]
    assert image["score"] is None
    assert image["groups"]["flowchart"]["score"] == 0
    assert image["groups"]["flowchart"]["score_status"] == "scored"
    assert image["groups"]["seal"]["coverage"]["missing"] == 1
    assert result["cases"]["seal"]["missing_reasons"] == ["fields"]
    assert result["overall"] is None


def test_summary_exposes_score_status_and_coverage_without_changing_score():
    gt, evidence = _complete_review()
    result = score_feature_rubric(gt, evidence)
    assert result["overall_status"] == "scored"
    assert result["score_basis"]["weights"] == {
        "appendix": 25,
        "header_footer": 25,
        "image": 25,
        "chart": 25,
    }
    assert result["features"]["chart"]["score_status"] == "scored"
    assert result["features"]["chart"]["coverage"] == {
        "planned": 1,
        "scored": 1,
        "missing": 0,
        "rate": 100.0,
    }
    del evidence["cases"]["chart"]
    result = score_feature_rubric(gt, evidence)
    assert result["overall_status"] == "pending_evidence"
    assert result["features"]["chart"]["score_status"] == "pending_evidence"
    assert result["features"]["chart"]["coverage"] == {
        "planned": 1,
        "scored": 0,
        "missing": 1,
        "rate": 0.0,
    }


def test_known_unapplied_target_configuration_cannot_be_relabelled_final():
    gt, evidence = _complete_review()
    evidence["relevel_applied"] = False
    with pytest.raises(ValueError, match="不能声明为 final"):
        score_feature_rubric(gt, evidence)
    evidence["stage"] = "replay"
    assert score_feature_rubric(gt, evidence)["overall"] is None


def test_cli_writes_frozen_gt_hash_per_case_and_summary(tmp_path, monkeypatch):
    gt, evidence = _complete_review()
    gt["gt_version"] = "operations-manuals-2026-11"
    document_ids = {"bc_003": "manual-a", "bc_022": "manual-z"}
    for case in gt["cases"]:
        case["document_id"] = document_ids[case["document_id"]]
    evidence["captures"] = {
        document_ids[document]: groups for document, groups in evidence["captures"].items()
    }
    gt_path, evidence_path = tmp_path / "truth.json", tmp_path / "evidence.json"
    output = tmp_path / "scores"
    write_json(gt_path, gt)
    write_json(evidence_path, evidence | {"gt_sha256": "invalid"})
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "docbench",
            "evaluate-feature-rubric",
            "--gt",
            str(gt_path),
            "--pred",
            str(evidence_path),
            "--output",
            str(output),
        ],
    )
    with pytest.raises(SystemExit, match="1"):
        main()
    assert not output.exists()
    write_json(evidence_path, evidence | {"gt_sha256": sha256(gt_path)})
    main()
    metrics = read_json(output / "metrics.json")
    provenance = read_json(output / "provenance.json")
    assert metrics["overall"] == 100
    assert metrics["rubric_version"] == provenance["rubric_version"] == RUBRIC_VERSION
    chart = read_json(output / "per_case.json")["chart"]
    assert chart["document_id"] == "manual-z"
    assert chart["matched_values"] == 1
    assert provenance["gt_version"] == gt["gt_version"]
    assert provenance["gt_sha256"] == sha256(gt_path)
    assert read_json(output / "pending_cases.json") == {}
    assert "四项等权总分：**100.00**" in (output / "report.md").read_text()
    assert read_json(output / "metrics.json")["features"]["header_footer"]["denominator"] == {
        "count": 1,
        "case_count": 1,
        "unit": "blocks",
    }


@pytest.mark.parametrize(
    "module",
    ["doc_parse_bench.feature_evaluation.feature_score_cli", "doc_parse_bench.feature_score_cli"],
)
def test_standalone_cli_runs_without_site_packages_and_template_does_not_invent_output(
    tmp_path, module
):
    root = Path(__file__).resolve().parents[1]
    cases = root / "tests/fixtures/feature_rubric_129"
    environment = os.environ | {"PYTHONPATH": str(root / "src")}
    command = [sys.executable, "-S", "-m", module]
    subprocess.run(
        command
        + [
            "score",
            "--gt",
            str(cases / "gt.json"),
            "--pred",
            str(cases / "ft.json"),
            "--output",
            str(tmp_path / "scores"),
        ],
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )
    metrics = read_json(tmp_path / "scores/metrics.json")
    assert metrics["rubric_version"] == RUBRIC_VERSION
    assert metrics["features"]["chart"]["score"] == 50
    assert metrics["overall"] is None
    subprocess.run(
        command
        + [
            "template",
            "--gt",
            str(cases / "gt.json"),
            "--model",
            "3.1-ft",
            "--output",
            str(tmp_path / "blank.json"),
        ],
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )
    blank = read_json(tmp_path / "blank.json")
    assert blank["stage"] == "replay"
    assert blank["captures"] == {}
    assert all(observation == {} for observation in blank["cases"].values())


@pytest.mark.parametrize(
    ("model", "image_scored", "chart_conflicts"),
    [("3.1-ft", 7, []), ("3.1-origin", 5, ["bc_091:candidate.block.p1.0004"])],
)
def test_saved_pilot_replays_score_with_current_rubric(
    tmp_path, model, image_scored, chart_conflicts
):
    root = Path(__file__).resolve().parents[1]
    gt = root / "artifacts/legacy-features-20261119/rubric-pilot-gt.json"
    evidence = (
        root / "experiments/legacy129-subimage-20261123/calibration-evidence" / f"{model}.json"
    )
    result = evaluate_feature_rubric(gt, evidence, tmp_path / model)
    assert sha256(gt) == "6d98b54495edc5f61422103a3a032a64ed93c72383a3df068e3c22238f610b72"
    assert result["features"]["appendix"]["score"] == pytest.approx(76.89102564102564)
    assert result["features"]["header_footer"]["score"] == pytest.approx(81.48148148148148)
    chart = result["features"]["chart"]
    assert chart["score"] == 100
    assert chart["matched_values"] == chart["denominator"]["count"] == 78
    assert chart["header_conflict_cases"] == chart_conflicts
    assert result["features"]["image"]["scored"] == image_scored
    assert result["features"]["image"]["score"] is None
    assert result["overall"] is None
    assert result["deletion_gate"]["observed_status"] == "fail"
