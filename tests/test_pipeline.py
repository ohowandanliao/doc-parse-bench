from pathlib import Path

import pytest
import yaml

from doc_parse_bench import pipeline
from doc_parse_bench.cli import build_parser
from doc_parse_bench.io import read_json, sha256, write_json


def test_legacy_switch_changes_preprocessing_without_changing_gt_or_evaluators(
    tmp_path, monkeypatch
):
    source = tmp_path / "annotations"
    write_json(
        source / "runs/doc/page_0001/result.json",
        {
            "page": 1,
            "revision": {
                "blocks": [
                    {
                        "block_id": "heading",
                        "type": "title",
                        "text": "Heading",
                        "level": 1,
                        "reading_order": 0,
                        "bbox_normalized": [0.1, 0.1, 0.9, 0.2],
                    }
                ]
            },
        },
    )
    write_json(
        tmp_path / "pred/doc.json",
        {
            "pages": [
                {
                    "page": 1,
                    "blocks": None,
                    "md": "# Heading\n\n![chart](data:image/png;base64,AAAA)\n\n"
                    "<details><summary>bar</summary><table><tr><td>42</td></tr></table></details>",
                }
            ]
        },
    )

    def capture(prepared, output, **settings):
        return {
            "gt": {b: sha256(prepared / "gt" / b / "gt.json") for b in settings["backends"]},
            "markdown": (prepared / "pred/model/OmniDocBench/doc__p0001.md").read_text(),
            "settings": settings,
        }

    monkeypatch.setattr(pipeline, "benchmark", capture)
    config = {
        "profile": "standard",
        "input_format": "annotations",
        "backends": ["OmniDocBench", "MPDocBench"],
        "annotations": "annotations",
        "models": {"model": {"adapter": "OvisOCR2", "source": "pred"}},
    }
    config_path = tmp_path / "run.yaml"
    outputs = []
    for legacy in (False, True):
        config["output"] = f"run-{legacy}"
        config_path.write_text(yaml.safe_dump(config))
        outputs.append(pipeline.run(config_path, legacy_preprocessing=legacy))
    standard, legacy = outputs
    assert standard["gt"] == legacy["gt"]
    assert "data:image/png;base64,AAAA" in standard["markdown"]
    assert "<details>" in standard["markdown"]
    assert "data:image" not in legacy["markdown"] and "<details>" not in legacy["markdown"]
    assert "<table>" in legacy["markdown"]
    assert "# Heading" in standard["markdown"] and "# Heading" in legacy["markdown"]
    for key in standard["settings"]:
        if key != "preprocessing":
            assert standard["settings"][key] == legacy["settings"][key]
    assert legacy["settings"]["figure"] and legacy["settings"]["relations"]
    recorded = read_json(tmp_path / "run-True/run.json")
    assert recorded["backends"] == ["OmniDocBench", "MPDocBench"]
    assert recorded["input_format"] == "annotations"
    assert recorded["preprocessing"]["profile"] == "legacy"


def test_historical_evaluator_is_selected_by_input_not_preprocessing(tmp_path, monkeypatch):
    (tmp_path / "pred").mkdir()
    (tmp_path / "pred/doc.md").write_text("# Heading")
    config = {
        "profile": "standard",
        "input_format": "markdown",
        "backends": ["legacy_compat"],
        "ground_truth": "gt",
        "output": "output",
        "models": {"model": {"source": "pred"}},
    }
    path = tmp_path / "run.yaml"
    path.write_text(yaml.safe_dump(config))
    calls = []

    def capture(backend, gt, predictions, output, **settings):
        calls.append((backend, settings))
        write_json(output / "metrics.json", {"title": 1, "agentbuilder_overall": 1})
        write_json(
            output / "provenance.json",
            {
                "backend": backend,
                "expected": 1,
                "provided": 1,
                "preprocessing": settings["preprocessing"],
            },
        )

    monkeypatch.setattr(pipeline, "evaluate", capture)
    pipeline.run(path)
    assert calls[0][0] == "legacy_compat"
    assert calls[0][1]["preprocessing"]["profile"] == "standard"
    assert not calls[0][1]["preprocessing"]["replace_embedded_images"]
    with pytest.raises(ValueError, match="缺少页面关系"):
        pipeline.run(path, {"merge_context": True})


def test_supplied_profiles_only_change_preprocessing():
    root = Path(__file__).parents[1] / "configs"
    standard = yaml.safe_load((root / "standard.yaml").read_text())
    legacy = yaml.safe_load((root / "legacy.yaml").read_text())
    for key in ("annotations", "input_format", "backends", "models"):
        assert standard[key] == legacy[key]
    parser = build_parser()
    assert parser.parse_args(["run", "config.yaml", "--legacy"]).legacy is True
    assert parser.parse_args(["run", "config.yaml", "--no-legacy"]).legacy is False
