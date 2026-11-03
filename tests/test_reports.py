from doc_parse_bench.benchmark import collect_reports
from doc_parse_bench.io import read_json, write_json


def test_reports_show_native_metrics_and_agentbuilder_for_each_backend(tmp_path):
    reports = tmp_path / "reports"
    for backend in ("OmniDocBench", "MPDocBench", "legacy"):
        directory = reports / "model" / backend
        write_json(
            directory / "provenance.json",
            {
                "backend": backend,
                "expected": 2 if backend == "OmniDocBench" else 1,
                "provided": 2 if backend == "OmniDocBench" else 1,
                "preprocessing": {"profile": "legacy"},
            },
        )
        metrics = {
            "agentbuilder_overall": 0.78,
            "title": 0.6,
            "table_teds": 0.8,
            "table_accuracy": 0.7,
            "table_teds_s": 0.9,
            "formula_accuracy": 0.4,
        }
        if backend == "MPDocBench":
            metrics.update({"merged_table_teds": 0.2, "head_teds": 0.1})
        if backend == "legacy":
            metrics["legacy_stage_overall"] = 0.8
        write_json(directory / "metrics.json", metrics)

    collect_reports([reports], tmp_path / "summary")
    rows = read_json(tmp_path / "summary/summary.json")
    assert len(rows) == 3
    assert all(row["agentbuilder_overall"] == 0.78 for row in rows)
    assert all(row["preprocessing_profile"] == "legacy" for row in rows)
    assert {row["backend"] for row in rows} == {"OmniDocBench", "MPDocBench", "legacy_compat"}
    markdown = (tmp_path / "summary/summary.md").read_text()
    sections = markdown.split("\n## ")[1:]
    assert len(sections) == 3
    omni, mp, legacy = sections
    for section in sections:
        assert "agentbuilder_overall" in section and "title" in section
        assert "formula_accuracy" in section and "table_accuracy" in section
    assert "omnidocbench_overall" in omni and "merged_table_teds" not in omni
    assert "merged_table_teds" in mp and "head_teds" in mp
    assert "omnidocbench_overall" not in mp
    assert "legacy_stage_overall" in legacy and "head_teds" not in legacy
    assert "historical_scores" not in markdown


def test_collect_allows_same_model_and_backend_with_different_preprocessing(tmp_path):
    roots = []
    for profile in ("standard", "legacy"):
        root = tmp_path / profile
        report = root / "model/OmniDocBench"
        write_json(
            report / "provenance.json",
            {
                "backend": "OmniDocBench",
                "expected": 1,
                "provided": 1,
                "preprocessing": {"profile": profile},
            },
        )
        write_json(report / "metrics.json", {"agentbuilder_overall": 0.8})
        roots.append(root)
    result = collect_reports(roots, tmp_path / "summary")
    assert result["evaluations"] == 2
    assert {r["preprocessing_profile"] for r in read_json(tmp_path / "summary/summary.json")} == {
        "standard",
        "legacy",
    }
