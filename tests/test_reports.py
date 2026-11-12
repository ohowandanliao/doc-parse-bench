import csv
from itertools import groupby

import pytest

from doc_parse_bench.benchmark import collect_reports
from doc_parse_bench.io import read_json, write_json


def _saved_report(root, model, backend, profile, metrics):
    report = root / model / backend
    write_json(
        report / "provenance.json",
        {
            "backend": backend,
            "expected": 2 if backend == "OmniDocBench" else 1,
            "provided": 2 if backend == "OmniDocBench" else 1,
            "preprocessing": {"profile": profile},
        },
    )
    write_json(report / "metrics.json", metrics)
    return report


def _csv_columns(path):
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return csv.DictReader(stream).fieldnames


def test_reports_publish_three_independent_boards_without_mp_agentbuilder_pollution(tmp_path):
    reports = tmp_path / "reports"
    common = {
        "text_accuracy": 0.9,
        "text_edit": 0.1,
        "table_teds": 0.8,
        "table_accuracy": 0.7,
        "table_teds_s": 0.9,
        "reading_order_accuracy": 0.7,
        "reading_order_edit": 0.3,
        "formula_accuracy": 0.4,
        "formula_cdm": None,
        "title": 0.6,
    }
    _saved_report(
        reports, "page-model", "OmniDocBench", "legacy", {**common, "agentbuilder_overall": 0.01}
    )
    contaminated = {
        **common,
        "agentbuilder_overall": 0.9999,
        "merged_table_teds": 0.2,
        "head_teds": 0.1,
    }
    mp_report = _saved_report(reports, "mp-only-model", "MPDocBench", "legacy", contaminated)
    _saved_report(
        reports,
        "old-model",
        "legacy",
        "legacy",
        {**common, "agentbuilder_overall": 0.55, "legacy_stage_overall": 0.8},
    )

    output = tmp_path / "summary"
    collect_reports([reports], output)
    rows = read_json(output / "summary.json")
    assert len(rows) == 3
    indexed = {row["backend"]: row for row in rows}
    assert indexed["OmniDocBench"]["agentbuilder_overall"] == pytest.approx(0.78)
    assert indexed["OmniDocBench"]["omnidocbench_overall"] is None
    assert indexed["MPDocBench"]["agentbuilder_overall"] is None
    assert indexed["legacy_compat"]["agentbuilder_overall"] is None
    assert indexed["legacy_compat"]["historical_weighted_overall"] == 0.55
    assert indexed["legacy_compat"]["legacy_stage_overall"] == 0.8
    assert read_json(mp_report / "metrics.json") == contaminated

    for board in ("AgentBuilder", "OmniDocBench", "MPDocBench"):
        directory = output / "leaderboards" / board
        assert all((directory / f"summary.{suffix}").is_file() for suffix in ("md", "csv", "json"))
        assert f"leaderboards/{board}/summary.md" in (output / "summary.md").read_text()

    ab = read_json(output / "leaderboards/AgentBuilder/summary.json")
    assert len(ab) == 1 and ab[0]["model"] == "page-model"
    assert ab[0]["source_backend"] == "OmniDocBench"
    assert ab[0]["evaluation_unit"] == "page"
    assert ab[0]["agentbuilder_overall"] == pytest.approx(0.78)
    assert ab[0]["title"] == 0.6
    assert "mp-only-model" not in (output / "leaderboards/AgentBuilder/summary.md").read_text()

    for board, model in (("OmniDocBench", "page-model"), ("MPDocBench", "mp-only-model")):
        directory = output / "leaderboards" / board
        native = read_json(directory / "summary.json")
        assert len(native) == 1 and native[0]["model"] == model
        assert all("agentbuilder_overall" not in row and "title" not in row for row in native)
        columns = _csv_columns(directory / "summary.csv")
        assert "agentbuilder_overall" not in columns and "title" not in columns
        if board == "OmniDocBench":
            assert "omnidocbench_overall" in columns
            assert native[0]["omnidocbench_overall"] is None
        else:
            assert native[0]["head_teds"] == 0.1
            assert native[0]["merged_table_teds"] == 0.2
            assert "omnidocbench_overall" not in columns


def test_mp_only_old_report_cannot_create_an_agentbuilder_entry(tmp_path):
    reports = tmp_path / "reports"
    _saved_report(
        reports,
        "old-mp-result",
        "MPDocBench",
        "standard",
        {
            "text_accuracy": 1.0,
            "table_teds": 1.0,
            "reading_order_accuracy": 1.0,
            "title": 1.0,
            "agentbuilder_overall": 1.0,
            "head_teds": 0.8,
        },
    )
    output = tmp_path / "summary"
    collect_reports([reports], output)
    assert read_json(output / "leaderboards/AgentBuilder/summary.json") == []
    assert read_json(output / "leaderboards/OmniDocBench/summary.json") == []
    assert len(read_json(output / "leaderboards/MPDocBench/summary.json")) == 1
    assert read_json(output / "summary.json")[0]["agentbuilder_overall"] is None


def test_agentbuilder_zero_score_is_a_computed_entry_not_missing(tmp_path):
    reports = tmp_path / "reports"
    _saved_report(
        reports,
        "zero-model",
        "OmniDocBench",
        "standard",
        {
            "text_accuracy": 0.0,
            "table_teds": 0.0,
            "reading_order_accuracy": 0.0,
            "title": 0.0,
            "formula_cdm": None,
            "agentbuilder_overall": None,
        },
    )
    output = tmp_path / "summary"
    collect_reports([reports], output)
    board = read_json(output / "leaderboards/AgentBuilder/summary.json")
    assert len(board) == 1
    assert board[0]["model"] == "zero-model"
    assert board[0]["agentbuilder_overall"] == 0.0


def test_collect_keeps_profiles_separate_and_ranks_agentbuilder_within_each_profile(tmp_path):
    roots = []
    scores = {
        "standard": {"model-a": 0.6, "model-z": 0.8},
        "legacy": {"model-a": 0.9, "model-z": 0.4},
    }
    for profile, models in scores.items():
        root = tmp_path / profile
        for model, score in models.items():
            # Full components produce this score. Stored aggregates are deliberately stale.
            _saved_report(
                root,
                model,
                "OmniDocBench",
                profile,
                {
                    "text_accuracy": score,
                    "table_teds": score,
                    "reading_order_accuracy": score,
                    "title": score,
                    "agentbuilder_overall": 1 - score,
                },
            )
        roots.append(root)
    output = tmp_path / "summary"
    result = collect_reports(roots, output)
    assert result["evaluations"] == 4
    raw = read_json(output / "summary.json")
    assert len(raw) == 4
    assert {r["preprocessing_profile"] for r in raw} == {"standard", "legacy"}
    board = read_json(output / "leaderboards/AgentBuilder/summary.json")
    groups = [
        (profile, list(rows))
        for profile, rows in groupby(board, key=lambda r: r["preprocessing_profile"])
    ]
    assert len(groups) == 2
    assert {profile for profile, _ in groups} == {"standard", "legacy"}
    for profile, rows in groups:
        assert [r["rank"] for r in rows] == [1, 2]
        assert [r["agentbuilder_overall"] for r in rows] == sorted(
            scores[profile].values(), reverse=True
        )
        assert [r["model"] for r in rows] == sorted(
            scores[profile], key=scores[profile].get, reverse=True
        )
