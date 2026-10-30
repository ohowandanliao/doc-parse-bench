"""Read-only repetition screening with original snippets and page-level evidence.

Long exact loops are candidates for review. This does not deduplicate predictions
or treat ordinary repeated headers across different pages as generation failures.
"""

import re
from pathlib import Path

from .io import fresh_directory, read_json, safe_name, sha256, write_json
from .schema import load_documents
from .unlimited_ocr2_parser import PAGE_RE

CHARACTER_LOOP = re.compile(r"(?P<unit>[^\n]{1,100}?)(?P=unit){11,}")


def detect_repetition(text: str) -> list[dict]:
    """Screen exact character loops and consecutive identical nonblank lines."""
    hits = []
    for match in CHARACTER_LOOP.finditer(text):
        if len(match.group()) >= 200 and any(c.isalnum() for c in match["unit"]):
            hits.append(
                {
                    "kind": "character_loop",
                    "unit": match["unit"],
                    "repeats": len(match.group()) // len(match["unit"]),
                    "start": match.start(),
                    "end": match.end(),
                }
            )
    lines = []
    offset = 0
    for number, raw in enumerate(text.splitlines(keepends=True), 1):
        value = re.sub(r"\s+", " ", raw).strip()
        if value:
            lines.append((value, offset, offset + len(raw), number))
        offset += len(raw)
    start = 0
    while start < len(lines):
        end = start + 1
        while end < len(lines) and lines[end][0] == lines[start][0]:
            end += 1
        unit = lines[start][0]
        if end - start >= 20 and any(c.isalnum() for c in unit):
            hits.append(
                {
                    "kind": "identical_lines",
                    "unit": unit,
                    "repeats": end - start,
                    "start": lines[start][1],
                    "end": lines[end - 1][2],
                    "line_start": lines[start][3],
                    "line_end": lines[end - 1][3],
                }
            )
        start = end
    for hit in hits:
        hit["span_characters"] = hit["end"] - hit["start"]
        hit["excerpt"] = text[max(0, hit["start"] - 120) : min(hit["end"], hit["start"] + 500)]
    return sorted(hits, key=lambda h: (h["start"], h["kind"]))


def _raw_pages(text: str) -> list[tuple[int, str]]:
    markers = list(PAGE_RE.finditer(text))
    if not markers:
        return [(1, text)]
    return [
        (i + 1, text[m.end() : markers[i + 1].start() if i + 1 < len(markers) else len(text)])
        for i, m in enumerate(markers)
    ]


def audit_repetition(
    source: Path, output: Path, evaluated: Path | None = None, ground_truth: Path | None = None
) -> dict:
    """Inspect saved model JSONs; optionally inspect actual page exports and GT."""
    output = fresh_directory(output)
    gt_pages = {}
    if ground_truth:
        for doc in load_documents(ground_truth):
            for page in doc.pages:
                gt_pages[(doc.id, page.number)] = "\n\n".join(b.html or b.text for b in page.blocks)
    report = {
        "rules": {
            "character_loop": "unit 1–100 chars, >=12 copies, >=200 chars",
            "identical_lines": ">=20 consecutive nonblank lines; collapse whitespace",
            "excluded": "punctuation-only units and cross-page header repetition",
        },
        "limitations": "Candidates require review; fuzzy loops and cross-page duplication are not exhaustively detected.",
        "models": {},
    }
    for folder in sorted(p for p in source.iterdir() if p.is_dir()):
        files = sorted(folder.glob("*.json"))
        if not files:
            continue
        model = safe_name(folder.name)
        entries, observed, source_hashes = [], set(), {}
        original_pages, evaluated_pages = set(), set()
        documents = []
        for path in files:
            obj = read_json(path)
            doc_id = safe_name(obj.get("stem", path.stem))
            source_hashes[path.name] = sha256(path)
            documents.append(
                {
                    "document": doc_id,
                    "declared_pages": obj.get("n_pages"),
                    "returned_pages": len(obj["pages"]),
                    "finish": obj.get("meta", {}).get("finish"),
                }
            )
            contents = []
            blocks = {}
            for page in obj["pages"]:
                number = int(page["page"])
                observed.add((doc_id, number))
                text = page.get("md") or ""
                if not isinstance(text, str):
                    raise ValueError(f"非字符串 Markdown：{path}/{number}")
                contents.append((number, "original-markdown", text))
                blocks[number] = page.get("blocks") or []
            if isinstance(obj.get("raw"), str):
                contents.extend((n, "original-raw", text) for n, text in _raw_pages(obj["raw"]))
            if evaluated:
                for number in sorted(n for d, n in observed if d == doc_id):
                    page_path = evaluated / model / "OmniDocBench" / f"{doc_id}__p{number:04d}.md"
                    if not page_path.is_file():
                        raise ValueError(f"缺少已导出页面：{page_path}")
                    contents.append(
                        (number, "evaluation-markdown", page_path.read_text(encoding="utf-8"))
                    )
            for number, channel, text in contents:
                hits = detect_repetition(text)
                if not hits:
                    continue
                pair = (doc_id, number)
                (evaluated_pages if channel == "evaluation-markdown" else original_pages).add(pair)
                evidence = Path("examples") / model / doc_id / f"page_{number:04d}.{channel}.txt"
                target = output / evidence
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(text, encoding="utf-8")
                gt = gt_pages.get(pair)
                for hit in hits:
                    unit = hit["unit"]
                    hit["block_types"] = sorted(
                        {
                            b["type"]
                            for b in blocks.get(number, [])
                            if unit.strip() and unit.strip() in (b.get("content") or "")
                        }
                    )
                    hit["gt_unit_occurrences"] = (
                        gt.count(unit.strip()) if gt is not None and unit.strip() else None
                    )
                    entries.append(
                        {
                            "document": doc_id,
                            "page": number,
                            "channel": channel,
                            "source": str(path.resolve()),
                            "evidence": evidence.as_posix(),
                            **hit,
                        }
                    )
        report["models"][model] = {
            "documents": len(files),
            "observed_pages": len(observed),
            "original_candidate_documents": len({d for d, _ in original_pages}),
            "original_candidate_pages": len(original_pages),
            "evaluation_candidate_pages": len(evaluated_pages) if evaluated else None,
            "document_status": documents,
            "source_sha256": source_hashes,
            "findings": entries,
        }
    if not report["models"]:
        raise ValueError(f"没有模型结果目录：{source}")
    write_json(output / "audit.json", report)
    _write_report(output, report)
    return {
        "report": str(output / "report.md"),
        "models": {
            model: {
                k: values[k]
                for k in (
                    "documents",
                    "observed_pages",
                    "original_candidate_documents",
                    "original_candidate_pages",
                    "evaluation_candidate_pages",
                )
            }
            for model, values in report["models"].items()
        },
    }


