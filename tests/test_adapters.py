from doc_parse_bench.context import infer_context, render_document
from doc_parse_bench.io import write_json
from doc_parse_bench.markdown import merge_tables, parse_markdown, render_page
from doc_parse_bench.predictions import import_predictions, parse_unlimited_ocr2
from doc_parse_bench.schema import Block, Document, Page


def test_unlimited_ocr2_recovers_level_tokens_blank_pages_and_native_chains():
    raw = (
        "<PAGE><BLOCK>title<LEVEL2>[10,20,900,60]<FORK>Heading"
        "<BLOCK>cross_text[10,800,900,950]<FORK>contin"
        "<PAGE><PAGE><BLOCK>append_text[10,20,900,80]<FORK>uation"
    )
    doc = parse_unlimited_ocr2(raw, "doc")
    assert len(doc.pages) == 3 and doc.pages[1].blocks == []
    assert doc.pages[0].blocks[0].level == 2
    assert "## Heading" in render_page(doc.pages[0])
    assert "continuation" in render_document(doc)
    assert "LEVEL" not in render_document(doc)


def test_ovis_preserves_tables_titles_and_visual_coordinates():
    text = '# Root\n\n<table><tr><td>a</td></tr></table>\n\nText <img src="images/bbox_10_20_900_800.jpg" /> tail'
    blocks = parse_markdown(text, 1)
    assert [b.type for b in blocks] == ["title", "table", "text", "image", "text"]
    assert blocks[3].bbox == [0.01, 0.02, 0.9, 0.8]
    assert "page1_10_20_900_800.jpg" in render_page(Page(1, blocks))


def test_linked_tables_keep_rowspan_and_drop_repeated_header():
    fragments = [
        '<table><tr><th>A</th><th>B</th></tr><tr><td rowspan="2">x</td><td>1</td></tr></table>',
        "<table><tr><th>A</th><th>B</th></tr><tr><td>2</td></tr></table>",
    ]
    merged = merge_tables(fragments)
    assert merged.count("<tr>") == 3
    assert 'rowspan="2"' in merged


def test_context_never_crosses_explicit_source_gap():
    a = Block("a", "text", "sentence with an open", bbox=[0.1, 0.8, 0.9, 0.95])
    b = Block("b", "text", "continuation", bbox=[0.1, 0.05, 0.9, 0.2])
    doc = Document(
        "doc",
        [Page(1, [a], metadata={"original_page": 2}), Page(2, [b], metadata={"original_page": 7})],
    )
    assert not infer_context(doc, "conservative").relations
    doc.pages[1].metadata["original_page"] = 3
    result = infer_context(doc, "conservative")
    assert len(result.relations) == 1
    assert not doc.relations


def test_native_invalid_heading_depth_is_preserved_for_evaluation():
    # Never silently improve a malformed LEVEL10 prediction by clamping it to LEVEL6.
    block = Block("title", "title", "Heading", level=10)
    assert render_page(Page(1, [block])).startswith("########## Heading")


def test_source_page_map_remains_valid_for_truncated_prediction(tmp_path):
    write_json(
        tmp_path / "source/doc.json",
        {
            "n_pages": 5,
            "pages": [
                {"page": 1, "md": "first", "blocks": None},
                {"page": 3, "md": "third", "blocks": None},
            ],
        },
    )
    write_json(tmp_path / "map.json", {"doc": {"original_page_numbers": [19, 20, 21, 25, 30]}})
    import_predictions(tmp_path / "source", tmp_path / "result", "OvisOCR2", tmp_path / "map.json")
    doc = Document.load(tmp_path / "result/documents/doc.json")
    assert [p.metadata["original_page"] for p in doc.pages] == [19, 21]
