"""Build and score the four PDF2Text feature checks.

The legacy Markdown set and the 2026-11-18 annotation package describe
different layers of the task.  This module keeps those layers explicit:
the structured package supplies page/block evidence, while legacy Markdown
is retained as a visual-content candidate audit.  It must not silently turn
the latter into a fully reviewed chart-content GT.
"""

from __future__ import annotations

import difflib
import json
import re
import tarfile
import tempfile
import unicodedata
from collections import Counter
from contextlib import contextmanager
from pathlib import Path

from .annotations import import_annotations
from .io import fresh_directory, read_json, sha256, write_json
from .markdown import parse_markdown
from .schema import (
    MARGINAL_TYPES,
    SCHEMA_VERSION,
    VISUAL_TYPES,
    Block,
    Document,
    Page,
    load_documents,
)

FEATURE_GT_SCHEMA = "doc-parse-bench.feature-gt.v1"
FEATURE_EVAL_SCHEMA = "doc-parse-bench.feature-eval.v1"
DEFAULT_DATASET_VERSION = "legacy-features-20261118"
FEATURE_GT_VERSION = "legacy-129-feature-v3"
LEGACY_MARKDOWN_GT_VERSION = "legacy-129-markdown-v1"
ANNOTATED_GT_VERSION = "legacy-129-annotated-v2"
FEATURE_SUBSET_SCHEMA = "doc-parse-bench.feature-subset.v1"
FEATURES = ("appendix", "header_footer", "image_analysis", "chart_analysis")
# Keep the broad marker for the old Markdown audit, but use the exact
# PDF2Text filter vocabulary for the behavior denominator.  PDF2Text's
# _find_appendix_page only accepts titles beginning with 附录/Appendix and
# only after the document's 50% page threshold; it does not treat 附件 or
# Addendum as an appendix.
APPENDIX_RE = re.compile(r"(?:^|[\s#（(])(?:附录|附件|appendix|addendum)(?=$|[\s:#）)])", re.I)
APPENDIX_START_RE = re.compile(r"^\s*(?:附录|appendix)", re.I)
APPENDIX_TITLE_TYPES = {"title", "paragraph_title", "doc_title"}
FIGURE_CAPTION_RE = re.compile(r"^\s*(?:图|fig(?:ure)?\.?)[\sA-Za-z0-9.-]*", re.I)
IMAGE_RE = re.compile(r"!\[[^\]]*\]\(([^)]*)\)|<img\b", re.I)
MARGINAL = set(MARGINAL_TYPES)
VISUAL = set(VISUAL_TYPES)


def _natural_id(value: str) -> tuple[int, str]:
    match = re.search(r"(\d+)$", value)
    return (int(match.group(1)) if match else 10**9, value)


def _normalise_text(value: str) -> str:
    value = unicodedata.normalize("NFKC", value or "").lower()
    return "".join(
        char for char in value if not char.isspace() and unicodedata.category(char)[0] not in "P"
    )


def _similarity(left: str, right: str) -> float:
    left, right = _normalise_text(left), _normalise_text(right)
    if not left and not right:
        return 1.0
    if not left or not right:
        return 0.0
    return difflib.SequenceMatcher(a=left, b=right, autojunk=False).ratio()


def _block_payload(block: Block) -> str:
    """Return visual content that counts as analysis output, not a bare box."""
    metadata = block.metadata or {}
    candidates = [block.text, block.html]
    for key in ("content", "chart_content", "visual_details", "description", "ocr_text"):
        value = metadata.get(key)
        if isinstance(value, str):
            candidates.append(value)
        elif isinstance(value, (dict, list)):
            candidates.append(json.dumps(value, ensure_ascii=False, sort_keys=True))
    bench = metadata.get("bench_block")
    if isinstance(bench, dict):
        for key in ("text", "content", "html", "description"):
            value = bench.get(key)
            if isinstance(value, str):
                candidates.append(value)
    return "\n".join(value for value in candidates if value).strip()


def _is_chart(block: Block) -> bool:
    if block.type == "chart":
        return True
    metadata = block.metadata or {}
    for key in ("source_type", "raw_type", "label", "type"):
        if str(metadata.get(key, "")).lower() == "chart":
            return True
    bench = metadata.get("bench_block")
    return isinstance(bench, dict) and str(bench.get("type", "")).lower() == "chart"


def _has_output(block: Block) -> bool:
    if _block_payload(block):
        return True
    return block.type in VISUAL and block.bbox is not None


def _service_appendix_start(document: Document) -> int | None:
    """Return the page selected by PDF2Text's ``keep_appendix`` filter."""
    total_pages = len(document.pages)
    if not total_pages:
        return None
    # MinerU's middle_json page_idx is zero based.  PDF2Text computes
    # int(total_pages * .5) against that value; this IR stores one-based pages.
    minimum_page_index = max(0, int(total_pages * 0.5))
    for page in document.pages:
        if page.number - 1 < minimum_page_index:
            continue
        for block in page.blocks:
            if block.type in APPENDIX_TITLE_TYPES and APPENDIX_START_RE.match(
                (block.text or "").strip()
            ):
                return page.number
    return None


