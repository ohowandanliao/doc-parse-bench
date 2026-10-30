import shutil

from doc_parse_bench.annotations import import_annotations
from doc_parse_bench.exporters import export_gt
from doc_parse_bench.io import read_json, sha256, write_json


def source_pack(path):
    write_json(
        path / "runs/doc/page_0001/result.json",
        {
            "sample_id": "doc",
            "page": 1,
            "revision": {
                "blocks": [
                    {
                        "block_id": "b1",
                        "type": "text",
                        "text": "Original",
                        "reading_order": 0,
                        "bbox_normalized": [0, 0, 1, 1],
                    }
                ]
            },
        },
    )
    write_json(path / "annotations/doc/document.json", {"status": "PASS", "reviewer": "reviewer"})


def test_input_fingerprint_survives_relocation_but_changes_on_annotation_revision(tmp_path):
    source_pack(tmp_path / "first")
    a = import_annotations(tmp_path / "first", tmp_path / "a", dataset_version="v1")
    shutil.copytree(tmp_path / "first", tmp_path / "moved")
    b = import_annotations(tmp_path / "moved", tmp_path / "b", dataset_version="v1")
    assert a["dataset_sha256"] == b["dataset_sha256"]
    write_json(
        tmp_path / "moved/annotations/doc/page_0001.json",
        {
            "blocks": [
                {
                    "block_id": "b1",
                    "type": "text",
                    "text": "Corrected",
                    "reading_order": 0,
                    "bbox_normalized": [0, 0, 1, 1],
                }
            ]
        },
    )
    c = import_annotations(tmp_path / "moved", tmp_path / "c", dataset_version="v2")
    assert c["dataset_sha256"] != a["dataset_sha256"]
    assert c["sources"][0]["selected_source"] == "patch"
    assert c["document_annotations"][0]["snapshot"]["reviewer"] == "reviewer"


def test_export_records_version_input_audit_and_both_gt_hashes(tmp_path):
    source_pack(tmp_path / "source")
    audit = import_annotations(tmp_path / "source", tmp_path / "ir", dataset_version="v1")
    manifest = export_gt(tmp_path / "ir/documents", tmp_path / "gt")
    assert manifest["dataset_version"] == "v1"
    assert manifest["source_dataset_sha256"] == audit["dataset_sha256"]
    assert read_json(tmp_path / "gt/source_audit.json") == audit
    for backend in ("OmniDocBench", "MPDocBench"):
        assert manifest["gt_sha256"][backend] == sha256(tmp_path / "gt" / backend / "gt.json")
    assert manifest["conversion"]["source_sha256"]


def test_export_does_not_attach_stale_audit_after_manual_intermediate_edit(tmp_path):
    source_pack(tmp_path / "source")
    import_annotations(tmp_path / "source", tmp_path / "ir", dataset_version="v1")
    file = tmp_path / "ir/documents/doc.json"
    document = read_json(file)
    document["pages"][0]["blocks"][0]["text"] = "Manual edit"
    write_json(file, document)
    manifest = export_gt(tmp_path / "ir/documents", tmp_path / "gt")
    assert manifest["source_dataset_sha256"] is None
    assert not (tmp_path / "gt/source_audit.json").exists()
    assert manifest["source_documents_sha256"][file.name] == sha256(file)
