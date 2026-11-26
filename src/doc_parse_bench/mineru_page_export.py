"""Prepare MinerU 3.x source-page tables for OmniDocBench."""

import asyncio
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory

from .io import read_json, safe_name, sha256, write_json
from .mineru_middle import _type_name, extract_pdf_info


def project_source_tables(pdf_info: list[dict]) -> tuple[list[dict], list[dict]]:
    """Restore native pre-merge table blocks to their original page and position."""
    projected, restored = [], []
    seen_pages = set()
    for page in pdf_info:
        page_idx = page.get("page_idx")
        if type(page_idx) is not int or page_idx < 0 or page_idx in seen_pages:
            raise ValueError(f"MinerU 原始页码无效或重复：{page_idx!r}")
        seen_pages.add(page_idx)
        blocks = page["para_blocks"]
        sources = [
            block
            for block in page.get("preproc_blocks", [])
            if _type_name(block["type"]) == "table"
        ]
        matched = set()
        page_blocks = list(blocks)
        for position, block in enumerate(blocks):
            if _type_name(block["type"]) != "table":
                continue
            index, bbox = block.get("index"), block.get("bbox")
            matches = [
                source_position
                for source_position, source in enumerate(sources)
                if index is not None
                and bbox
                and (source.get("index"), source.get("bbox")) == (index, bbox)
            ]
            if len(matches) != 1 or matches[0] in matched:
                raise ValueError(f"第 {page_idx + 1} 页表格 index={index} 缺少唯一的合并前片段")
            source_position = matches[0]
            matched.add(source_position)
            source = sources[source_position]
            if any(child.get("lines_deleted") for child in source["blocks"]):
                raise ValueError(f"第 {page_idx + 1} 页表格 index={index} 的合并前片段已被清除")
            if source == block:
                continue
            table = source.copy()
            table["blocks"] = [
                child
                for child in source["blocks"]
                if not (
                    _type_name(child["type"]) == "table_caption"
                    and {**child, "type": "text"} in blocks
                )
            ]
            page_blocks[position] = table
            restored.append({"page": page_idx + 1, "native_index": index})
        if len(matched) != len(sources):
            raise ValueError(f"第 {page_idx + 1} 页存在缺少渲染位置的合并前表格片段")
        projected.append({**page, "para_blocks": page_blocks})
    return deepcopy(projected), restored


async def _render_predictions(
    files: list[Path], output: Path, config: dict, include_documents: bool
) -> dict:
    from pdf2text.core.parse import mineru_client, mineru_filters, mineru_postprocess

    post = mineru_postprocess.PostProcessParams(**config)
    if post.structure_repair:
        raise ValueError("逐页重放要求 PDF2Text 配置的 structure_repair=false")
    directory = output / "OmniDocBench"
    directory.mkdir(parents=True)
    full_directory = output / "MPDocBench"
    if include_documents:
        full_directory.mkdir()
    documents = {}
    for path in files:
        name = safe_name(path.stem.removesuffix(".middle_json"))
        if name in documents:
            raise ValueError(f"重复的 MinerU 文档输出：{name}")
        response = read_json(path)
        pdf_info = response["pdf_info"] if "pdf_info" in response else extract_pdf_info(response)
        try:
            projected, restored = project_source_tables(pdf_info)
        except (KeyError, ValueError) as error:
            raise ValueError(f"{path.name}：{error}") from error
        document = await mineru_postprocess.postprocess_mineru(
            projected, provider="mineru3", post=post, file_bytes=b"", filename=f"{name}.pdf"
        )
        for page in document.pdf_info:
            number = page["page_idx"] + 1
            (directory / f"{name}__p{number:04d}.md").write_text(
                mineru_client.render_mineru_markdown([page]), encoding="utf-8"
            )
        if include_documents:
            full_document = document
            if restored:
                full_document = await mineru_postprocess.postprocess_mineru(
                    pdf_info, provider="mineru3", post=post, file_bytes=b"", filename=f"{name}.pdf"
                )
            (full_directory / f"{name}.md").write_text(
                mineru_client.render_mineru_markdown(full_document.pdf_info), encoding="utf-8"
            )
        documents[name] = {
            "source_sha256": sha256(path),
            "pages": len(document.pdf_info),
            "restored_tables": restored,
        }
    return {
        "kind": "prediction",
        "page_table_source": "MinerU 3.x preproc_blocks",
        "pdf2text_config": post.model_dump(),
        "pdf2text_source_sha256": {
            module.__name__: sha256(Path(module.__file__))
            for module in (mineru_client, mineru_filters, mineru_postprocess)
        },
        "documents": documents,
    }


def export_mineru_predictions(
    raw: Path, config: Path, output: Path, *, include_documents: bool = False
) -> dict:
    """Replay PDF2Text and export original-page predictions and optional full Markdown."""
    files = (
        [raw]
        if raw.is_file()
        else sorted(path for path in raw.glob("*.json") if path.stem != "manifest")
    )
    if not files:
        raise ValueError(f"没有 MinerU 原始响应：{raw}")
    output = output.resolve()
    if output.exists() and (not output.is_dir() or any(output.iterdir())):
        raise ValueError(f"输出目录非空，请选用新目录：{output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(dir=output.parent) as temporary:
        staged = Path(temporary) / "export"
        try:
            manifest = asyncio.run(
                _render_predictions(files, staged, read_json(config), include_documents)
            )
        except ImportError as error:
            raise ValueError(f"请在原评测的 PDF2Text 渲染环境中执行导出（{error}）") from error
        write_json(staged / "manifest.json", manifest)
        staged.rename(output)
    return {
        "output": str(output),
        "documents": len(manifest["documents"]),
        "pages": sum(item["pages"] for item in manifest["documents"].values()),
        "restored_tables": sum(
            len(item["restored_tables"]) for item in manifest["documents"].values()
        ),
    }