def _old_markdown_stats(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    headings = []
    for line in lines:
        match = re.match(r"^\s*(#{1,6})\s+(.+?)\s*$", line)
        if match:
            headings.append({"level": len(match.group(1)), "text": match.group(2).strip()})
    image_matches = list(IMAGE_RE.finditer(text))
    appendix_markers = [line.strip() for line in lines if APPENDIX_RE.search(line) and line.strip()]
    appendix_headings = [item["text"] for item in headings if APPENDIX_START_RE.match(item["text"])]
    html_tables = len(re.findall(r"<table\b", text, re.I))
    markdown_tables = sum(
        1
        for index, line in enumerate(lines[:-1])
        if "|" in line and re.search(r"\|\s*:?-{1,}\s*", lines[index + 1])
    )
    figure_captions = [line.strip() for line in lines if FIGURE_CAPTION_RE.match(line)]
    return {
        "sha256": sha256(path),
        "characters": len(text),
        "headings": headings,
        "heading_count": len(headings),
        "image_references": len(image_matches),
        "image_placeholder_count": sum(
            "this is a image" in match.group(0).lower() for match in image_matches
        ),
        "html_table_count": html_tables,
        "markdown_table_count": markdown_tables,
        "table_count": html_tables + markdown_tables,
        "details_count": len(re.findall(r"<details\b", text, re.I)),
        "appendix_marker_count": len(appendix_markers),
        "appendix_heading_count": len(appendix_headings),
        "appendix_markers": appendix_markers[:30],
        "figure_caption_count": len(figure_captions),
        "figure_captions": figure_captions[:50],
        "chart_content_candidate": bool(figure_captions and (html_tables or markdown_tables)),
    }


def _new_document_features(document: Document) -> dict:
    type_counts = Counter(block.type for page in document.pages for block in page.blocks)
    title_blocks = [
        {
            "page": page.number,
            "id": block.id,
            "text": block.text,
            "level": block.level,
        }
        for page in document.pages
        for block in page.blocks
        if block.type == "title"
    ]
    appendix_titles = [item for item in title_blocks if APPENDIX_START_RE.match(item["text"] or "")]
    appendix_markers = [
        {
            "page": page.number,
            "id": block.id,
            "type": block.type,
            "text": block.text,
        }
        for page in document.pages
        for block in page.blocks
        if APPENDIX_RE.search(block.text or "")
    ]
    appendix_start = _service_appendix_start(document)
    appendix_pages = (
        [page.number for page in document.pages if page.number >= appendix_start]
        if appendix_start is not None
        else []
    )
    marginal_blocks = [
        {
            "page": page.number,
            "id": block.id,
            "type": block.type,
            "text": block.text,
            "bbox": block.bbox,
        }
        for page in document.pages
        for block in page.blocks
        if block.type in MARGINAL
    ]
    header_footer_blocks = [
        item for item in marginal_blocks if item["type"] in {"header", "footer"}
    ]
    page_number_blocks = [item for item in marginal_blocks if item["type"] == "page_number"]
    visual_blocks = [
        {
            "page": page.number,
            "id": block.id,
            "type": block.type,
            "text": block.text,
            "bbox": block.bbox,
            "has_content": bool(_block_payload(block)),
        }
        for page in document.pages
        for block in page.blocks
        if block.type in VISUAL
    ]
    chart_blocks = [item for item in visual_blocks if item["type"] == "chart"]
    image_blocks = [item for item in visual_blocks if item["type"] in {"image", "seal"}]
    image_only_blocks = [item for item in visual_blocks if item["type"] == "image"]
    seal_blocks = [item for item in visual_blocks if item["type"] == "seal"]
    captions = [
        {
            "page": page.number,
            "id": block.id,
            "type": block.type,
            "text": block.text,
        }
        for page in document.pages
        for block in page.blocks
        if block.type in {"image_caption", "image_footnote"}
    ]
    return {
        "pages": len(document.pages),
        "type_counts": dict(sorted(type_counts.items())),
        "title_blocks": title_blocks,
        "title_count": len(title_blocks),
        "appendix": {
            "has_appendix": bool(appendix_start is not None),
            "start_page": appendix_start,
            "pages": appendix_pages,
            "marker_count": len(appendix_markers),
            "title_count": len(appendix_titles),
            "markers": appendix_markers[:50],
            "service_min_page_index": max(0, int(len(document.pages) * 0.5)),
        },
        "marginal_blocks": marginal_blocks,
        "marginal_count": len(marginal_blocks),
        "header_footer_blocks": header_footer_blocks,
        "header_footer_count": len(header_footer_blocks),
        "page_number_blocks": page_number_blocks,
        "page_number_count": len(page_number_blocks),
        "image_blocks": image_blocks,
        "image_count": len(image_blocks),
        "image_only_blocks": image_only_blocks,
        "image_only_count": len(image_only_blocks),
        "seal_blocks": seal_blocks,
        "seal_count": len(seal_blocks),
        "chart_blocks": chart_blocks,
        "chart_count": len(chart_blocks),
        "visual_blocks": visual_blocks,
        "visual_count": len(visual_blocks),
        "captions": captions,
    }


def _safe_extract(archive: Path, destination: Path) -> None:
    with tarfile.open(archive, "r:*") as stream:
        root = destination.resolve()
        for member in stream.getmembers():
            target = (destination / member.name).resolve()
            if target != root and root not in target.parents:
                raise ValueError(f"归档包含越界路径：{member.name}")
        stream.extractall(destination)


@contextmanager
def _annotation_root(source: Path):
    if source.is_dir():
        yield source
        return
    if not source.is_file() or not tarfile.is_tarfile(source):
        raise ValueError(f"新 GT 必须是目录或 tar 包：{source}")
    with tempfile.TemporaryDirectory(prefix="docbench-feature-gt-") as directory:
        root = Path(directory)
        _safe_extract(source, root)
        yield root


def _old_names(old_groundtruth: Path) -> list[Path]:
    paths = sorted(old_groundtruth.glob("*.md"))
    if len(paths) == 130 and any(path.name == "Handwriting document.md" for path in paths):
        paths = [path for path in paths if path.name != "Handwriting document.md"]
    if len(paths) != 129:
        raise ValueError(f"旧 GT 应有 129 个 Markdown，实际为 {len(paths)}：{old_groundtruth}")
    return paths


def build_feature_ground_truth(
    new_source: Path,
    old_groundtruth: Path,
    output: Path,
    old_pdf_dir: Path | None = None,
    dataset_version: str = DEFAULT_DATASET_VERSION,
    include_structured: bool = False,
) -> dict:
    """Materialize the compact v3 GT and an old/new comparison report.

    The v2 structured source is already retained in its original tar archive.
    v3 therefore keeps only the feature records by default; ``include_structured``
    is a debugging option for a local expanded copy.
    """
    old_paths = _old_names(old_groundtruth)
    output = fresh_directory(output)
    old_pdf_dir = old_pdf_dir or old_groundtruth.parent / "dataset" / "pdf" / "source"
    with _annotation_root(new_source) as root:
        if include_structured:
            ir = output / "structured"
            import_report = import_annotations(root, ir, dataset_version=dataset_version)
            documents = load_documents(ir / "documents")
        else:
            with tempfile.TemporaryDirectory(prefix="docbench-feature-ir-") as directory:
                ir = Path(directory) / "structured"
                import_report = import_annotations(root, ir, dataset_version=dataset_version)
                documents = load_documents(ir / "documents")
    documents.sort(key=lambda doc: _natural_id(doc.id))
    if len(documents) != len(old_paths):
        raise ValueError(f"新旧 GT 文档数不一致：new={len(documents)}, old={len(old_paths)}")
    if old_pdf_dir.exists():
        import pypdfium2 as pdfium

        for document, old_path in zip(documents, old_paths):
            pdf = old_pdf_dir / f"{old_path.stem}.pdf"
            if not pdf.exists():
                raise ValueError(f"缺少旧 GT 对应 PDF：{pdf}")
            with pdfium.PdfDocument(pdf) as source_pdf:
                pages = len(source_pdf)
            if pages != len(document.pages):
                raise ValueError(
                    f"页数无法对齐：{document.id}/{old_path.name}: new={len(document.pages)}, old={pages}"
                )

    records = []
    old_summary = Counter()
    new_summary = Counter()
    for document, old_path in zip(documents, old_paths):
        old = _old_markdown_stats(old_path)
        new = _new_document_features(document)
        old_summary.update(
            {
                "documents": 1,
                "heading_count": old["heading_count"],
                "image_references": old["image_references"],
                "image_reference_documents": bool(old["image_references"]),
                "image_placeholder_count": old["image_placeholder_count"],
                "table_count": old["table_count"],
                "appendix_documents": bool(old["appendix_heading_count"]),
                "chart_candidate_documents": old["chart_content_candidate"],
            }
        )
        new_summary.update(
            {
                "documents": 1,
                "pages": new["pages"],
                "titles": new["title_count"],
                "marginal_blocks": new["marginal_count"],
                "header_footer_blocks": new["header_footer_count"],
                "page_number_blocks": new["page_number_count"],
                "image_blocks": new["image_count"],
                "seal_blocks": new["seal_count"],
                "chart_blocks": new["chart_count"],
                "visual_blocks": new["visual_count"],
                "appendix_documents": new["appendix"]["has_appendix"],
            }
        )
        records.append(
            {
                "document_id": document.id,
                "source_name": old_path.stem,
                "old_gt": old,
                "new_gt": new,
                "feature_sources": {
                    "appendix": "new_structured_annotation; old_markdown_cross_check",
                    "header_footer": "new_marginal_blocks; old_markdown_cross_check",
                    "image_analysis": "new_image_and_seal_blocks; old_placeholder_cross_check",
                    "chart_analysis": "new_chart_locations + old_markdown_content_candidate",
                },
            }
        )

    summary = {
        "old": {
            "documents": int(old_summary["documents"]),
            "heading_count": int(old_summary["heading_count"]),
            "image_references": int(old_summary["image_references"]),
            "image_reference_documents": int(old_summary["image_reference_documents"]),
            "image_placeholder_count": int(old_summary["image_placeholder_count"]),
            "table_count": int(old_summary["table_count"]),
            "appendix_documents": int(old_summary["appendix_documents"]),
            "chart_candidate_documents": int(old_summary["chart_candidate_documents"]),
        },
        "new": {
            "documents": int(new_summary["documents"]),
            "pages": int(new_summary["pages"]),
            "titles": int(new_summary["titles"]),
            "marginal_blocks": int(new_summary["marginal_blocks"]),
            "header_footer_blocks": int(new_summary["header_footer_blocks"]),
            "page_number_blocks": int(new_summary["page_number_blocks"]),
            "image_blocks": int(new_summary["image_blocks"]),
            "seal_blocks": int(new_summary["seal_blocks"]),
            "chart_blocks": int(new_summary["chart_blocks"]),
            "visual_blocks": int(new_summary["visual_blocks"]),
            "appendix_documents": int(new_summary["appendix_documents"]),
            "patch_pages": import_report["patch_pages"],
            "chain_pages": import_report["chain_pages"],
        },
        "comparison": {
            "title": {
                "preferred": "new",
                "reason": "new GT has block-level types, levels, bboxes, and title-sync edits; old Markdown only has headings",
            },
            "appendix": {
                "preferred": "new",
                "reason": "new GT gives page/block boundaries; old Markdown is a useful text cross-check",
            },
            "header_footer": {
                "preferred": "new",
                "reason": "old Markdown does not retain reliable header/footer/page-number types",
            },
            "image_analysis": {
                "preferred": "hybrid",
                "reason": "new GT supplies visual block locations; old Markdown only supplies image placeholders and no image-content transcription",
            },
            "chart_analysis": {
                "preferred": "hybrid_candidate",
                "reason": "new GT supplies chart locations but chart text/html is empty; old Markdown contains mixed chart/table conversions that still require manual chart-level review",
                "review_required": True,
            },
        },
    }
    summary["coverage"] = {
        "appendix": {
            "status": "supported_boundary_proxy",
            "documents": int(new_summary["appendix_documents"]),
            "pages": sum(
                len(record["new_gt"]["appendix"]["pages"])
                for record in records
                if record["new_gt"]["appendix"]["has_appendix"]
            ),
            "old_markdown_cross_check_documents": int(old_summary["appendix_documents"]),
        },
        "header_footer": {
            "status": "structured_retention_proxy",
            "new_header_footer_blocks": int(new_summary["header_footer_blocks"]),
            "new_page_number_blocks": int(new_summary["page_number_blocks"]),
            "old_markdown_typed_blocks": 0,
        },
        "image_analysis": {
            "status": "visual_block_retention_proxy",
            "new_image_and_seal_blocks": int(new_summary["image_blocks"]),
            "new_image_blocks": int(new_summary["image_blocks"] - new_summary["seal_blocks"]),
            "new_seal_blocks": int(new_summary["seal_blocks"]),
            "old_markdown_reference_documents": int(old_summary["image_reference_documents"]),
            "strict_content_accuracy": False,
        },
        "chart_analysis": {
            "location_status": "structured_location_proxy",
            "content_status": "legacy_markdown_candidate_only",
            "new_chart_blocks": int(new_summary["chart_blocks"]),
            "old_candidate_documents": int(old_summary["chart_candidate_documents"]),
            "strict_content_accuracy": False,
        },
    }
    manifest = {
        "schema_version": FEATURE_GT_SCHEMA,
        "kind": "feature_ground_truth",
        "gt_version": FEATURE_GT_VERSION,
        "gt_lineage": {
            "legacy_markdown": {
                "version": LEGACY_MARKDOWN_GT_VERSION,
                "path": str(old_groundtruth.resolve()),
                "role": "historical_content_and_chart_candidate_source",
            },
            "annotated_structured": {
                "version": ANNOTATED_GT_VERSION,
                "path": str(new_source.resolve()),
                "role": "title_and_structure_primary_ground_truth",
            },
            "feature_derived": {
                "version": FEATURE_GT_VERSION,
                "role": "four_pdf2text_feature_evaluation_only",
            },
        },
        "dataset_version": dataset_version,
        "documents": len(records),
        "source": {
            "new_source": str(new_source.resolve()),
            "new_source_sha256": sha256(new_source) if new_source.is_file() else None,
            "old_groundtruth": str(old_groundtruth.resolve()),
            "old_pdf_dir": str(old_pdf_dir.resolve()) if old_pdf_dir.exists() else None,
            "document_mapping": "natural bc_001..bc_129 order to sorted old Markdown stems; PDF page counts verified",
        },
        "features": FEATURES,
        "materialization": {
            "structured_documents_included": include_structured,
            "structured_source_retained_in": str(new_source.resolve()),
        },
        "summary": summary,
        "import_audit": {
            "documents": import_report["documents"],
            "pages": import_report["pages"],
            "patch_pages": import_report["patch_pages"],
            "chain_pages": import_report["chain_pages"],
            "issues": import_report["issues"],
        },
    }
    write_json(output / "manifest.json", manifest)
    write_json(output / "records.json", {"schema_version": FEATURE_GT_SCHEMA, "records": records})
    (output / "comparison.md").write_text(_comparison_markdown(manifest), encoding="utf-8")
    return {
        "output": str(output),
        "documents": len(records),
        "pages": summary["new"]["pages"],
        "features": list(FEATURES),
        "comparison": str(output / "comparison.md"),
    }


def _comparison_markdown(manifest: dict) -> str:
    summary = manifest["summary"]
    old, new = summary["old"], summary["new"]
    lines = [
        "# legacy 129 四项能力 GT 对账",
        "",
        f"版本：`{manifest.get('gt_version', FEATURE_GT_VERSION)}`；数据集：`{manifest['dataset_version']}`；文档：{new['documents']}；页：{new['pages']}。",
        "",
        "## 结论",
        "",
        "新结构化 GT 作为标题、附录、页眉页脚和视觉块位置的主 GT。它有人工整页快照和标题同步修订，能保留页码、块类型、层级、顺序和坐标。附录边界严格按 PDF2Text 的标题开头及后半段规则计算。",
        "",
        "旧 Markdown 作为视觉内容的来源审计：它有图片占位符和混合的表格转录，但没有可靠的页眉/页脚类型；其中表格未逐项标注为 chart，不能直接当作精确 chart-content GT。",
        "",
        "因此四项模式采用：附录／页眉页脚使用新 GT；image analysis 将 image 与 seal 一起作为主分母并拆分诊断；chart analysis 使用新 chart 位置加旧 Markdown 候选内容，图表内容正式计分前仍需人工复核。",
        "",
        "## 对账统计",
        "",
        "| 项目 | 旧 Markdown | 新结构化 GT |",
        "| --- | ---: | ---: |",
        f"| 文档 | {old['documents']} | {new['documents']} |",
        f"| 页 | 未可靠保存 | {new['pages']} |",
        f"| 标题 | {old['heading_count']} 个 Markdown heading | {new['titles']} 个 title 块 |",
        f"| 页眉/页脚块 | 无可靠类型 | {new['header_footer_blocks']}（页码 {new['page_number_blocks']}；边缘块合计 {new['marginal_blocks']}） |",
        f"| 图片引用/占位符 | {old['image_references']} / {old['image_placeholder_count']} | image/seal {new['image_blocks']}（其中 seal {new['seal_blocks']}） |",
        f"| chart 块 | 无独立类型 | {new['chart_blocks']} |",
        f"| 混合表格 | {old['table_count']} | table 块见新 GT |",
        f"| 附录候选文档 | {old['appendix_documents']} | {new['appendix_documents']} |",
        "",
        "## 计分边界",
        "",
        "- `appendix`：复现 PDF2Text 的 `附录`/`Appendix` 标题开头且位于文档后半段的边界；`附件` 不进入此分母。",
        "- `header_footer`：按新 GT 的 header/footer 和 page_number 边缘块做匹配，并分别报告页码；旧 Markdown 只作文本交叉核对。",
        "- `image_analysis`：主分母统计 image＋seal，并分别报告两类；seal 是 image 的视觉子类型，不是独立开关。图片占位符本身不代表图内文字已识别。",
        "- `chart_analysis`：同时报告 chart 定位和有实际文本/表格内容的 chart；当前旧内容是候选 GT，未审核前不宣称精确内容分。",
        "",
        "详细 per-document 记录见 `records.json`。运行方式见项目中的 `docs/feature-evaluation.md`。",
        "",
    ]
    return "\n".join(lines)


def _records_from_gt(gt: Path) -> tuple[dict, list[dict]]:
    manifest = read_json(gt / "manifest.json")
    if manifest.get("schema_version") != FEATURE_GT_SCHEMA:
        raise ValueError(f"不是四项能力 GT：{gt}")
    payload = read_json(gt / "records.json")
    if payload.get("schema_version") != FEATURE_GT_SCHEMA:
        raise ValueError(f"GT records 版本不一致：{gt}")
    return manifest, payload["records"]


def _select_feature_records(
    manifest: dict,
    records: list[dict],
    subset_manifest: Path | None,
    subset_name: str | None,
) -> tuple[list[dict], dict]:
    """Select a fixed document subset without treating omitted docs as zeros."""
    if subset_manifest is None:
        if subset_name:
            raise ValueError("指定 --subset-name 时必须同时指定 --subset-manifest")
        return records, {"name": None, "manifest": None, "documents": len(records)}

    subset = read_json(subset_manifest)
    if subset.get("schema_version") != FEATURE_SUBSET_SCHEMA:
        raise ValueError(f"不是四项能力子集清单：{subset_manifest}")
    name = subset_name or "union"
    document_ids = subset.get("subsets", {}).get(name)
    if not isinstance(document_ids, list) or not document_ids:
        raise ValueError(f"子集不存在或为空：{name}（{subset_manifest}）")
    if len(document_ids) != len(set(document_ids)):
        raise ValueError(f"子集包含重复文档：{name}")
    if subset.get("gt_version") and subset["gt_version"] != manifest.get("gt_version"):
        raise ValueError(
            f"子集 GT 版本不一致：subset={subset.get('gt_version')}, "
            f"ground_truth={manifest.get('gt_version')}"
        )
    by_id = {record["document_id"]: record for record in records}
    selected = []
    missing = []
    for document_id in document_ids:
        record = by_id.get(document_id)
        if record is None:
            missing.append(document_id)
        else:
            selected.append(record)
    if missing:
        raise ValueError(f"子集包含 GT 中不存在的文档：{missing[:5]}")
    return selected, {
        "name": name,
        "manifest": str(subset_manifest.resolve()),
        "manifest_sha256": sha256(subset_manifest),
        "documents": len(selected),
    }


def _prediction_document_id(path: Path, payload: dict) -> str:
    value = payload.get("document_id") or payload.get("filename") or path.stem
    value = Path(str(value)).name
    return value.removesuffix(".pdf").removesuffix(".md")


def _markdown_prediction(
    document_id: str,
    page_markdowns: list[str],
    *,
    source: Path,
    reported_pages: int | None = None,
    page_boundaries: str = "explicit",
    error: str | None = None,
) -> Document:
    return Document(
        document_id,
        [
            Page(number, parse_markdown(markdown, number))
            for number, markdown in enumerate(page_markdowns, 1)
        ],
        metadata={
            "origin": "pdf2text_response",
            "source": str(source),
            "reported_pages": reported_pages,
            "page_boundaries": page_boundaries,
            "error": error,
        },
    )


def _load_pdf2text_response(path: Path, payload: dict) -> Document:
    """Read one JSON response returned by PDF2Text ``/v1/pdfparse``."""
    document_id = _prediction_document_id(path, payload)
    reported_pages = payload.get("pages")
    if isinstance(reported_pages, bool) or not isinstance(reported_pages, int):
        reported_pages = None
    page_markdowns = payload.get("page_markdowns")
    if isinstance(page_markdowns, dict) and page_markdowns:
        keyed = []
        for key, value in page_markdowns.items():
            try:
                page = int(key)
            except (TypeError, ValueError):
                continue
            keyed.append((page, str(value or "")))
        keyed.sort()
        if keyed and [page for page, _ in keyed] == list(range(1, len(keyed) + 1)):
            return _markdown_prediction(
                document_id,
                [value for _, value in keyed],
                source=path,
                reported_pages=reported_pages or len(keyed),
                page_boundaries="explicit",
                error=payload.get("error"),
            )

    markdown = str(payload.get("markdown") or "")
    pages = re.split(r"<PAGE>|\f", markdown)
    explicit = len(pages) > 1
    if explicit and pages and not pages[0].strip() and "<PAGE>" in markdown:
        pages = pages[1:]
    if not pages:
        pages = [""]
    return _markdown_prediction(
        document_id,
        pages,
        source=path,
        reported_pages=reported_pages or len(pages),
        page_boundaries="explicit" if explicit else "unknown",
        error=payload.get("error"),
    )


def _load_prediction_documents(source: Path) -> list[Document]:
    documents_path = source / "documents" if (source / "documents").is_dir() else source
    if not documents_path.exists():
        raise ValueError(f"预测目录不存在：{source}")
    json_paths = sorted(documents_path.glob("*.json")) if documents_path.is_dir() else []
    if json_paths:
        payloads = [(path, read_json(path)) for path in json_paths]
        if all(
            isinstance(payload, dict) and payload.get("schema_version") == SCHEMA_VERSION
            for _, payload in payloads
        ):
            return load_documents(documents_path)
        if all(
            isinstance(payload, dict) and "markdown" in payload and "pages" in payload
            for _, payload in payloads
        ):
            return [_load_pdf2text_response(path, payload) for path, payload in payloads]
        raise ValueError(
            f"预测 JSON 必须全部是统一 IR（schema_version={SCHEMA_VERSION}）或 PDF2Text 响应：{documents_path}"
        )
    if not documents_path.is_dir():
        raise ValueError(f"预测目录没有可读文件：{source}")
    paths = sorted(documents_path.glob("*.md")) or sorted(documents_path.glob("*.txt"))
    if not paths:
        raise ValueError(f"预测目录没有 documents/*.json 或 Markdown：{source}")
    documents = []
    for path in paths:
        text = path.read_text(encoding="utf-8")
        pages = re.split(r"<PAGE>|\f", text)
        if pages and not pages[0].strip() and "<PAGE>" in text:
            pages = pages[1:]
        documents.append(
            Document(
                path.stem,
                [
                    Page(number, parse_markdown(page, number))
                    for number, page in enumerate(pages, 1)
                ],
                metadata={
                    "origin": "prediction",
                    "source": str(path),
                    "page_boundaries": "explicit" if len(pages) > 1 else "unknown",
                },
            )
        )
    return documents


def _match_blocks(
    expected: list[dict],
    predicted: list[tuple[int, Block]],
    threshold: float = 0.85,
    *,
    require_type: bool = True,
    page_aware: bool = True,
) -> tuple[int, int]:
    used: set[int] = set()
    matched = 0
    for item in expected:
        candidates = [
            (index, (page, block))
            for index, (page, block) in enumerate(predicted)
            if index not in used
            and (not require_type or block.type == item["type"])
            and (not page_aware or page == item["page"])
        ]
        if not candidates:
            continue
        scored = sorted(
            (
                (_similarity(item.get("text", ""), candidate[1].text), index)
                for index, candidate in candidates
            ),
            reverse=True,
        )
        score, index = scored[0]
        if score >= threshold or (not item.get("text") and not predicted[index][1].text):
            used.add(index)
            matched += 1
    return matched, len(expected)


def _predicted_page_blocks(document: Document, page_number: int) -> list[Block]:
    return next((page.blocks for page in document.pages if page.number == page_number), [])


def _count_visual_matches(
    expected: list[dict], predicted: list[tuple[int, Block]], *, page_aware: bool
) -> int:
    if not page_aware:
        return min(len(expected), len(predicted))
    matched = 0
    pages = {item["page"] for item in expected}
    for page in pages:
        matched += min(
            sum(1 for item in expected if item["page"] == page),
            sum(1 for number, _ in predicted if number == page),
        )
    return matched


def _feature_scores(record: dict, document: Document | None) -> dict:
    new = record["new_gt"]
    expected_marginal = new.get("marginal_blocks", [])
    expected_header_footer = new.get("header_footer_blocks", [])
    expected_page_numbers = new.get("page_number_blocks", [])
    if document is None:
        return {
            "appendix": {"expected_pages": len(new["appendix"]["pages"]), "observed_pages": 0},
            "header_footer": {
                "expected": len(expected_marginal),
                "predicted": 0,
                "matched": 0,
                "header_footer_expected": len(expected_header_footer),
                "header_footer_matched": 0,
                "page_number_expected": len(expected_page_numbers),
                "page_number_matched": 0,
            },
            "image_analysis": {
                "expected": len(new["image_blocks"]),
                "predicted": 0,
                "matched": 0,
                "image_expected": len(new.get("image_only_blocks", [])),
                "image_matched": 0,
                "seal_expected": len(new.get("seal_blocks", [])),
                "seal_predicted": 0,
                "seal_matched": 0,
            },
            "chart_analysis": {
                "expected": len(new["chart_blocks"]),
                "located": 0,
                "contentful": 0,
                "content_expected": (
                    len(new["chart_blocks"]) if record["old_gt"]["chart_content_candidate"] else 0
                ),
                "table_page_proxy": 0,
                "expected_chart_pages": len({item["page"] for item in new["chart_blocks"]}),
                "page_proxy_available": False,
            },
        }
    appendix_pages = new["appendix"]["pages"]
    page_aware = document.metadata.get("page_boundaries") == "explicit"
    response_pages = document.metadata.get("reported_pages")
    if response_pages is not None and appendix_pages:
        # keep_appendix removes a suffix, so the reported retained-page count
        # directly determines how much of the appendix suffix survived.
        retained_end = min(int(response_pages), max(appendix_pages))
        observed_pages = max(0, retained_end - min(appendix_pages) + 1)
    else:
        observed_pages = sum(
            any(
                block.type not in MARGINAL and _has_output(block)
                for block in _predicted_page_blocks(document, page)
            )
            for page in appendix_pages
        )
    markdown_only = document.metadata.get("origin") == "pdf2text_response"
    predicted_marginal = [
        (page.number, block)
        for page in document.pages
        for block in page.blocks
        if (block.text.strip() if markdown_only else block.type in MARGINAL)
    ]
    marginal_matched, marginal_expected = _match_blocks(
        expected_marginal,
        predicted_marginal,
        require_type=not markdown_only,
        page_aware=page_aware,
    )
    header_footer_matched, _ = _match_blocks(
        expected_header_footer,
        predicted_marginal,
        require_type=not markdown_only,
        page_aware=page_aware,
    )
    page_number_matched, _ = _match_blocks(
        expected_page_numbers,
        predicted_marginal,
        require_type=not markdown_only,
        page_aware=page_aware,
    )
    expected_images = new["image_blocks"]
    predicted_images = [
        (page.number, block)
        for page in document.pages
        for block in page.blocks
        if block.type in {"image", "seal"}
    ]
    image_matched = _count_visual_matches(expected_images, predicted_images, page_aware=page_aware)
    expected_image_only = new.get("image_only_blocks", [])
    predicted_image_only = [
        (page, block) for page, block in predicted_images if block.type == "image"
    ]
    image_only_matched = _count_visual_matches(
        expected_image_only, predicted_image_only, page_aware=page_aware
    )
    expected_seals = new.get("seal_blocks", [])
    predicted_seals = [(page, block) for page, block in predicted_images if block.type == "seal"]
    seal_matched = _count_visual_matches(expected_seals, predicted_seals, page_aware=page_aware)
    expected_charts = new["chart_blocks"]
    predicted_charts_by_page = {
        page.number: [block for block in page.blocks if _is_chart(block)] for page in document.pages
    }
    predicted_charts = [block for blocks in predicted_charts_by_page.values() for block in blocks]
    located = sum(
        min(
            sum(1 for item in expected_charts if item["page"] == page),
            len(predicted_charts_by_page.get(page, [])),
        )
        for page in {item["page"] for item in expected_charts}
    )
    contentful = sum(bool(_block_payload(block)) for block in predicted_charts)
    chart_content_candidate = bool(record["old_gt"]["chart_content_candidate"])
    content_expected = len(expected_charts) if chart_content_candidate else 0
    contentful_candidate = contentful if chart_content_candidate else 0
    predicted_content_candidate = len(predicted_charts) if chart_content_candidate else 0
    table_page_proxy = 0
    if markdown_only and page_aware:
        chart_pages = {item["page"] for item in expected_charts}
        table_page_proxy = sum(
            any(block.type == "table" for block in _predicted_page_blocks(document, page))
            for page in chart_pages
        )
    return {
        "appendix": {"expected_pages": len(appendix_pages), "observed_pages": observed_pages},
        "header_footer": {
            "expected": marginal_expected,
            "predicted": len(predicted_marginal),
            "matched": marginal_matched,
            "header_footer_expected": len(expected_header_footer),
            "header_footer_matched": header_footer_matched,
            "page_number_expected": len(expected_page_numbers),
            "page_number_matched": page_number_matched,
            "page_aware": page_aware,
            "markdown_only": markdown_only,
        },
        "image_analysis": {
            "expected": len(expected_images),
            "predicted": len(predicted_images),
            "matched": image_matched,
            "image_expected": len(expected_image_only),
            "image_matched": image_only_matched,
            "seal_expected": len(expected_seals),
            "seal_predicted": len(predicted_seals),
            "seal_matched": seal_matched,
            "page_aware": page_aware,
            "markdown_only": markdown_only,
        },
        "chart_analysis": {
            "expected": len(expected_charts),
            "located": located,
            "predicted": predicted_content_candidate,
            "contentful": contentful_candidate,
            "content_expected": content_expected,
            "table_page_proxy": table_page_proxy,
            "expected_chart_pages": len({item["page"] for item in expected_charts}),
            "page_proxy_available": markdown_only and page_aware,
            "old_content_candidate": record["old_gt"]["chart_content_candidate"],
        },
    }


def _rate(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator, 4) if denominator else None


def evaluate_features(
    ground_truth: Path,
    predictions: Path,
    output: Path,
    allow_missing: bool = False,
    subset_manifest: Path | None = None,
    subset_name: str | None = None,
) -> dict:
    """Evaluate capability presence/retention, keeping feature denominators visible."""
    manifest, all_records = _records_from_gt(ground_truth)
    records, subset_info = _select_feature_records(
        manifest, all_records, subset_manifest, subset_name
    )
    prediction_list = _load_prediction_documents(predictions)
    by_id = {document.id: document for document in prediction_list}
    by_name = {document.id.removesuffix(".md"): document for document in prediction_list}
    missing = []
    per_document = []
    totals = {
        "appendix": Counter(),
        "header_footer": Counter(),
        "image_analysis": Counter(),
        "chart_analysis": Counter(),
    }
    for record in records:
        document = by_id.get(record["document_id"]) or by_name.get(record["source_name"])
        if document is None:
            missing.append(record["document_id"])
        scores = _feature_scores(record, document)
        per_document.append(
            {
                "document_id": record["document_id"],
                "source_name": record["source_name"],
                "missing": document is None,
                **scores,
            }
        )
        for feature, values in scores.items():
            totals[feature].update(values)
    if missing and not allow_missing:
        raise ValueError(
            f"缺少 {len(missing)}/{len(records)} 份四项能力预测，例如 {missing[:3]}；"
            "补齐 documents 或使用 --allow-missing"
        )
    appendix = totals["appendix"]
    marginal = totals["header_footer"]
    images = totals["image_analysis"]
    charts = totals["chart_analysis"]
    metrics = {
        "appendix_page_recall": _rate(appendix["observed_pages"], appendix["expected_pages"]),
        "header_footer_recall": _rate(marginal["matched"], marginal["expected"]),
        "header_footer_precision": _rate(marginal["matched"], marginal["predicted"]),
        "header_footer_text_recall": _rate(
            marginal["header_footer_matched"], marginal["header_footer_expected"]
        ),
        "page_number_recall": _rate(
            marginal["page_number_matched"], marginal["page_number_expected"]
        ),
        "image_analysis_recall": _rate(images["matched"], images["expected"]),
        "image_analysis_precision": _rate(images["matched"], images["predicted"]),
        "image_only_recall": _rate(images["image_matched"], images["image_expected"]),
        "seal_recall": _rate(images["seal_matched"], images["seal_expected"]),
        "chart_location_recall": _rate(charts["located"], charts["expected"]),
        "chart_content_recall": _rate(charts["contentful"], charts["content_expected"]),
        "chart_content_precision": _rate(charts["contentful"], charts["predicted"]),
        "chart_table_page_proxy_recall": _rate(
            charts["table_page_proxy"], charts["expected_chart_pages"]
        ),
        "chart_table_page_proxy_available": bool(charts["page_proxy_available"]),
        "missing_documents": len(missing),
        "expected_documents": len(records),
        "provided_documents": len(records) - len(missing),
        "subset": subset_info["name"],
        "chart_gt_content_status": manifest.get("summary", {})
        .get("coverage", {})
        .get("chart_analysis", {})
        .get("content_status", "legacy_markdown_candidate_only"),
    }
    for key in ("header_footer", "image_analysis"):
        recall = metrics[f"{key}_recall"]
        precision = metrics[f"{key}_precision"]
        metrics[f"{key}_f1"] = (
            round(2 * recall * precision / (recall + precision), 4)
            if recall is not None and precision is not None and recall + precision
            else None
        )
    output = fresh_directory(output)
    provenance = {
        "schema_version": FEATURE_EVAL_SCHEMA,
        "gt_version": manifest.get("gt_version", FEATURE_GT_VERSION),
        "gt_lineage": manifest.get("gt_lineage", {}),
        "ground_truth": str(ground_truth.resolve()),
        "ground_truth_manifest_sha256": sha256(ground_truth / "manifest.json"),
        "prediction_source": str(predictions.resolve()),
        "dataset_version": manifest.get("dataset_version"),
        "subset": subset_info,
        "missing_documents": missing,
        "allow_missing": allow_missing,
        "feature_denominators": {
            "appendix_pages": appendix["expected_pages"],
            "header_footer_blocks": marginal["expected"],
            "image_blocks": images["expected"],
            "chart_blocks": charts["expected"],
            "chart_content_candidate_blocks": charts["content_expected"],
        },
        "feature_coverage": manifest.get("summary", {}).get("coverage", {}),
    }
    write_json(output / "metrics.json", metrics)
    write_json(output / "per_document.json", {"documents": per_document})
    write_json(output / "provenance.json", provenance)
    (output / "report.md").write_text(_evaluation_markdown(metrics, provenance), encoding="utf-8")
    return {"output": str(output), **metrics}


def _evaluation_markdown(metrics: dict, provenance: dict) -> str:
    rows = [
        ("附录保留页召回", metrics["appendix_page_recall"]),
        ("页眉页脚召回", metrics["header_footer_recall"]),
        ("页眉页脚精确率", metrics["header_footer_precision"]),
        ("页眉页脚 F1", metrics["header_footer_f1"]),
        ("header/footer 文本召回（不含页码）", metrics["header_footer_text_recall"]),
        ("页码召回", metrics["page_number_recall"]),
        ("image 分析召回", metrics["image_analysis_recall"]),
        ("image 分析精确率", metrics["image_analysis_precision"]),
        ("image 分析 F1", metrics["image_analysis_f1"]),
        ("纯 image 召回", metrics["image_only_recall"]),
        ("seal 召回", metrics["seal_recall"]),
        ("chart 定位召回", metrics["chart_location_recall"]),
        ("chart 内容召回", metrics["chart_content_recall"]),
        ("chart 内容精确率", metrics["chart_content_precision"]),
        ("chart 页表格代理召回", metrics["chart_table_page_proxy_recall"]),
    ]
    lines = [
        "# 四项能力评测",
        "",
        f"覆盖预测：{metrics['provided_documents']}/{metrics['expected_documents']}；缺失：{metrics['missing_documents']}。",
        "",
        "| 指标 | 得分 |",
        "| --- | ---: |",
    ]
    lines.extend(
        f"| {name} | {value if value is not None else 'unavailable'} |" for name, value in rows
    )
    lines.extend(
        [
            "",
            "chart 内容 GT 当前来自旧 Markdown 的 12 个候选文档，仍是混合表格候选，不是逐 chart 人工确认的精确表格 GT；`chart_content_*` 只回答候选范围内是否产出实际内容，不能替代数值正确率。",
            "Markdown-only 的 PDF2Text 响应没有可靠 block type；页眉页脚和 image 指标是文本/视觉块保留代理，chart 页表格指标只有在响应提供 page_markdowns 时才可用。",
            f"GT manifest：`{provenance['ground_truth']}`。",
            "",
        ]
    )
    return "\n".join(lines)
