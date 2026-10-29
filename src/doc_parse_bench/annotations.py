"""Import annotation snapshots: patch.blocks replaces revision.blocks completely."""

from pathlib import Path

from .io import fresh_directory, read_json, sha256, write_json
from .schema import Block, Document, Page


def _page_from_path(path: Path) -> int:
    return int(path.stem.removeprefix("page_"))


def import_annotations(
    root: Path, output: Path, annotations: Path | None = None, document_map: Path | None = None
) -> dict:
    """Support both annotations/ and annotated/, or an explicitly supplied path."""
    runs = root / "runs"
    annotations = annotations or next(
        (p for p in (root / "annotations", root / "annotated") if p.is_dir()),
        root / "annotations",
    )
    files = sorted(runs.glob("*/page_*/result.json"))
    if not files:
        raise ValueError(f"未找到 runs/<doc>/page_*/result.json：{root}")
    patches = {path: False for path in annotations.rglob("page_*.json")}
    mapping = read_json(document_map) if document_map else {}
    grouped: dict[str, list[Path]] = {}
    for path in files:
        grouped.setdefault(path.parent.parent.name, []).append(path)
    output = fresh_directory(output)
    report = {
        "documents": len(grouped),
        "pages": 0,
        "patch_pages": 0,
        "chain_pages": 0,
        "blocks": 0,
        "issues": [],
        "sources": [],
    }
    for doc_id, paths in grouped.items():
        dimensions = _pdf_dimensions(root / "sources" / f"{doc_id}.pdf")
        pages = []
        for path in sorted(paths, key=lambda p: _page_from_path(p.parent)):
            number = _page_from_path(path.parent)
            chain = read_json(path)
            candidates = list(annotations.glob(f"{doc_id}/**/page_{number:04d}.json"))
            if len(candidates) > 1:
                raise ValueError(f"同一页有多个标注快照，需要明确选择标注员：{candidates}")
            patch = candidates[0] if candidates else None
            final = read_json(patch) if patch else chain
            if final.get("sample_id", doc_id) != doc_id or final.get("page", number) != number:
                raise ValueError(f"页面身份与路径不一致：{patch or path}")
            # Empty snapshots intentionally delete every block. Never fall back on truthiness.
            blocks = final["blocks"] if patch else final["revision"]["blocks"]
            if not isinstance(blocks, list):
                raise ValueError(f"blocks 必须是列表：{patch or path}")
            if patch:
                patches[patch] = True
            report["patch_pages" if patch else "chain_pages"] += 1
            report["pages"] += 1
            report["blocks"] += len(blocks)
            report["sources"].append(
                {
                    "path": str(path),
                    "sha256": sha256(path),
                    "patch": str(patch) if patch else None,
                    "patch_sha256": sha256(patch) if patch else None,
                }
            )
            normalized = []
            for block in sorted(blocks, key=lambda b: b["reading_order"]):
                kind = block["type"]
                normalized.append(
                    Block(
                        id=block["block_id"],
                        type=kind,
                        text=block.get("text") or "",
                        html=block.get("html") or "",
                        bbox=block.get("bbox_normalized"),
                        level=block.get("level"),
                        metadata=block,
                    )
                )
            if dimensions and number > len(dimensions):
                raise ValueError(f"{doc_id}: run 页码 {number} 超出 PDF 页数 {len(dimensions)}")
            width, height = dimensions[number - 1] if dimensions else (1000, 1000)
            pages.append(
                Page(number, normalized, width, height, {"source": "patch" if patch else "chain"})
            )
        if dimensions and len(dimensions) != len(pages):
            raise ValueError(f"{doc_id}: PDF {len(dimensions)} 页，runs 只有 {len(pages)} 页")
        if [p.number for p in pages] != list(range(1, len(pages) + 1)):
            raise ValueError(f"{doc_id}: runs 页码有缺口，不能假定缺页为空白页")
        metadata = {
            "origin": "annotations",
            "source_pdf": str(root / "sources" / f"{doc_id}.pdf"),
            "continuity": "unknown",
            **mapping.get(doc_id, {}),
        }
        original_pages = metadata.get("original_page_numbers")
        if original_pages is not None:
            if len(original_pages) != len(pages) or len(set(original_pages)) != len(pages):
                raise ValueError(f"{doc_id}: original_page_numbers 长度或唯一性无效")
            for page, original in zip(pages, original_pages):
                page.metadata["original_page"] = original
            metadata["continuity"] = (
                "continuous"
                if all(b == a + 1 for a, b in zip(original_pages, original_pages[1:]))
                else "sampled"
            )
        doc = Document(doc_id, pages, metadata=metadata)
        doc.relations, issues = annotation_relations(doc)
        report["issues"].extend(issues)
        doc.dump(output / "documents" / f"{doc_id}.json")
    orphaned = [str(path) for path, used in patches.items() if not used]
    if orphaned:
        raise ValueError(f"存在无对应 run 的 patch：{orphaned[:5]}")
    report["relations"] = sum(
        len(Document.load(p).relations) for p in (output / "documents").glob("*.json")
    )
    write_json(output / "audit.json", report)
    return report


def _pdf_dimensions(path: Path) -> list[tuple[float, float]]:
    if not path.exists():
        return []
    import pypdfium2 as pdfium

    with pdfium.PdfDocument(path) as pdf:
        return [pdf.get_page_size(i) for i in range(len(pdf))]


def annotation_relations(doc: Document) -> tuple[list[dict], list[dict]]:
    index = {block.id: (page.number, block) for page in doc.pages for block in page.blocks}
    edges = set()
    issues = []
    for block_id, (page, block) in index.items():
        for key, kind in (("cross_page_text", "text"), ("cross_page_table", "table")):
            info = block.metadata.get(key) or {}
            for field, reverse in (("continues_block_id", True), ("continued_by_block_id", False)):
                target = info.get(field)
                if not target:
                    continue
                text_types = {"text", "image_caption", "table_caption", "footnote", "title"}
                compatible = target in index and (
                    (kind == "table" and block.type == index[target][1].type == "table")
                    or (
                        kind == "text"
                        and block.type in text_types
                        and index[target][1].type in text_types
                    )
                )
                if not compatible:
                    issues.append(
                        {
                            "document": doc.id,
                            "block": block_id,
                            "target": target,
                            "issue": "unresolved_or_type_mismatch",
                        }
                    )
                    continue
                source, destination = (target, block_id) if reverse else (block_id, target)
                if index[source][0] >= index[destination][0]:
                    issues.append(
                        {
                            "document": doc.id,
                            "block": block_id,
                            "target": target,
                            "issue": "invalid_page_direction",
                        }
                    )
                    continue
                edges.add((source, destination))
    return ([{"type": "truncated", "source": a, "target": b} for a, b in sorted(edges)], issues)
