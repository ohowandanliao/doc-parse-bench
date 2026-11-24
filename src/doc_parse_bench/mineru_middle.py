"""MinerU ``middle_json`` capture, PDF2Text filtering and IR conversion.

The public PDF2Text endpoint returns rendered Markdown only.  The feature
evaluation needs the structural result that PDF2Text receives from MinerU,
so this module deliberately keeps the capture/conversion step separate from
the normal Markdown adapters.  A raw MinerU response is read, copied, passed
through the exact ``mineru_filters.py`` selected by the caller, and converted
to :mod:`doc_parse_bench.schema` objects.

The module does not import the PDF2Text repository as a package.  The source
path is explicit and the filter module is loaded with ``importlib``.  This is
important on the evaluation machine, where PDF2Text and doc-parse-bench may
be installed in different environments.
"""

from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import logging
import sys
from collections.abc import Mapping
from pathlib import Path
from types import ModuleType
from typing import Any

from .schema import Block, Document, Page

# The names are the stable names used by MinerU 3.x's local BlockType enum.
# Keep this table here so conversion can still describe a block if the source
# filter module is unavailable while a raw response is being inspected.
_TYPE_NAMES = {
    0: "text",
    1: "title",
    2: "paragraph_title",
    3: "doc_title",
    4: "image",
    5: "image_caption",
    6: "image_footnote",
    7: "table",
    8: "table_caption",
    9: "table_footnote",
    10: "formula",
    11: "formula_number",
    12: "header",
    13: "footer",
    14: "page_number",
    15: "header_image",
    16: "footer_image",
    17: "seal",
    18: "chart",
    19: "chart_body",
    20: "chart_caption",
    21: "chart_footnote",
    22: "reference",
    23: "reference_content",
    24: "content",
    25: "content_title",
    26: "algorithm",
}


def _type_name(value: Any) -> str:
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, int):
        return _TYPE_NAMES.get(value, str(value))
    return str(value or "text").strip().lower()


def _json_value(value: Any) -> Any:
    """Decode JSON strings used by MinerU gateways without changing objects."""
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
    return value


def _first_result(results: Any) -> Mapping[str, Any]:
    if isinstance(results, Mapping):
        if "middle_json" in results:
            return results
        for value in results.values():
            if isinstance(value, Mapping):
                return value
    elif isinstance(results, list):
        for value in results:
            if isinstance(value, Mapping):
                return value
    raise ValueError("MinerU 响应的 results 中没有可用结果")


def extract_middle_json(response: Mapping[str, Any]) -> dict[str, Any]:
    """Extract the one document's ``middle_json`` object from ``/file_parse``.

    MinerU 3.x has returned both a mapping keyed by filename and a one-element
    list in different gateway versions.  ``middle_json`` itself may be a JSON
    string, so both forms are accepted here.
    """

    if not isinstance(response, Mapping):
        raise ValueError("MinerU 响应必须是 JSON 对象")
    result = _first_result(response.get("results", response))
    middle = _json_value(result.get("middle_json"))
    if not isinstance(middle, Mapping):
        raise ValueError("MinerU 响应缺少 results.*.middle_json")
    return dict(middle)