def _write_report(output: Path, report: dict) -> None:
    lines = [
        "# 四模型重复输出检查",
        "",
        "检测对象为保存的原始输出；不修改预测、不重新跑分。",
        "表中是长连续重复的候选页面，不能当作模型整体错误率。页眉跨页重复不计入；",
        "近似重复和整页重放不在本轮穷举范围。",
        "",
        "| 模型 | 文档 | 返回页 | 原始候选文档 | 原始候选页 | 评测 Markdown 候选页 |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for model, values in report["models"].items():
        lines.append(
            f"| {model} | {values['documents']} | {values['observed_pages']} | "
            f"{values['original_candidate_documents']} | {values['original_candidate_pages']} | "
            f"{values['evaluation_candidate_pages']} |"
        )
    lines.extend(
        [
            "",
            "字符规则：单元长度 1–100，连续至少 12 次且总长至少 200；",
            "行规则：去空行、合并行内空白后，连续至少 20 行相同。标点装饰单元排除。",
            "",
            "原始输出和评测导出分别检查，避免把被视觉占位符替换的图片描述算成正文污染。",
            "同页不同表示、不同检测规则可能重复命中，表中按页去重。",
            "",
        ]
    )
    examples = []
    for model, values in report["models"].items():
        # Pick the longest original example of each kind without document-specific rules.
        for kind in ("character_loop", "identical_lines"):
            candidates = [
                f
                for f in values["findings"]
                if f["channel"] != "evaluation-markdown" and f["kind"] == kind
            ]
            if candidates:
                examples.append((model, max(candidates, key=lambda h: h["span_characters"])))
    lines.extend(
        [
            "## 代表性原文",
            "",
            "以下只显示开头一小段；完整页面通过链接查看，重复次数由原文统计。",
            "",
        ]
    )
    for model, hit in examples:
        document, page = hit["document"], hit["page"]
        original = (output / hit["evidence"]).read_text(encoding="utf-8")
        snippet = original[hit["start"] : min(hit["end"], hit["start"] + 260)]
        lines.extend(
            [
                f"### {model} / {document} / 第 {page} 页",
                "",
                f"重复 {hit['repeats']} 次；该单元在对应 GT 中出现 {hit['gt_unit_occurrences']} 次。",
                f"[完整原文]({hit['evidence']})",
                "",
                "```text",
                snippet,
                "```",
                "",
            ]
        )
    for model, values in report["models"].items():
        lines.extend(
            [
                f"## {model}",
                "",
                "| 文档 | 页 | 来源 | 重复次数 | 单元（截取） | 块类型 | 原文 |",
                "| --- | --- | --- | --- | --- | --- | --- |",
            ]
        )
        findings = [f for f in values["findings"] if f["channel"] != "evaluation-markdown"]
        by_page = {}
        for item in sorted(findings, key=lambda f: f["span_characters"], reverse=True):
            by_page.setdefault((item["document"], item["page"]), item)
        for item in sorted(by_page.values(), key=lambda f: (f["document"], f["page"])):
            unit = item["unit"].replace("|", "\\|").replace("\n", " ")[:90]
            lines.append(
                f"| {item['document']} | {item['page']} | {item['channel']} | {item['repeats']} | "
                f"`{unit}` | {', '.join(item['block_types']) or '—'} | [查看]({item['evidence']}) |"
            )
        lines.append("")
    (output / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
