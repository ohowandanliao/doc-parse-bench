from pathlib import Path

import pytest

from doc_parse_bench.annotations import import_annotations
from doc_parse_bench.exporters import export_gt
from doc_parse_bench.io import read_json, write_json
from doc_parse_bench.schema import Document


def test_snapshot_replaces_chain_including_empty_page(tmp_path):
    source = tmp_path / "input"
    for number in (1, 2):
        write_json(
            source / f"runs/doc/page_{number:04d}/result.json",
            {
                "page": number,
                "revision": {
                    "blocks": [
                        {
                            "block_id": f"p{number}",
                            "type": "text",
                            "text": "old",
                            "reading_order": 0,
                            "bbox_normalized": [0, 0, 1, 1],
                        }
                    ]
                },
            },
        )
    write_json(source / "annotated/doc/page_0001.json", {"page": 1, "blocks": []})
    report = import_annotations(source, tmp_path / "out")
    doc = Document.load(tmp_path / "out/documents/doc.json")
    assert report["patch_pages"] == 1 and report["chain_pages"] == 1
    assert doc.pages[0].blocks == []
    assert doc.pages[1].blocks[0].text == "old"


def test_multiple_annotators_need_explicit_selection(tmp_path):
    write_json(tmp_path / "input/runs/doc/page_0001/result.json", {"revision": {"blocks": []}})
    for annotator in ("a", "b"):
        write_json(tmp_path / f"input/annotations/doc/{annotator}/page_0001.json", {"blocks": []})
    with pytest.raises(ValueError, match="多个标注快照"):
        import_annotations(tmp_path / "input", tmp_path / "out")


def test_real_gt_page_counts_and_cross_page_export(tmp_path):
    source = Path(__file__).parents[1] / "data/annotations"
    if not source.exists():
        pytest.skip("本地标注包未提供")
    audit = import_annotations(source, tmp_path / "ir")
    runs = list((source / "runs").glob("*/page_*/result.json"))
    patch_pages = sum(
        (source / "annotations" / p.parent.parent.name / (p.parent.name + ".json")).exists()
        for p in runs
    )
    assert audit["documents"] == len({p.parent.parent.name for p in runs})
    assert audit["pages"] == len(runs)
    assert audit["patch_pages"] == patch_pages
    assert audit["chain_pages"] == len(runs) - patch_pages
    assert not audit["issues"]
    export_gt(tmp_path / "ir/documents", tmp_path / "export")
    mpdocbench = read_json(tmp_path / "export/MPDocBench/gt.json")
    assert len(mpdocbench) == audit["documents"]
    assert sum(len(d["page_info"]["width"]) for d in mpdocbench) == audit["pages"]
    for doc in mpdocbench:
        ids = {b["anno_id"] for b in doc["layout_dets"]}
        orders = {b["anno_id"]: b["order"] for b in doc["layout_dets"]}
        edges = [r for r in doc["extra"]["relation"] if r["relation_type"] == "truncated"]
        assert [orders[r["source_anno_id"]] for r in edges] == sorted(
            orders[r["source_anno_id"]] for r in edges
        )
        for relation in doc["extra"]["relation"]:
            assert relation["source_anno_id"] in ids | {"root"}
            assert relation["target_anno_id"] in ids