def extract_pdf_info(response: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Return the MinerU ``pdf_info`` page list from a complete response."""

    middle = extract_middle_json(response)
    pdf_info = middle.get("pdf_info", middle)
    # Some wrappers nest the 3.x object one additional time.
    if isinstance(pdf_info, Mapping):
        pdf_info = pdf_info.get("pdf_info", [])
    if not isinstance(pdf_info, list):
        raise ValueError("MinerU middle_json.pdf_info 必须是列表")
    if not all(isinstance(page, Mapping) for page in pdf_info):
        raise ValueError("MinerU middle_json.pdf_info 含有非对象页面")
    return [dict(page) for page in pdf_info]


def response_reported_pages(response: Mapping[str, Any]) -> int | None:
    """Read the gateway's original page count, when one was reported."""

    value = response.get("pages") if isinstance(response, Mapping) else None
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def _filter_path(source: str | Path) -> Path:
    path = Path(source).expanduser().resolve()
    candidates: list[Path]
    if path.is_file():
        candidates = [path]
    else:
        candidates = [
            path / "src/pdf2text/core/parse/mineru_filters.py",
            path / "pdf2text/core/parse/mineru_filters.py",
            path / "mineru_filters.py",
        ]
    for candidate in candidates:
        if candidate.is_file() and candidate.name == "mineru_filters.py":
            return candidate
    raise FileNotFoundError(f"找不到显式 PDF2Text mineru_filters.py：{source}")


def _temporary_logging_stub() -> tuple[dict[str, ModuleType], ModuleType | None]:
    """Supply the tiny logging dependency needed by the frozen filter file.

    The checked-in PDF2Text source imports ``structlog`` only to construct a
    logger.  The evaluation environment need not install PDF2Text's service
    dependencies, so a standard-library logger is sufficient for offline
    filtering.  Existing modules are restored by the caller.
    """

    names = (
        "pdf2text.common.logging.config",
        "pdf2text.common.logging",
        "pdf2text.common",
        "pdf2text",
    )
    previous = {name: sys.modules[name] for name in names if name in sys.modules}
    package = ModuleType("pdf2text")
    common = ModuleType("pdf2text.common")
    logging_package = ModuleType("pdf2text.common.logging")
    config = ModuleType("pdf2text.common.logging.config")
    config.get_logger = logging.getLogger  # type: ignore[attr-defined]
    package.__path__ = []  # type: ignore[attr-defined]
    common.__path__ = []  # type: ignore[attr-defined]
    logging_package.__path__ = []  # type: ignore[attr-defined]
    sys.modules.update(
        {
            "pdf2text": package,
            "pdf2text.common": common,
            "pdf2text.common.logging": logging_package,
            "pdf2text.common.logging.config": config,
        }
    )
    return previous, config


def _restore_modules(previous: dict[str, ModuleType]) -> None:
    for name in (
        "pdf2text.common.logging.config",
        "pdf2text.common.logging",
        "pdf2text.common",
        "pdf2text",
    ):
        sys.modules.pop(name, None)
    sys.modules.update(previous)


def load_pdf2text_filters(source: str | Path) -> ModuleType:
    """Dynamically load the selected PDF2Text ``mineru_filters.py`` module."""

    path = _filter_path(source)
    digest = hashlib.sha1(str(path).encode()).hexdigest()[:12]
    module_name = f"_docbench_pdf2text_filters_{digest}"
    cached = sys.modules.get(module_name)
    if cached is not None:
        return cached
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"无法加载 PDF2Text 过滤器：{path}")
    module = importlib.util.module_from_spec(spec)
    source_root = next((parent for parent in path.parents if (parent / "pdf2text").is_dir()), None)
    previous_stub: dict[str, ModuleType] = {}
    if source_root is not None and str(source_root) not in sys.path:
        sys.path.insert(0, str(source_root))
        inserted = True
    else:
        inserted = False
    try:
        try:
            spec.loader.exec_module(module)
        except ModuleNotFoundError as exc:
            # The source snapshot's logger imports structlog, which is not a
            # runtime dependency of doc-parse-bench.  Retry with a stub only
            # for that optional logging dependency.
            if exc.name != "structlog":
                raise
            previous_stub, _ = _temporary_logging_stub()
            try:
                spec.loader.exec_module(module)
            finally:
                _restore_modules(previous_stub)
    finally:
        if inserted:
            sys.path.remove(str(source_root))
    sys.modules[module_name] = module
    if not callable(getattr(module, "apply_content_filters", None)):
        raise ImportError(f"过滤器缺少 apply_content_filters：{path}")
    return module


def _mark_raw_types(pdf_info: list[dict[str, Any]]) -> None:
    """Stamp immutable provenance before the in-place PDF2Text filters run."""

    def walk(block: dict[str, Any], index_path: tuple[int, ...]) -> None:
        raw_type = _type_name(block.get("type"))
        block.setdefault("_docbench_raw_type", raw_type)
        block.setdefault("_docbench_source_type", raw_type)
        block.setdefault("_docbench_raw_id", block.get("id", block.get("block_id")))
        block.setdefault("_docbench_index_path", list(index_path))
        for child_index, child in enumerate(block.get("blocks") or []):
            if isinstance(child, dict):
                walk(child, (*index_path, child_index))

    for page in pdf_info:
        for key in ("para_blocks", "discarded_blocks"):
            for index, block in enumerate(page.get(key) or []):
                if isinstance(block, dict):
                    walk(block, (index,))


