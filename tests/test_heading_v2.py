import pytest

from doc_parse_bench import agentbuilder_v2
from doc_parse_bench.agentbuilder_v2 import _checked_predictions
from doc_parse_bench.heading import (
    compare_heading_trees,
    compute_title_tree_score,
    extract_headings,
    gt_heading_tree,
    markdown_heading_tree,
)
from doc_parse_bench.io import read_json, write_json
from doc_parse_bench.metrics import agentbuilder_v2_score


def test_commonmark_headings_ignore_code_html_and_display_math():
    text = """# **C++** [guide](https://example.com) ###

Setext heading
--------------

```python
# code
$$
```

    # indented code

<div>
# HTML block
</div>

\\[
\\Delta E
=
x
-
\\]

$$
E
=
mc^2
$$

#参数证明请见：https://example.com#/option

###
"""
    assert extract_headings(text) == [(1, "C++ guide"), (2, "Setext heading"), (3, "")]


@pytest.mark.parametrize(
    "gold,pred,score",
    [
        ("", "", 1),
        ("# A", "", 0),
        ("", "# A", 0),
        ("# A\n### B\n### C", "# A\n### B\n### C", 1),
        ("# A\n### B\n### C", "## A\n#### B\n#### C", 1),
        ("# C++", "# C", 1 / 3),
        ("# A\n## B\n### C\n#### D", "# A\n# B\n# C\n# D", 0),
    ],
)
def test_score_boundaries_symbols_and_tree_invariance(gold, pred, score):
    result = compute_title_tree_score(gold, pred)
    assert result["title_tree_v2"] == pytest.approx(score)
    assert 0 <= result["title_tree_v2"] <= 1


def test_body_retention_does_not_change_a_missing_heading_cost():
    gold = "# A\n## B\nB body\n## C\nC body"
    demoted = "# A\n## B\nB body\nC\nC body"
    deleted = "# A\n## B\nB body"
    for pred in [demoted, deleted]:
        result = compute_title_tree_score(gold, pred)
        assert result["tree_distance"] == 1
        assert result["title_tree_v2"] == pytest.approx(2 / 3)
    result = compute_title_tree_score(gold, "# A\n## B\nB body\n### C\nC body")
    assert result["tree_distance"] == 2


def test_gt_uses_numeric_reading_order_and_explicit_parent_relations():
    sample = {
        "layout_dets": [
            {"anno_id": "p10", "category_type": "title", "text": "Child", "order": 10},
            {"anno_id": "p2", "category_type": "title", "text": "A", "order": 2},
        ],
        "extra": {
            "relation": [
                {"relation_type": "parent_son", "source_anno_id": "root", "target_anno_id": "p2"},
                {"relation_type": "parent_son", "source_anno_id": "p2", "target_anno_id": "p10"},
            ]
        },
    }
    result = compare_heading_trees(gt_heading_tree(sample), markdown_heading_tree("# A\n### Child"))
    assert result["title_tree_v2"] == 1
    sample["extra"]["relation"][0]["source_anno_id"] = "p10"
    with pytest.raises(ValueError, match="环"):
        gt_heading_tree(sample)


def test_real_heading_named_root_is_not_an_anchor_and_unicode_is_normalized():
    assert compute_title_tree_score("# root", "")["title_tree_v2"] == 0
    assert compute_title_tree_score("# café", "# cafe\u0301")["title_tree_v2"] == 1


def test_agentbuilder_v2_requires_fixed_components_and_correct_source():
    metrics = {
        "text_accuracy": 0.9,
        "table_teds": 0.8,
        "reading_order_accuracy": 0.7,
        "title_tree_v2": 0,
    }
    assert agentbuilder_v2_score(metrics, "OmniDocBench") == pytest.approx(0.72)
    for key in metrics:
        assert agentbuilder_v2_score({**metrics, key: None}, "OmniDocBench") is None
    with pytest.raises(ValueError, match="OmniDocBench"):
        agentbuilder_v2_score(metrics, "MPDocBench")
    with pytest.raises(ValueError, match=r"\[0,1\]"):
        agentbuilder_v2_score({**metrics, "title_tree_v2": -0.1}, "OmniDocBench")


