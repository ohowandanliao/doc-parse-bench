import json
from collections import Counter
from hashlib import sha256
from zipfile import ZipFile

import pytest

from doc_parse_bench.cli import main
from doc_parse_bench.feature_evaluation.feature_rubric import GT_SCHEMA
from doc_parse_bench.feature_evaluation.legacy129 import build_report
from doc_parse_bench.feature_evaluation.legacy129.score_batch import _observe_visual
from doc_parse_bench.io import read_json, write_json
from doc_parse_bench.schema import Block


@pytest.mark.parametrize(
    ("image_content", "auto_score"),
    [("Printed\nlabel", 100), ("Printed label\nExtra content", None)],
)
def test_batch_reads_html_anchors_and_uses_image_only_evidence(
    tmp_path, capsys, image_content, auto_score
):
    document_id = "unseen-document"
    gt_path = tmp_path / "gt.json"
    sources_path = tmp_path / "sources.json"
    write_json(
        gt_path,
        {
            "schema_version": GT_SCHEMA,
            "gt_version": "new-dataset",
            "split": "evaluation",
            "cases": [
                {
                    "id": "appendix-page",
                    "document_id": document_id,
                    "page": 2,
                    "feature": "appendix",
                    "anchors": ["321.09"],
                },
                {
                    "id": "figure",
                    "document_id": document_id,
                    "page": 1,
                    "feature": "image",
                    "source_id": "image-region",
                    "bbox": [0.1, 0.1, 0.8, 0.8],
                    "sub_type": "text_image",
                    "fields": [{"key": "label", "text": "Printed label"}],
                },
                {
                    "id": "chart",
                    "document_id": document_id,
                    "page": 1,
                    "feature": "chart",
                    "source_id": "chart-region",
                    "bbox": [0.1, 0.82, 0.8, 0.98],
                    "values": [{"series": "Value", "category": "A", "value": "12", "unit": ""}],
                },
            ],
        },
    )
    document = {
        "document_id": document_id,
        "source_pdf": "sample.pdf",
        "pdf_sha256": "pdf-fingerprint",
        "pages": 2,
    }
    write_json(sources_path, {"documents": [document]})
    chart_html = (
        "<table><tr><th>Group</th><th>Value</th></tr><tr><td>A</td><td>12</td></tr></table>"
    )
    table_html = "<table><tr><td>321.09</td></tr></table>"
    appendix_page = {
        "page_idx": 1,
        "page_size": [1000, 1000],
        "para_blocks": [
            {
                "type": "table",
                "bbox": [100, 100, 800, 800],
                "blocks": [{"type": "table_body", "lines": [{"spans": [{"html": table_html}]}]}],
            }
        ],
    }
    archive_path = tmp_path / "finals.zip"
    prefix = f"new-model/documents/{document_id}"
    with ZipFile(archive_path, "w") as archive:
        manifest = document | {"source_pages": 2, "status": "ok"}
        archive.writestr(f"{prefix}/document.json", json.dumps(manifest))
        for group in build_report.GROUPS:
            label = {"image_only": image_content, "both_on": "Other label"}.get(group)
            body = []
            if label:
                body = [
                    {
                        "id": "figure-block",
                        "type": "image",
                        "sub_type": "text_image",
                        "bbox": [100, 100, 800, 800],
                        "lines": [{"spans": [{"type": "image", "content": label}]}],
                    }
                ]
            pages = [{"page_idx": 0, "page_size": [1000, 1000], "para_blocks": body}]
            markdown = label or ""
            if group == "both_on":
                body.append(
                    {
                        "type": "chart",
                        "bbox": [90, 810, 840, 990],
                        "blocks": [
                            {"type": "chart_body", "lines": [{"spans": [{"html": chart_html}]}]}
                        ],
                    }
                )
                markdown += f"\n{chart_html}"
            if group != "appendix_off":
                pages.append(appendix_page)
                markdown += f"\n{table_html}"
            data = json.dumps({"pdf_info": pages})
            source = {"capture_sha256": f"capture-{group}"}
            if group in {"appendix_off", "header_footer_on"}:
                source = {"base_capture_sha256": "capture-both_off"}
            meta = {
                "document_id": document_id,
                "variant": group,
                "pages": len(pages),
                "source": source,
                "relevel_applied": True,
                "filters": {
                    "image_analysis": "true" if label else "false",
                    "chart_analysis": group in {"both_on", "chart_only"},
                    "keep_header_footer": group == "header_footer_on",
                    "keep_appendix": group != "appendix_off",
                    "title_rules": False,
                },
                "middle_json_sha256": sha256(data.encode()).hexdigest(),
                "markdown_sha256": sha256(markdown.encode()).hexdigest(),
                "assets": [],
            }
            archive.writestr(f"{prefix}/final/{group}/middle_json.json", data)
            archive.writestr(f"{prefix}/final/{group}/final.md", markdown)
            archive.writestr(f"{prefix}/final/{group}/meta.json", json.dumps(meta))

    output = tmp_path / "score"
    command = [
        "evaluate-legacy129",
        "--zip",
        str(archive_path),
        "--model",
        "new-model",
        "--gt",
        str(gt_path),
        "--sources",
        str(sources_path),
    ]
    main([*command, "--output", str(output)])
    capsys.readouterr()
    scores = read_json(output / "scores/metrics.json")
    assert scores["features"]["appendix"]["score"] == 100
    assert scores["features"]["chart"]["score"] == 100
    assert read_json(output / "scores/per_case.json")["figure"]["score"] == auto_score
    assert scores["overall_status"] == "pending_evidence"
    pending = read_json(output / "visual_review.json")
    if auto_score is None:
        assert pending["figure"]["reason"] == "field_attribution_needs_review"
        assert pending["figure"]["capture_sha256"] == "capture-image_only"
        assert pending["figure"]["candidates"][0]["content"] == [image_content]
    else:
        assert pending == {}

    reviewed = read_json(output / "evidence.json")
    reviewed["cases"]["figure"] = {
        "sub_type": "text_image",
        "subtype_id": "figure-block",
        "fields": [{"id": "figure-block:0", "key": "label", "text": "Printed label"}],
    }
    review_path = tmp_path / "review.json"
    write_json(review_path, reviewed)
    command.extend(["--reviewed-evidence", str(review_path)])
    reviewed_output = tmp_path / "reviewed-score"
    main([*command, "--output", str(reviewed_output)])
    assert read_json(reviewed_output / "scores/per_case.json")["figure"]["score"] == 100

    reviewed["image_only_captures"][document_id] = "capture-both_on"
    write_json(review_path, reviewed)
    stale_output = tmp_path / "stale-score"
    with pytest.raises(SystemExit) as error:
        main([*command, "--output", str(stale_output)])
    assert error.value.code == 1
    assert "图片复核证据与 image_only 回包不符" in capsys.readouterr().err
    assert not stale_output.exists()


def test_one_visual_block_cannot_supply_two_source_figures():
    block = Block("merged-figure", "image", bbox=[0.1, 0.1, 0.8, 0.8])
    observation, reason = _observe_visual(
        {"feature": "image", "bbox": [0.1, 0.1, 0.5, 0.8]},
        [block],
        Counter({block.id: 2}),
        "",
        {},
        set(),
    )
    assert observation is None
    assert reason == "ambiguous_source_block"
