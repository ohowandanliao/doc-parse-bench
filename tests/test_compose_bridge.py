from doc_parse_bench.compose_bridge import composition_input, render_composition
from doc_parse_bench.schema import Block, Document, Page


def test_composition_bridge_retains_native_visuals_details_and_annotations():
    chart = Block(
        "chart",
        "chart",
        "| x | y |",
        bbox=[0.1, 0.2, 0.8, 0.7],
        metadata={"visual_details": "<details><summary>bar</summary>table</details>"},
    )
    doc = Document("d", [Page(1, [chart, Block("caption", "image_caption", "Chart caption")])])
    raw = composition_input(doc)
    assert raw["pages"][0]["blocks"][0]["type"] == "image"
    assert raw["pages"][0]["blocks"][0]["bench_block"]["type"] == "chart"
    fragment = {
        "id": "f1",
        "page": 1,
        "raw_markdown": "![](image)",
        "content": {"mineru_block": raw["pages"][0]["blocks"][0]},
    }
    ir = {
        "pages": [{"page": 1}],
        "fragments": [fragment],
        "reading_order": ["e1"],
        "elements": [{"id": "e1", "type": "figure", "fragments": ["f1"], "content": {}}],
    }
    pages, document, audit = render_composition(ir, lambda value: value["html"])
    assert "page1_100_200_800_700.jpg" in pages[1]
    assert "<details>" in document and pages[1] == document
    assert audit["ground_truth_used"] is False


def test_cross_page_composition_projects_fragments_without_moving_table_to_first_page():
    ir = {
        "pages": [{"page": 1}, {"page": 2}],
        "fragments": [
            {"id": "f1", "page": 1, "raw_markdown": "<table>A</table>", "content": {}},
            {"id": "f2", "page": 2, "raw_markdown": "<table>B</table>", "content": {}},
            {"id": "header", "page": 2, "raw_markdown": "Repeated header", "content": {}},
        ],
        "elements": [
            {
                "id": "t",
                "type": "table",
                "fragments": ["f1", "f2"],
                "content": {"html": "<table>AB</table>"},
            },
            {
                "id": "h",
                "type": "paragraph",
                "fragments": ["header"],
                "role": "header",
                "content": {"text": "Repeated header"},
            },
        ],
        "reading_order": ["t", "h"],
    }
    pages, document, audit = render_composition(ir, lambda value: value["html"])
    assert pages == {1: "<table>A</table>\n", 2: "<table>B</table>\n"}
    assert document == "<table>AB</table>\n"
    assert audit["hidden_furniture_fragments"] == ["header"]
    assert audit["cross_page_elements"][0]["pages"] == [1, 2]