def test_retest_rejects_changed_input_including_previously_missing_pages(tmp_path):
    provenance = {"gt_sha256": "gt", "prediction_sha256": {"doc.md": None}}
    assert _checked_predictions(tmp_path, provenance, ["doc.md"], "gt") == {"doc.md": ""}
    (tmp_path / "doc.md").write_text("new content")
    with pytest.raises(ValueError, match="非空内容"):
        _checked_predictions(tmp_path, provenance, ["doc.md"], "gt")
    with pytest.raises(ValueError, match="GT 不一致"):
        _checked_predictions(tmp_path, provenance, ["doc.md"], "changed gt")


@pytest.mark.parametrize("include_raw_model", [False, True])
def test_rescore_evaluates_prepared_predictions_with_optional_mineru_raw(
    tmp_path, monkeypatch, include_raw_model
):
    gt = tmp_path / "gt"
    write_json(gt / "OmniDocBench/gt.json", [{"page_info": {"image_path": "doc__p0001.jpg"}}])
    write_json(
        gt / "MPDocBench/gt.json",
        [
            {
                "page_info": {"image_path": "doc.pdf"},
                "layout_dets": [
                    {"anno_id": "title", "category_type": "title", "text": "Full title", "order": 1}
                ],
                "extra": {
                    "relation": [
                        {
                            "source_anno_id": "root",
                            "target_anno_id": "title",
                            "relation_type": "parent_son",
                        }
                    ]
                },
            }
        ],
    )
    title_gt = gt / "MPDocBench/markdown/doc.md"
    title_gt.parent.mkdir()
    title_gt.write_text("# Full title", encoding="utf-8")

    def make_predictions(directory, text):
        omni = directory / "OmniDocBench"
        omni.mkdir(parents=True)
        (omni / "doc__p0001.md").write_text(text, encoding="utf-8")
        mp = directory / "MPDocBench"
        mp.mkdir()
        (mp / "doc.md").write_text("# Full title", encoding="utf-8")

    make_predictions(tmp_path / "ovis", "Original page")
    inputs = tmp_path / "inputs.json"
    settings = {
        "base_directory": ".",
        "gt": "gt",
        "models": [{"model": "OvisOCR2", "predictions": "ovis"}],
    }
    if include_raw_model:
        settings["pdf2text_config"] = "p2t.json"
        settings["models"].append({"model": "MinerU-3.x", "raw": "raw"})
    write_json(inputs, settings)

    exported = []

    def export(raw, config, directory, *, include_documents):
        assert raw == tmp_path / "raw"
        assert config == tmp_path / "p2t.json"
        assert include_documents
        exported.append(raw)
        make_predictions(directory, "Restored page")
        return {"restored_tables": 2}

    def evaluate(backend, gold, predictions, report, **options):
        assert backend == "OmniDocBench"
        assert gold == gt / "OmniDocBench/gt.json"
        assert options["title_gt"] == gt / "OmniDocBench/markdown"
        text = (predictions / "doc__p0001.md").read_text(encoding="utf-8")
        assert text == ("Original page" if report.parent.name == "OvisOCR2" else "Restored page")
        write_json(report / "provenance.json", {"provided": 1, "expected": 1})
        return {"text_accuracy": 0.9, "table_teds": 0.8, "reading_order_accuracy": 0.7, "title": 0}

    monkeypatch.setattr(agentbuilder_v2, "export_mineru_predictions", export)
    monkeypatch.setattr(agentbuilder_v2, "evaluate", evaluate)
    result = agentbuilder_v2.rescore_agentbuilder(inputs, tmp_path / "output")

    rows = {row["model"]: row for row in read_json(tmp_path / "output/summary.json")}
    assert result["models"] == len(settings["models"])
    assert len(exported) == int(include_raw_model)
    assert rows["OvisOCR2"]["restored_tables"] is None
    if include_raw_model:
        assert rows["MinerU-3.x"]["restored_tables"] == 2
    for row in rows.values():
        assert row["title_tree_v2"] == 1
        assert row["agentbuilder_v2_overall"] == pytest.approx(0.82)
