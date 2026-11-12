import pytest

from doc_parse_bench.agentbuilder_v2 import _checked_predictions
from doc_parse_bench.heading import (
    compare_heading_trees,
    compute_title_tree_score,
    extract_headings,
    gt_heading_tree,
    markdown_heading_tree,
)
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