def apply_pdf2text_filters(
    pdf_info: list[dict[str, Any]],
    *,
    pdf2text_source: str | Path,
    keep_appendix: bool = False,
    keep_header_footer: bool = False,
    image_analysis: bool = False,
    chart_analysis: bool = False,
    relevel_titles: bool = True,
    title_rules: bool = False,
    keep_toc: bool = True,
    use_scheduler: bool = False,
) -> list[dict[str, Any]]:
    """Copy and filter ``pdf_info`` using the selected PDF2Text source.

    ``use_scheduler`` is available for source snapshots that need the full
    compatibility scheduler.  The normal four-feature path calls the content
    stage and MinerU3 relevel separately, which avoids importing title-rule
    dependencies while preserving the documented ``title_rules=false`` path.
    """

    filters = load_pdf2text_filters(pdf2text_source)
    working = copy.deepcopy(pdf_info)
    _mark_raw_types(working)
    options = {
        "keep_header_footer_enabled": keep_header_footer,
        "remove_toc": not keep_toc,
        "remove_appendix": not keep_appendix,
        "seal_enabled": True,
        "chart_analysis_enabled": chart_analysis,
        "image_analysis_enabled": image_analysis,
    }
    if use_scheduler and callable(getattr(filters, "apply_filters", None)):
        filters.apply_filters(
            working,
            relevel_titles_enabled=relevel_titles,
            title_rules_enabled=title_rules,
            **options,
        )
    else:
        filters.apply_content_filters(working, **options)
        if relevel_titles and callable(getattr(filters, "relevel_titles", None)):
            filters.relevel_titles(working)
        if title_rules:
            raise ValueError("离线四功能过滤默认要求 title_rules=false；请使用 use_scheduler")
    return working


def _bbox(value: Any, width: float, height: float) -> list[float] | None:
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        return None
    try:
        values = [float(item) for item in value]
    except (TypeError, ValueError):
        return None
    # MinerU4's adapter expresses coordinates in [0, 1] before scaling to its
    # virtual page; tolerate that shape when it appears in a raw response.
    if all(0 <= item <= 1 for item in values) and width > 1 and height > 1:
        normalized = values
    else:
        normalized = [values[0] / width, values[1] / height, values[2] / width, values[3] / height]
    return [max(0.0, min(1.0, item)) for item in normalized]


def _span_record(span: Mapping[str, Any]) -> dict[str, Any]:
    # Keep the fields needed to distinguish generated image descriptions from
    # printed captions while avoiding a second copy of unrelated gateway data.
    keys = (
        "type", "text", "content", "generated", "image_path", "html", "bbox",
        "subimage_source", "subimage_index",
    )
    return {key: copy.deepcopy(span[key]) for key in keys if key in span}


def _all_span_records(block: Mapping[str, Any]) -> list[dict[str, Any]]:
    records = [
        _span_record(span)
        for line in block.get("lines") or []
        if isinstance(line, Mapping)
        for span in line.get("spans") or []
        if isinstance(span, Mapping)
    ]
    for child in block.get("blocks") or []:
        if isinstance(child, Mapping):
            records.extend(_all_span_records(child))
    return records


def _block_text(block: Mapping[str, Any]) -> str:
    values: list[str] = []
    for line in block.get("lines") or []:
        if not isinstance(line, Mapping):
            continue
        for span in line.get("spans") or []:
            if not isinstance(span, Mapping):
                continue
            value = span.get("text", span.get("content", ""))
            if isinstance(value, str) and value:
                values.append(value)
    return "".join(values).strip()


def _nested_records(block: Mapping[str, Any], width: float, height: float) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for child in block.get("blocks") or []:
        if not isinstance(child, Mapping):
            continue
        current_type = _type_name(child.get("type"))
        record: dict[str, Any] = {
            "type": current_type,
            "raw_type": child.get("_docbench_raw_type", current_type),
            "source_type": child.get("_docbench_source_type", current_type),
            "bbox": _bbox(child.get("bbox"), width, height),
            "text": _block_text(child),
            "content": copy.deepcopy(child.get("content")) if "content" in child else None,
            "html": copy.deepcopy(child.get("html")) if "html" in child else None,
            "spans": [
                _span_record(span)
                for line in child.get("lines") or []
                if isinstance(line, Mapping)
                for span in line.get("spans") or []
                if isinstance(span, Mapping)
            ],
        }
        record["blocks"] = _nested_records(child, width, height)
        records.append(record)
    return records


def _html_from_nested(nested: list[dict[str, Any]]) -> str:
    for child in nested:
        if child.get("type") in {"chart_body", "table_body"}:
            spans = child.get("spans") or []
            # PDF2Text clears chart-body span text/content when chart analysis
            # is disabled.  Do not resurrect that content from a stale parent
            # ``html`` field in the raw gateway object.
            if spans and not any(
                isinstance(span.get(key), str) and span[key].strip()
                for span in spans
                for key in ("text", "content")
            ):
                return ""
            value = child.get("html") or child.get("content")
            if isinstance(value, str) and value:
                return value
            span_values = [
                span.get(key)
                for span in spans
                for key in ("text", "content")
                if isinstance(span.get(key), str) and span[key].strip()
            ]
            if span_values:
                return "\n".join(span_values)
    return ""


