from copy import deepcopy

import pytest

from doc_parse_bench.mineru_page_export import project_source_tables


def _table(html, *annotations):
    return {
        "type": "table",
        "index": 0,
        "bbox": [10, 10, 100, 100],
        "blocks": [
            {
                "type": "table_body",
                "lines": [{"spans": [{"type": "table", "html": html}]}],
            },
            *annotations,
        ],
    }


def test_project_source_tables_restores_both_pages_independently():
    note = {"type": "table_footnote", "lines": [{"spans": [{"content": "note"}]}]}
    caption = {"type": "table_caption", "lines": [{"spans": [{"content": "caption"}]}]}
    caption_as_text = {**caption, "type": "text"}
    first = _table('<table><tr><td rowspan="2">a</td></tr></table>')
    second = _table("<table><tr><td>b</td></tr></table>", caption, note)
    merged = _table("<table><tr><td>a</td></tr><tr><td>b</td></tr></table>", note)
    placeholder = _table("")
    placeholder["blocks"][0].update(lines=[], lines_deleted=True)
    heading = {"type": "title", "level": 2}
    pdf_info = [
        {"page_idx": 0, "preproc_blocks": [first], "para_blocks": [heading, merged]},
        {
            "page_idx": 1,
            "preproc_blocks": [second],
            "para_blocks": [placeholder, caption_as_text],
        },
        {"page_idx": 2, "para_blocks": []},
    ]
    original = deepcopy(pdf_info)

    projected, restored = project_source_tables(pdf_info)

    assert restored == [{"page": 1, "native_index": 0}, {"page": 2, "native_index": 0}]
    assert projected[0]["para_blocks"] == [heading, first]
    assert projected[1]["para_blocks"] == [
        _table("<table><tr><td>b</td></tr></table>", note),
        caption_as_text,
    ]
    assert projected[2] == pdf_info[2]
    projected[0]["para_blocks"][1]["blocks"].clear()
    assert pdf_info == original


@pytest.mark.parametrize("source_count", [0, 2])
def test_project_source_tables_rejects_missing_or_ambiguous_fragments(source_count):
    table = _table("<table><tr><td>a</td></tr></table>")
    with pytest.raises(ValueError, match="第 1 页表格 index=0 缺少唯一的合并前片段"):
        project_source_tables(
            [{"page_idx": 0, "preproc_blocks": [table] * source_count, "para_blocks": [table]}]
        )
