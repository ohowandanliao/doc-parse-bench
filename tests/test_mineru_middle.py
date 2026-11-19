import json
from pathlib import Path

from doc_parse_bench.mineru_middle import (
    apply_pdf2text_filters,
    extract_middle_json,
    extract_pdf_info,
    pdf_info_to_document,
    response_to_document,
)

FILTER_SOURCE = Path(
    "archives/pdf2text-feature-20261119/source-ditto/pdf2text-78712-pdf-rule-toggle-test-1806ec1/src"
)


def _span(kind="text", content=""):
    return {"type": kind, "content": content}


def _response():
    pdf_info = [
        {
            "page_idx": 2,
            "page_size": [1000, 2000],
            "para_blocks": [
                {
                    "id": "header-1",
                    "type": "header",
                    "bbox": [100, 100, 500, 200],
                    "lines": [{"spans": [_span(content="页眉")]}],
                },
                {
                    "id": "chart-1",
                    "type": "chart",
                    "bbox": [100, 400, 900, 1200],
                    "blocks": [
                        {
                            "type": "chart_body",
                            "html": "<table><tr><td>42</td></tr></table>",
                            "lines": [{"spans": [_span(content="42")]}],
                        },
                        {
                            "type": "chart_caption",
                            "lines": [{"spans": [_span(content="图 1")]}],
                        },
                    ],
                },
                {
                    "id": "image-1",
                    "type": "image",
                    "bbox": [100, 1300, 900, 1900],
                    "blocks": [
                        {
                            "type": "image_body",
                            "lines": [
                                {
                                    "spans": [
                                        {
                                            "type": "image",
                                            "content": "模型生成描述",
                                            "generated": True,
                                        }
                                    ]
                                }
                            ],
                        }
                    ],
                },
            ],
            "discarded_blocks": [],
        }
    ]
    return {
        "pages": 3,
        "results": {"sample.pdf": {"middle_json": json.dumps({"pdf_info": pdf_info})}},
    }


def test_extract_middle_json_and_page_idx():
    response = _response()
    assert extract_middle_json(response)["pdf_info"][0]["page_idx"] == 2
    assert extract_pdf_info(response)[0]["page_idx"] == 2
    document = pdf_info_to_document(extract_pdf_info(response), document_id="sample")
    assert document.pages[0].number == 3
    assert document.pages[0].blocks[0].bbox == [0.1, 0.05, 0.5, 0.1]
    assert document.metadata["page_boundaries"] == "explicit"


def test_header_footer_keep_preserves_raw_type_metadata():
    document = response_to_document(
        _response(),
        document_id="sample",
        pdf2text_source=FILTER_SOURCE,
        filter_options={
            "keep_header_footer": True,
            "keep_appendix": True,
            "image_analysis": True,
            "chart_analysis": True,
            "relevel_titles": False,
        },
    )
    header = document.pages[0].blocks[0]
    assert header.type == "text"
    assert header.metadata["raw_type"] == "header"
    assert header.metadata["source_type"] == "header"


def test_chart_off_becomes_image_and_clears_chart_body():
    filtered = apply_pdf2text_filters(
        extract_pdf_info(_response()),
        pdf2text_source=FILTER_SOURCE,
        keep_appendix=True,
        keep_header_footer=False,
        image_analysis=True,
        chart_analysis=False,
        relevel_titles=False,
    )
    chart = next(block for block in filtered[0]["para_blocks"] if block["id"] == "chart-1")
    assert chart["type"] == "image"
    body = chart["blocks"][0]
    assert body["lines"][0]["spans"][0]["content"] == ""
    document = pdf_info_to_document(filtered, document_id="sample")
    ir_chart = next(block for block in document.pages[0].blocks if block.id == "chart-1")
    assert ir_chart.type == "image"
    assert ir_chart.metadata["raw_type"] == "chart"


def test_image_analysis_off_clears_generated_image_span():
    filtered = apply_pdf2text_filters(
        extract_pdf_info(_response()),
        pdf2text_source=FILTER_SOURCE,
        keep_appendix=True,
        image_analysis=False,
        chart_analysis=True,
        relevel_titles=False,
    )
    image = next(block for block in filtered[0]["para_blocks"] if block["id"] == "image-1")
    span = image["blocks"][0]["lines"][0]["spans"][0]
    assert span["content"] == ""
    document = pdf_info_to_document(filtered, document_id="sample")
    ir_image = next(block for block in document.pages[0].blocks if block.id == "image-1")
    assert ir_image.metadata["generated_spans"][0]["generated"] is True