def pdf_info_to_document(
    pdf_info: list[dict[str, Any]],
    *,
    document_id: str,
    reported_pages: int | None = None,
    source: str | Path | None = None,
    effective_config: Mapping[str, Any] | None = None,
    original_reported_pages: int | None = None,
) -> Document:
    """Convert filtered MinerU pages into the benchmark's explicit-page IR."""

    pages: list[Page] = []
    used_ids: set[str] = set()
    for page_position, raw_page in enumerate(pdf_info):
        page_idx = int(raw_page.get("page_idx", page_position))
        page_size = raw_page.get("page_size") or [1000, 1000]
        try:
            width, height = float(page_size[0]), float(page_size[1])
        except (TypeError, ValueError, IndexError):
            width, height = 1000.0, 1000.0
        if width <= 0 or height <= 0:
            width, height = 1000.0, 1000.0
        blocks: list[Block] = []
        for index, raw_block in enumerate(raw_page.get("para_blocks") or []):
            if not isinstance(raw_block, Mapping):
                continue
            current_type = _type_name(raw_block.get("type"))
            raw_type = str(raw_block.get("_docbench_raw_type", current_type))
            source_type = str(raw_block.get("_docbench_source_type", raw_type))
            native_id = (
                raw_block.get("_docbench_raw_id")
                or raw_block.get("id")
                or raw_block.get("block_id")
            )
            block_id = str(native_id or f"mineru.p{page_idx + 1}.{index:04d}")
            if block_id in used_ids:
                suffix = 2
                while f"{block_id}#{suffix}" in used_ids:
                    suffix += 1
                block_id = f"{block_id}#{suffix}"
            used_ids.add(block_id)
            nested = _nested_records(raw_block, width, height)
            spans = _all_span_records(raw_block)
            generated = [
                span
                for span in spans
                if span.get("generated") is True or span.get("type") == "image"
            ]
            metadata: dict[str, Any] = {
                "raw_type": raw_type,
                "source_type": source_type,
                "current_type": current_type,
                "raw_block_id": raw_block.get("_docbench_raw_id"),
                "native_index": copy.deepcopy(raw_block.get("index")),
                "source": copy.deepcopy(raw_block.get("_source")),
                "spans": spans,
                "generated_spans": generated,
                "nested_blocks": nested,
            }
            if "sub_type" in raw_block:
                metadata["sub_type"] = copy.deepcopy(raw_block["sub_type"])
            chart_body = [child for child in nested if child.get("type") == "chart_body"]
            if chart_body:
                metadata["chart_body"] = chart_body
            level = raw_block.get("level", raw_block.get("text_level"))
            try:
                level = int(level) if level is not None else None
            except (TypeError, ValueError):
                level = None
            blocks.append(
                Block(
                    block_id,
                    current_type,
                    _block_text(raw_block),
                    _html_from_nested(nested),
                    _bbox(raw_block.get("bbox"), width, height),
                    level,
                    metadata,
                )
            )
        pages.append(
            Page(
                page_idx + 1,
                blocks,
                width,
                height,
                {"page_idx": page_idx, "page_size": [width, height]},
            )
        )
    metadata = {
        "origin": "mineru_middle_json",
        "source": str(source) if source is not None else None,
        "page_boundaries": "explicit",
        "reported_pages": reported_pages if reported_pages is not None else len(pages),
        "source_reported_pages": original_reported_pages,
        "effective_config": dict(effective_config or {}),
    }
    document = Document(document_id, pages, metadata=metadata)
    document.validate()
    return document


def response_to_document(
    response: Mapping[str, Any],
    *,
    document_id: str,
    pdf2text_source: str | Path | None = None,
    filter_options: Mapping[str, Any] | None = None,
    source: str | Path | None = None,
) -> Document:
    """Extract, optionally filter, and convert one complete MinerU response."""

    raw_pdf_info = extract_pdf_info(response)
    options = dict(filter_options or {})
    original_pages = response_reported_pages(response) or len(raw_pdf_info)
    filtered = raw_pdf_info
    if pdf2text_source is not None:
        filtered = apply_pdf2text_filters(
            raw_pdf_info,
            pdf2text_source=pdf2text_source,
            **options,
        )
    return pdf_info_to_document(
        filtered,
        document_id=document_id,
        reported_pages=len(filtered),
        source=source,
        effective_config=options,
        original_reported_pages=original_pages,
    )
