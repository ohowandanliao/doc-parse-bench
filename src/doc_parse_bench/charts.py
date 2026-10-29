"""Auditable chart transcription extension shared by every model.

A provider command receives one JSON request on stdin, including a crop, and
returns {"is_chart": bool, "html": "<table>...</table>"}. No provider runs unless
explicitly configured. GT accepts reviewed sidecars only.
"""

import base64
import io
import json
import subprocess
from copy import deepcopy
from pathlib import Path

from .io import fresh_directory, read_json, write_json
from .schema import VISUAL_TYPES, load_documents


def augment_charts(
    source: Path,
    output: Path,
    tables: Path | None = None,
    provider: list[str] | None = None,
    pdf_dir: Path | None = None,
) -> dict:
    if bool(tables) == bool(provider):
        raise ValueError("需指定一个图表数据表 sidecar 或 provider 命令")
    sidecar = read_json(tables) if tables else {}
    documents = load_documents(source)
    if provider and any(d.metadata.get("origin") == "annotations" for d in documents):
        raise ValueError("GT 不接受未经人工确认的 provider 结果；先生成并审核 sidecar")
    output = fresh_directory(output)
    records = []
    matched = set()
    for original in documents:
        doc = deepcopy(original)
        for page in doc.pages:
            for block in page.blocks:
                if block.type not in VISUAL_TYPES:
                    continue
                key = f"{doc.id}/{block.id}"
                item = sidecar.get(key)
                if provider:
                    if not block.bbox:
                        records.append({"key": key, "status": "no_bbox"})
                        continue
                    if pdf_dir is None:
                        raise ValueError("provider 模式需要 --pdf-dir")
                    request = {
                        "document": doc.id,
                        "block_id": block.id,
                        "page": page.number,
                        "bbox": block.bbox,
                        "image_png_base64": _crop(
                            pdf_dir / f"{doc.id}.pdf", page.number, block.bbox
                        ),
                    }
                    result = subprocess.run(
                        provider,
                        input=json.dumps(request),
                        text=True,
                        capture_output=True,
                        check=True,
                        timeout=180,
                    )
                    item = json.loads(result.stdout)
                if not item:
                    continue
                matched.add(key)
                if doc.metadata.get("origin") == "annotations" and item.get("reviewed") is not True:
                    raise ValueError(f"GT 图表数据表尚未人工确认：{key}")
                if item.get("is_chart", True):
                    html = item.get("html", "")
                    if "<table" not in html.lower() or "</table>" not in html.lower():
                        raise ValueError(f"图表 provider/sidecar 未返回完整 HTML 表格：{key}")
                    block.type, block.html = "chart", html
                    block.metadata["chart_enrichment"] = item
                    records.append({"key": key, "status": "transcribed", "result": item})
        doc.metadata["chart_enhanced"] = True
        doc.dump(output / "documents" / f"{doc.id}.json")
    if sidecar.keys() - matched:
        raise ValueError(
            f"sidecar 引用了不存在的 visual block：{sorted(sidecar.keys() - matched)[:5]}"
        )
    report = {"records": records, "provider": provider, "tables": str(tables) if tables else None}
    write_json(output / "chart_audit.json", report)
    return report


def _crop(path: Path, number: int, bbox: list[float]) -> str:
    import pypdfium2 as pdfium

    with pdfium.PdfDocument(path) as pdf:
        page = pdf[number - 1]
        image = page.render(scale=2).to_pil()
        x1, y1, x2, y2 = [v * scale for v, scale in zip(bbox, [image.width, image.height] * 2)]
        crop = image.crop((int(x1), int(y1), int(x2), int(y2)))
        buffer = io.BytesIO()
        crop.save(buffer, format="PNG")
        return base64.b64encode(buffer.getvalue()).decode("ascii")
