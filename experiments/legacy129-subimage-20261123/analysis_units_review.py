"""Build an offline review of parent/child analysis units using saved responses only."""

from __future__ import annotations

import argparse
import ast
import base64
import hashlib
import json
import shutil
import zipfile
from collections import defaultdict
from html import escape
from pathlib import Path

import pypdfium2 as pdfium
from flowchart_relation_review import audit as audit_flowchart
from markdown_it import MarkdownIt

from doc_parse_bench.feature_evaluation.feature_eval import _iou
from doc_parse_bench.mineru_middle import extract_pdf_info

EXPECTED_RECORDS_SHA = "a1384023b6bc67aba52b312091f7bd729c2fc0eba7940e745d422e56fd0c9b29"
VARIANTS = {
    "ft-before": "FT 首轮 · 原始结构回包",
    "ft-package": "FT 原包补偿 · 历史回放",
    "ft-all-split": "FT 全拆交付 · 历史回放",
    "ft-adapted": "FT 前置候选 · 历史回放",
    "origin-6docs": "Origin · 同开关对照",
}
# Reviewed recommendations for these cases, not a production decision rule.
NOTES = {
    ("bc_022", 2, 2): {
        "unit": "parent", "title": "Fig. 1 · 两种制备工艺",
        "reason": "(a)/(b) 共同组成 Fig. 1。建议分析整幅工艺示意并保留一个父图，保留两面板的字段归属。",
        "all_split": "拆成 2 块；上面板 IoU 0.544 可匹配，下方 0.444 不匹配。上面板 flowchart 标签不能代表整图；下面板只读到 PP、CO₂，缺失完整设备与工序证据。",
        "gap": "整父图响应未采到。17 个校准文字字段已有 GT，本图没有正式关系 GT；虚线标注不能直接当流程边。",
    },
    ("bc_022", 5, 2): {
        "unit": "parent", "title": "Fig. 6 · 装置与滤片对照组图",
        "reason": "装置示意与六个滤片面板共用 Fig. 6 图注，按整组理解。建议整图分析一次、保留父图。",
        "all_split": "拆成 7 块，5 份结果只含 OCR 文字；最大子框 IoU 0.447，没有一块能匹配整组 GT。原包虽分析了七张，最后保留父图并丢弃全部七份结果。",
        "gap": "没有整父图分析响应，也没有该图已冻结的内容／subtype GT。不能把已有局部文字拼成整图模型回答。",
    },
    ("bc_062", 1, 12): {
        "unit": "parent", "title": "图 13.12 · 共图注线路组图",
        "reason": "左右示意共用一个图号与图注，当前 v3 作为一个源图。建议保留父框并读取整组内容。",
        "all_split": "原包和全拆都变成两个半框，IoU 0.466／0.469，原先命中的一个源图变成零命中。子图都有文字，所以“纯文字比例”不能保护此组。",
        "gap": "父框对应的整图分析尚缺；此组没有冻结内容 subtype／节点／关系 GT。现有 text_image 是子裁图实际标签。",
    },
    ("bc_062", 1, 16): {
        "unit": "parent", "title": "图 13.13 · 共图注线路组图",
        "reason": "第二组左右线路图也属于一个共同图号。建议保留原父图并补整组分析。",
        "all_split": "两个半框 IoU 0.469／0.463，原先一个定位命中丢失；EF-RT、Rf 等标签即使分别读出，也不等于整组接线关系被读对。",
        "gap": "父图分析缺证据；本组内容和 subtype GT 尚未冻结，不能用 Origin 的 text_image 当 GT。",
    },
    ("bc_022", 4, 11): {
        "unit": "children", "title": "Fig. 5 · 两张独立柱图",
        "reason": "两图各有坐标轴、系列和单位：Draw Resistance (Pa) 与 Open-cell Content (%)。建议分别分析两个子框。共同图注只保留一份。",
        "all_split": "正例：两份真实 chart/bar 响应补回 10/10 个明示值。子框 IoU 0.982／0.991；拆前父图没有可评分表。",
        "gap": "两个子图响应已齐，可复用；独立 chart-only 组合与最终标题重排仍需验证。",
    },
    ("bc_059", 1, 16): {
        "unit": "children", "title": "维修手册 · 四张独立设备照片",
        "reason": "四张不同设备／器件照片是独立素材，建议分析四个子图，各自保留图片和标签。",
        "all_split": "定位收益明确，四图 IoU 0.965–0.994。“音量调节”裁图退化为 OCR，无 subtype；第二张视觉块内容空且无 subtype，后两张 natural_image。",
        "gap": "读到“音量调节”不等于 natural_image 标签正确。现有四份响应可评已冻结范围，不用整父图掩盖单图空结果。",
    },
    ("bc_065", 1, 18): {
        "unit": "children", "title": "消防系统 · 两幅独立接线示意",
        "reason": "下方左右为两幅独立源图，建议分别分析，不能将一份同名标签同时算到两图。",
        "all_split": "子框 IoU 均约 0.981。FT 两图实际均是 text_image，GT 为 flowchart；图片主分均为 0。文字诊断左图 100、右图 87.50（PE→PH），两份输出均未提供关系结构。",
        "gap": "已有标签与文字响应；GT 当前只评每图八字段，不评无明确方向的接线。文字正确不能证明连接、方向和归属正确。",
    },
    ("bc_077", 1, 9): {
        "unit": "children", "title": "惠玩甘青 4 · 两张城楼照片",
        "reason": "两张独立取景照片，建议分别读取。第一张照片有牌匾文字，仍需区分源图类型与图中文字。",
        "all_split": "两图定位命中（IoU 0.985／0.987）；FT 左图给 text_image 且牌匾文字明显可疑，右图为 natural_image。拆分解决粒度，不能修正错字或错类型。",
        "gap": "本组没有冻结内容／subtype GT。左图原文与实际输出并排，作为待审 badcase，不擅自重标或计新分。",
    },
    ("bc_078", 1, 1): {
        "unit": "children", "title": "惠玩甘青 7 · 两张盐湖照片",
        "reason": "左右独立无字照片，建议按两张子图交付并保留各自 natural_image 标签。",
        "all_split": "正例：IoU 0.993／0.990，两份子图均 natural_image。校准范围只要求资产可访问、没有编造图中文字，不强求场景描述。",
        "gap": "两张子图响应和校准 GT 已齐。场景描述仅作诊断，不拿描述长度当质量分。",
    },
    ("bc_078", 1, 12): {
        "unit": "children", "title": "惠玩甘青 7 · 两张寺院照片",
        "reason": "下方两张独立照片，建议复用两个子框分析结果，分别交付。",
        "all_split": "两图 IoU 0.993／0.993，FT 子图均 natural_image。已有实际场景描述，不能由非空直接推断描述正确。",
        "gap": "已有两份子图响应，未有冻结内容／subtype GT；先保留资产与来源，描述另列诊断。",
    },
}

STYLE = """
:root{--ink:#203329;--muted:#647167;--accent:#167058;--line:#dce5df;--bg:#f3f6f2;--warn:#946018}
*{box-sizing:border-box}html{scroll-behavior:smooth}body{margin:0;color:var(--ink);background:var(--bg);font:15px/1.65 -apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif}
main{max-width:1480px;margin:auto;padding:28px 24px 70px}h1{font-size:32px;line-height:1.3;margin:8px 0 14px}h2{font-size:24px;margin:0 0 14px}h3{font-size:18px;margin:0 0 10px}h4{font-size:15px;margin:4px 0 8px}p{margin:8px 0 12px}a{color:#126b66}code{font-size:12px;overflow-wrap:anywhere}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#f4f7f4;padding:12px;border:1px solid var(--line);border-radius:8px;font:13px/1.6 ui-monospace,SFMono-Regular,monospace;margin:8px 0}
.eyebrow{color:var(--accent);letter-spacing:.12em;font-size:12px;font-weight:700}.muted{color:var(--muted);font-size:13px}.lead{max-width:1040px;font-size:17px}.panel,.case{background:white;border:1px solid var(--line);border-radius:14px;padding:24px;margin:22px 0}.banner{background:#e9f3eb;border-left:4px solid var(--accent);padding:13px 18px;border-radius:6px}.warning{background:#fff6e5;border-left:4px solid #c38d2b;padding:12px 16px;border-radius:6px}.badge{display:inline-block;padding:3px 10px;border-radius:20px;background:#edf2ee;font-size:12px;font-weight:650}.badge.parent{color:#8a4d0a;background:#fff0d4}.badge.children{color:#16644a;background:#e5f3eb}.badge.evidence{color:#5c5a8a;background:#efedfa}
.stats{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin:22px 0}.stat{background:#fff;border:1px solid var(--line);border-radius:12px;padding:16px}.stat b{display:block;font-size:26px;line-height:1.4}.stat span{color:var(--muted);font-size:13px}nav{display:flex;gap:20px;flex-wrap:wrap;padding:12px 0}.grid2{display:grid;grid-template-columns:1fr 1fr;gap:20px}.logic-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:16px}.logic-box{padding:18px;border:1px solid var(--line);border-radius:10px}.diagram{display:flex;align-items:stretch;gap:10px;flex-wrap:wrap;margin:18px 0}.node{background:#ecf3ed;border:1px solid #bfd4c3;border-radius:8px;padding:12px 16px;flex:1;min-width:180px}.arrow{align-self:center;color:var(--accent);font-size:22px}
table{border-collapse:collapse;width:100%;font-size:14px;margin:12px 0}th,td{border:1px solid var(--line);padding:9px 12px;text-align:left;vertical-align:top}th{background:#f1f6f1}.table-scroll{overflow-x:auto}.num{font-variant-numeric:tabular-nums;white-space:nowrap}.toolbar{display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin:16px 0;position:sticky;top:0;z-index:20;background:#f3f6f2ed;padding:10px 0;backdrop-filter:blur(8px)}button,input{font:inherit;border:1px solid #c7d6cb;border-radius:7px;padding:8px 12px;background:white;color:var(--ink)}button{cursor:pointer}button.active{background:var(--accent);color:white;border-color:var(--accent)}input{flex:1;min-width:180px}button:hover{border-color:var(--accent)}.case[hidden]{display:none}.case{scroll-margin-top:75px}.case-head{display:flex;justify-content:space-between;gap:14px;flex-wrap:wrap}.case h2{font-size:21px;margin:5px 0}.reason{margin:14px 0;padding:12px 16px;background:#f4f7f2;border-radius:8px}.source-layout{display:grid;grid-template-columns:minmax(210px,.65fr) minmax(0,1.6fr);gap:20px}.page-img{display:block;width:100%;max-height:440px;object-fit:contain;border:1px solid var(--line);background:#fafbf8}.parent-image{position:relative;line-height:0;width:100%;border:1px solid #b9cabd;background:#f8faf6}.parent-image img{width:100%;height:auto;display:block}.parent-image svg{position:absolute;inset:0;width:100%;height:100%;pointer-events:none}.parent-image.hide-boxes svg{display:none}.parent-caption{font-size:13px;padding:8px 12px;background:#f6f8f5;border:1px solid var(--line);white-space:pre-wrap;line-height:1.5}.source-label{font-size:12px;color:var(--muted);margin:6px 0}.empty{color:#8d6219;background:#fff9ec;border:1px dashed #dbbd80;padding:12px;border-radius:8px}.children-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(285px,100%),1fr));gap:14px;margin:14px 0}.crop{border:1px solid var(--line);border-radius:10px;padding:12px;min-width:0}.crop img{width:100%;height:165px;object-fit:contain;background:#fafbf7}.crop pre{max-height:330px;overflow:auto}.payload{overflow:auto;font-size:14px}.payload table{font-size:13px}.payload p{white-space:pre-wrap}.payload pre{max-height:350px;overflow:auto}.variants{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(280px,100%),1fr));gap:14px}.variant{padding:14px;border:1px solid var(--line);border-radius:10px;min-width:0}.variant .block{border-top:1px solid var(--line);padding:12px 0}.variant .block:first-of-type{border-top:0}.variant h4{font-size:14px}.variant .muted{font-size:11px}.variant pre{max-height:300px;overflow:auto}.raw-code ol{margin:0;padding-left:4em;max-height:430px;overflow:auto;background:#f4f7f4;font:12px/1.6 ui-monospace,SFMono-Regular,monospace}.raw-code li{white-space:pre-wrap;overflow-wrap:anywhere;padding:0 12px}.raw-code li::marker{color:#819388}.raw-code{border:1px solid var(--line);border-radius:8px;overflow:hidden}details{margin:12px 0}summary{cursor:pointer;color:#175c46;font-weight:650;padding:5px 0}.step{padding:14px 0;border-top:1px solid var(--line)}.step:first-child{border-top:0}.hidden{display:none}.footer{border-top:1px solid var(--line);margin-top:30px;padding-top:18px;color:var(--muted);font-size:13px}
@media(max-width:900px){main{padding:18px 12px}.panel,.case{padding:16px}.stats{grid-template-columns:1fr 1fr}.logic-grid,.grid2,.source-layout{grid-template-columns:1fr}.page-img{max-height:300px}h1{font-size:26px}.variants{grid-template-columns:1fr}.parent-image img{max-height:none}}
@media print{.toolbar,nav,button{display:none}.case{break-inside:avoid}.case[hidden]{display:block}details>*{display:block}main{max-width:none}body{background:white}}
"""


def read(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def spans(block: dict):
    for line in block.get("lines") or []:
        yield from line.get("spans") or []
    for child in block.get("blocks") or []:
        yield from spans(child)


def span_text(span: dict) -> str:
    return str(span.get("content") or span.get("text") or span.get("html") or "")


def body_content(block: dict) -> str:
    return "\n\n".join(
        text for child in block.get("blocks") or []
        if child.get("type", "").endswith("_body")
        for span in spans(child) if (text := span_text(span)).strip()
    )


def coverage(inner: list, outer: list) -> float:
    overlap = max(0, min(inner[2], outer[2]) - max(inner[0], outer[0])) * max(
        0, min(inner[3], outer[3]) - max(inner[1], outer[1])
    )
    area = (inner[2] - inner[0]) * (inner[3] - inner[1])
    return overlap / area if area else 0


def pick_visuals(page: dict, region: list) -> list:
    return [
        b for b in page.get("blocks", []) if b.get("type") in {"image", "seal", "chart"}
        and b.get("bbox") and (_iou(region, b["bbox"]) >= 0.05 or coverage(b["bbox"], region) > 0.5)
    ]


def render_pdf(pdf: Path, page_number: int, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    with pdfium.PdfDocument(str(pdf)) as document:
        page = document[page_number - 1]
        bitmap = page.render(scale=2)
        image = bitmap.to_pil()
        image.save(output)
        image.close()
        bitmap.close()
        page.close()


def source_excerpt(output: Path, key: str, label: str, text: str, symbol: str | None = None,
                   start: int | None = None, stop: int | None = None) -> tuple[str, dict]:
    lines = text.splitlines()
    if symbol:
        matches = [n for n in ast.walk(ast.parse(text))
                   if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == symbol]
        if len(matches) != 1:
            raise ValueError(f"Ambiguous source symbol: {symbol}")
        start, stop = matches[0].lineno, matches[0].end_lineno
    if start is None or stop is None:
        raise ValueError(label)
    dest = output / "sources" / f"{key}.txt"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(text, encoding="utf-8")
    body = "".join(f"<li>{escape(line) or ' '}</li>" for line in lines[start - 1:stop])
    fragment = (
        f'<details><summary>{escape(label)} · {start}–{stop} 行</summary>'
        f'<p class="muted"><a href="sources/{key}.txt" target="_blank">查看完整原文件</a></p>'
        f'<div class="raw-code"><ol start="{start}">{body}</ol></div></details>'
    )
    return fragment, {"file": str(dest.relative_to(output)), "sha256": sha(dest),
                      "symbol": symbol, "line_start": start, "line_end": stop, "label": label}


def build(args) -> None:
    root = args.root.resolve()
    pack = root / "archives/129-subimage-inference-full-20261123"
    review = pack / "review"
    replay = root / "artifacts/legacy129-subimage-20261123/p2t-split-policy"
    gt_dir = root / "artifacts/legacy-features-20261119"
    output = args.output.resolve()
    if output.exists() and any(output.iterdir()):
        raise ValueError(f"Output must be empty: {output}")
    output.mkdir(parents=True, exist_ok=True)
    if sha(gt_dir / "records.json") != EXPECTED_RECORDS_SHA:
        raise ValueError("Frozen v3 records SHA-256 changed")
    rows = read(review / "analysis.json")
    grouped = defaultdict(list)
    for row in rows:
        grouped[(row["gt_document_id"], row["page"], row["parent_index"])].append(row)
    if set(grouped) != set(NOTES) or len(rows) != 27:
        raise ValueError("Expected exactly the existing 10 parents / 27 children")
    records = {r["document_id"]: r for r in read(gt_dir / "records.json")["records"]}
    pilot = read(gt_dir / "rubric-pilot-gt.json")
    comparisons = read(replay / "split-comparison.json")
    markdown = MarkdownIt("commonmark", {"html": False}).enable("table")
    raw_docs, ir_docs, rendered_pages = {}, {}, set()
    cases, sections = [], []

    def payload(text: str) -> str:
        if not text.strip():
            return '<div class="empty">【空输出】生成内容为空。</div>'
        rendered = markdown.render(text)
        return f'<div class="payload">{rendered}</div><details><summary>输出原文</summary><pre>{escape(text)}</pre></details>'

    ordered_keys = sorted(grouped, key=lambda k: (NOTES[k]["unit"] != "parent", k))
    for number, key in enumerate(ordered_keys, start=1):
        document_id, page_number, parent_index = key
        note, children = NOTES[key], sorted(grouped[key], key=lambda r: r["sub_index"])
        row, source_name = children[0], children[0]["document"]
        case_id = f"{document_id}-p{page_number}-i{parent_index}"
        if document_id not in raw_docs:
            raw_docs[document_id] = read(pack / "ft/raw-B-original" / f"{source_name}.json")
        raw = raw_docs[document_id]
        raw_page = next(p for p in extract_pdf_info(raw) if p["page_idx"] == page_number - 1)
        parent = next(b for b in raw_page["para_blocks"] if b.get("index") == parent_index)
        if parent["bbox"] != row["parent_bbox"] or len(parent["sub_images"]) != len(children):
            raise ValueError(f"Parent identity drift: {key}")
        region = row["parent_norm_bbox"]
        reference = [b for b in records[document_id]["new_gt"]["image_blocks"]
                     + records[document_id]["new_gt"]["chart_blocks"]
                     if b["page"] == page_number and coverage(b["bbox"], region) >= .5]
        pilot_cases = [c for c in pilot["cases"] if c.get("source_id") in {r["id"] for r in reference}
                       and c["document_id"] == document_id and c["page"] == page_number and not c.get("protected")]
        stem = f"{document_id}-p{page_number}"
        page_asset = f"pages/{stem}.png"
        if stem not in rendered_pages:
            render_pdf(root / "data/legacy/dataset/pdf/source" / f"{source_name}.pdf", page_number,
                       output / page_asset)
            rendered_pages.add(stem)
        encoded = next(iter(raw["results"].values()))["images"][row["composite_key"]]
        parent_bytes = base64.b64decode(encoded.split(",", 1)[1] if encoded.startswith("data:") else encoded)
        parent_asset = f"inputs/parents/{case_id}.jpg"
        (output / parent_asset).parent.mkdir(parents=True, exist_ok=True)
        (output / parent_asset).write_bytes(parent_bytes)
        native_box_elements = []
        for i, sub in enumerate(parent["sub_images"], start=1):
            x0, y0, x1, y1 = sub["bbox"]
            native_box_elements.append(
                f'<rect x="{x0*1000:.2f}" y="{y0*1000:.2f}" width="{(x1-x0)*1000:.2f}" '
                f'height="{(y1-y0)*1000:.2f}" fill="none" stroke="#f19016" stroke-width="4"/>'
                f'<rect x="{x0*1000:.2f}" y="{y0*1000:.2f}" width="55" height="40" fill="#fff2d9"/>'
                f'<text x="{x0*1000+5:.2f}" y="{y0*1000+30:.2f}" font-size="30" fill="#7d4100">S{i}</text>'
            )
        parent_caption = "\n".join(span_text(s) for c in parent.get("blocks", [])
                                   if c.get("type", "").endswith(("_caption", "_footnote")) for s in spans(c))
        crop_cards, child_rows = [], []
        for child in children:
            source_crop, source_response = review / child["crop_path"], review / child["analysis"]["response"]
            if sha(source_crop) != child["crop_sha256"]:
                raise ValueError(f"Crop bytes changed: {source_crop}")
            crop_asset = f"inputs/children/{case_id}-s{child['sub_index']+1}.jpg"
            response_asset = f"responses/{case_id}-s{child['sub_index']+1}.json"
            for source, dest in ((source_crop, output / crop_asset), (source_response, output / response_asset)):
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, dest)
            a = child["analysis"]
            text = a.get("description") or a.get("text_content") or ""
            label = f"{a.get('visual_type') or a['result_kind']} / {a.get('visual_sub_type') or '无 subtype'}"
            crop_cards.append(
                f'<section class="crop"><h4>S{child["sub_index"]+1} · {escape(label)}</h4>'
                f'<a href="{crop_asset}" target="_blank"><img src="{crop_asset}" loading="lazy" alt="{case_id} 子图 {child["sub_index"]+1}"></a>'
                f'<p class="muted">原包实际请求：crop → /file_parse → 再布局。<a href="{response_asset}" target="_blank">真实结构回包</a></p>'
                f'{payload(text)}</section>'
            )
            child_rows.append({
                "sub_index": child["sub_index"], "input": crop_asset, "input_sha256": sha(source_crop),
                "bbox_relative_to_parent": child["sub_bbox_rel"], "page_bbox": child["norm_bbox"],
                "response": response_asset, "response_sha256": sha(source_response),
                "result_kind": a["result_kind"], "type": a.get("visual_type"),
                "sub_type": a.get("visual_sub_type"), "content": text,
                "inference_route": "crop_as_page_file_parse", "fixed_region_analysis_collected": False,
            })
        gt_lines, gt_counts = [], []
        for ref in reference:
            child_ious = [_iou(ref["bbox"], c["norm_bbox"]) for c in children]
            gt_counts.append({"source_id": ref["id"], "type": ref["type"], "bbox": ref["bbox"],
                              "parent_iou": _iou(ref["bbox"], region), "child_ious": child_ious})
            gt_lines.append(
                f'<tr><td><code>{escape(ref["id"])}</code><br>{ref["type"]}</td>'
                f'<td>{_iou(ref["bbox"], region):.3f}</td>'
                f'<td>{" / ".join(f"{v:.3f}" for v in child_ious)}</td></tr>'
            )
        gt_detail = []
        for c in pilot_cases:
            if c["feature"] == "chart":
                gt_detail.append(f'<h4>{escape(c["source_id"])} · 明示值 GT</h4>'
                                 f'<pre>{escape(json.dumps(c.get("values", []),ensure_ascii=False,indent=2))}</pre>')
            else:
                gt_detail.append(f'<h4>{escape(c["source_id"])} · {escape(c.get("sub_type", ""))}</h4>'
                                 f'<pre>{escape(json.dumps(c.get("fields", []),ensure_ascii=False,indent=2))}</pre>'
                                 f'<p>{escape(c.get("scope_note", ""))}</p>')
        variant_html, variant_data = [], {}
        for variant, label in VARIANTS.items():
            doc_key = (variant, document_id)
            if doc_key not in ir_docs:
                ir_docs[doc_key] = read(replay / variant / "chart/documents" / f"{document_id}.json")
            page = next(p for p in ir_docs[doc_key]["pages"] if p["number"] == page_number)
            blocks = pick_visuals(page, region)
            block_fragments, block_data = [], []
            for block in blocks:
                meta = block["metadata"]
                text = block.get("html") or "\n\n".join(span_text(s) for s in meta.get("generated_spans", []))
                caption = "\n".join(b["text"] for b in meta.get("nested_blocks", [])
                                    if b["type"].endswith(("_caption", "_footnote")) and b.get("text"))
                caption_html = f'<p class="muted">印刷图注：</p><pre>{escape(caption)}</pre>' if caption else ""
                block_fragments.append(
                    f'<div class="block"><span class="badge">{block["type"]} / {escape(meta.get("sub_type") or "无标签")}</span>'
                    f'<p class="muted"><code>{escape(block["id"])}</code></p>{payload(text)}'
                    f'{caption_html}</div>'
                )
                block_data.append({"id": block["id"], "type": block["type"], "sub_type": meta.get("sub_type"),
                                   "bbox": block["bbox"], "content": text, "printed_caption": caption})
            variant_data[variant] = block_data
            variant_html.append(f'<section class="variant"><h4>{label}</h4>'
                                + ("".join(block_fragments) or '<div class="empty">【无可归属输出块】</div>')
                                + '</section>')
        case = {
            "id": case_id, "document_id": document_id, "source_pdf": f"{source_name}.pdf", "page": page_number,
            "source_pdf_sha256": sha(root / "data/legacy/dataset/pdf/source" / f"{source_name}.pdf"),
            "source_raw_response_sha256": sha(pack / "ft/raw-B-original" / f"{source_name}.json"),
            "parent_index": parent_index, "block_position": row["block_position"],
            "recommendation_status": "review_candidate_not_production_policy", "analysis_unit": note["unit"],
            "parent_input": parent_asset, "parent_input_sha256": hashlib.sha256(parent_bytes).hexdigest(),
            "page_bbox": region, "source_image_key": row["composite_key"],
            "upstream_parent_content": body_content(parent), "upstream_parent_sub_type": parent.get("sub_type"),
            "parent_analysis_evidence": "not_collected", "children": child_rows,
            "reason": note["reason"], "all_split_consequence": note["all_split"], "evidence_gap": note["gap"],
            "gt_location_diagnostic": gt_counts, "calibration_gt_cases": pilot_cases,
            "replay_variants": variant_data,
        }
        cases.append(case)
        write(output / "cases" / f"{case_id}.json", case)
        unit_label = "建议补整父图 · 未采到响应" if note["unit"] == "parent" else f"建议按子图读取 · 已有 {len(children)} 份响应"
        sections.append(f'''
<article class="case" id="{case_id}" data-unit="{note['unit']}" data-search="{escape(source_name+' '+note['title']+' '+document_id)}">
<div class="case-head"><div><div class="eyebrow">CASE {number:02d} / {document_id} · 物理第 {page_number} 页 · parent index {parent_index}</div>
<h2>{escape(note['title'])}</h2><p class="muted">{escape(source_name)}.pdf · 原包位置 b{row['block_position']:02d} · {len(children)} 个 sub_images</p></div>
<div><span class="badge {note['unit']}">{unit_label}</span><br><a class="muted" href="cases/{case_id}.json">逐案证据 JSON</a></div></div>
<p class="reason">{escape(note['reason'])}</p>
<div class="source-layout"><div><h3>原 PDF 页</h3><a href="{page_asset}" target="_blank"><img class="page-img" src="{page_asset}" loading="lazy" alt="{escape(source_name)} 第 {page_number} 页原 PDF 渲染"></a><p class="source-label">点击查看原分辨率。原页是真值，Origin 仅作对照。</p></div>
<div><h3>FT 原始父图资产与原生子框</h3><div class="parent-image"><img src="{parent_asset}" loading="lazy" alt="FT 原始父图 {case_id}"><svg viewBox="0 0 1000 1000" preserveAspectRatio="none" aria-label="原生子框">{''.join(native_box_elements)}</svg></div>
<p class="source-label">橙框 S1… 是 MinerU 原生 sub_images。<a href="{parent_asset}" target="_blank">查看／下载父图输入</a> · <button class="boxes-toggle" type="button">显示／隐藏子框</button></p>
<div class="parent-caption">印刷图注（原父块携带）：\n{escape(parent_caption or '【父块未携带图注；以原页可见文字核对归属】')}</div>
<div class="empty">父图首轮生成内容：【空输出】；subtype：{escape(parent.get('sub_type') or '无标签')}。独立整父图分析响应：【未采到】，不能把子图回答当作整图回答。</div></div></div>
<div class="grid2"><div><h3>如果全部拆成子图交付</h3><p>{escape(note['all_split'])}</p></div><div><h3>目前评分可用性</h3><p>{escape(note['gap'])}</p></div></div>
<details><summary>当前 v3 源框与校准 GT · IoU 仅作定位诊断</summary><div class="table-scroll"><table><thead><tr><th>源块</th><th>父框 IoU</th><th>各子框 IoU（S1…）</th></tr></thead><tbody>{''.join(gt_lines)}</tbody></table></div><p class="muted">同页 IoU≥0.5 的一对一匹配来自历史定位诊断；不表示内容正确。GT 只用来审阅结果，不进入线上拆保决策。</p>{''.join(gt_detail) or '<p>本组尚无冻结内容／subtype 校准 GT；保留待审，不以 Origin 补真值。</p>'}</details>
<details open><summary>已有子图输入与 FT 真实响应 · {len(children)} 份</summary><div class="children-grid">{''.join(crop_cards)}</div></details>
<details><summary>首轮／原包／全拆／历史候选／Origin · 双开回放输出对照</summary><p class="muted">均来自已保存的 chart 组（image=true, chart=true）；历史回放 relevel_applied=false。历史前置候选保留父图时跳过分析，不能当作新方案完整能力。</p><div class="variants">{''.join(variant_html)}</div></details>
</article>''')

    source_specs = []
    sources_html = []
    utils = args.utils / "mineru_vl_utils/mineru_client.py"
    native = args.mineru / "mineru/utils/visual_magic_model_utils.py"
    zip_path = args.p2t_zip
    with zipfile.ZipFile(zip_path) as archive:
        clean_client = archive.read("src/pdf2text/core/parse/mineru_client.py").decode("utf-8")
    excerpt_inputs = [
        ("native_prepare", "原生 utils 1.0.5：选取抽取区域", utils.read_text(), "prepare_for_extract"),
        ("native_two_step", "原生 utils 1.0.5：先布局再抽取", utils.read_text(), "two_step_extract"),
        ("native_absorb", "MinerU 3.3.1：吸收子块，只保留 type/bbox", native.read_text(), "absorb_image_block_members"),
        ("native_fixed_layout", "原生 utils：固定区域抽取，保留类型与 subtype", utils.read_text(), "extract_with_layout"),
        ("native_content", "原生 utils：content_extract 只返回字符串", utils.read_text(), "content_extract"),
        ("original_p2t", "原 ZIP 8b747ca：请求→过滤→渲染，无子图补偿", clean_client, "parse_pdf_with_filters"),
        ("original_p2t_request", "原 ZIP 8b747ca：middle_json 请求参数与上游调用", clean_client, "_call_mineru_sync_middle_json"),
        ("package_analysis", "原包：子裁图上传 /file_parse 再推理", (review / "scripts/run_subimage_analysis.py").read_text(), "request_analysis"),
        ("package_expand", "原包：重推后按 50% 文字／空结果决定拆保", (review / "scripts/build_expanded_raw.py").read_text(), "expand_page"),
        ("historical_candidate", "历史 P2T 候选：共图注／网格的前置拆保", (root / "archives/pdf2text-develop-1.6.0-8b747ca-20261123/src/pdf2text/core/parse/mineru_subimages.py").read_text(), "_split_rule"),
    ]
    for key, label, text, symbol in excerpt_inputs:
        fragment, metadata = source_excerpt(output, key, label, text, symbol=symbol)
        sources_html.append(fragment)
        source_specs.append(metadata)
    render_pdf(root / "data/legacy/dataset/pdf/source/珠海机场_工作证管理细则_9.pdf", 1,
               output / "pages/bc_108-p1.png")
    flowchart_html, flowchart_audit = audit_flowchart(root, output, pilot, args.legacy_origin)
    totals = {"parents": len(cases), "children": len(rows),
              "parent_analysis_units_missing": sum(c["analysis_unit"] == "parent" for c in cases),
              "child_analysis_groups": sum(c["analysis_unit"] == "children" for c in cases),
              "reusable_child_responses": sum(len(c["children"]) for c in cases if c["analysis_unit"] == "children")}
    assert totals == {"parents": 10, "children": 27, "parent_analysis_units_missing": 4,
                      "child_analysis_groups": 6, "reusable_child_responses": 14}
    manifest = {
        "schema_version": "doc-parse-bench.analysis-units-review.v1", "created_date": "2026-11-24",
        "scope": "legacy129 existing 10 composite parents / 27 saved child responses",
        "policy_status": "review_candidate_not_frozen", "new_model_calls": 0,
        "engineering_reference": {"mineru": "3.3.1", "mineru_vl_utils": "1.0.5"},
        "capture_reported_version": "3.1.14", "records_sha256": EXPECTED_RECORDS_SHA,
        "pilot_gt_sha256": sha(gt_dir / "rubric-pilot-gt.json"),
        "configuration": {"provider": "mineru3", "relevel_titles": True, "title_rules": False},
        "historical_replay_relevel_applied": False, "totals": totals,
        "sources": source_specs, "cases": cases, "additional_calibration_flowchart": flowchart_audit,
    }
    write(output / "manifest.json", manifest)
    planned = []
    for c in cases:
        units = [{"id": f"{c['id']}-parent", "input": c["parent_input"], "input_sha256": c["parent_input_sha256"],
                  "kind": "parent", "existing_response": None}] if c["analysis_unit"] == "parent" else [
            {"id": f"{c['id']}-s{s['sub_index']+1}", "input": s["input"], "input_sha256": s["input_sha256"],
             "kind": "child", "existing_response": s["response"], "existing_route": s["inference_route"]}
            for s in c["children"]
        ]
        planned.append({"case_id": c["id"], "source_pdf": c["source_pdf"], "page": c["page"],
                        "parent_index": c["parent_index"], "analysis_unit": c["analysis_unit"], "units": units})
    write(output / "analysis-plan.json", {
        "status": "for_review_not_authorized_inference", "models": ["3.1-ft", "3.1-origin"],
        "engineering_reference": {"mineru": "3.3.1", "mineru_vl_utils": "1.0.5"},
        "target_config": {"mineru_provider": "mineru3", "backend": "vlm-vllm-async-engine",
                          "relevel_titles": True, "title_rules": False},
        "strategy": "choose parent or children; do not run both by default",
        "cases": planned, "chart_only_candidate_policy": "pending_review",
        "note": "Existing child responses used /file_parse with re-layout. A fixed-region route changes inputs; compare separately.",
    })
    metric_rows = []
    for variant, title in list(VARIANTS.items())[:4]:
        metrics = comparisons[variant]["metrics"]
        im, ch = metrics["image"]["counts"], metrics["chart"]["counts"]
        chart_metric = read(replay / "rubric-charts/all-pilot-charts" / variant / "metrics.json")["features"]["chart"]
        run = comparisons[variant]["groups"]["chart"]
        metric_rows.append(f'<tr><td>{title}</td><td class="num">{run["crop_requests"]}</td>'
                           f'<td class="num">{im["matched"]}/{im["gt"]}</td>'
                           f'<td class="num">{im["matched"]}/{im["predicted"]}</td>'
                           f'<td class="num">{im["content_output"]}/{im["gt"]}</td>'
                           f'<td class="num">{ch["matched"]}/{ch["gt"]}</td>'
                           f'<td class="num">{chart_metric["score"]:.2f}</td></tr>')
    nav_cases = "".join(f'<tr><td><a href="#{c["id"]}">{escape(NOTES[(c["document_id"],c["page"],c["parent_index"])]["title"])}</a>'
                        f'<br><span class="muted">{escape(c["source_pdf"])} · p{c["page"]}</span></td>'
                        f'<td><span class="badge {c["analysis_unit"]}">{"整父图（待补）" if c["analysis_unit"]=="parent" else "子图（已有响应）"}</span></td>'
                        f'<td>{len(c["children"])}</td><td>{"未采到整图响应" if c["analysis_unit"]=="parent" else "可复用历史子图响应"}</td></tr>'
                        for c in cases)
    html = f'''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>129 专项 · 父图与子图分析审阅</title><style>{STYLE}</style></head><body><main>
<div class="eyebrow">LEGACY 129 · MINERU 3.3.1 / UTILS 1.0.5 · 2026-11-24</div>
<h1>哪些应读整张父图，哪些应读子图？</h1>
<p class="lead">把 10 个复合框、27 份真实子图响应和三层原代码摆在一起。审阅建议是：4 个父框补整图，6 个父框按 14 张子图读取；尚未采到的整图响应明确留空。</p>
<div class="banner"><b>本页是待确认的分析单位建议。</b>未运行新推理、未修改 GT、未冻结线上拆保规则。工程适配按用户确定的 MinerU 3.3.1 逻辑推进；历史采集回包仍报告 3.1.14。Origin 只是对照。</div>
<nav><a href="#roster">case 清单</a><a href="#all-split">全部按拆分会怎样</a><a href="#logic">原来的代码逻辑</a><a href="#cases">逐案原图与输出</a><a href="#flowchart-content">流程关系核对</a><a href="#next">评测与适配怎么推进</a><a href="analysis-plan.json">分析输入清单 JSON</a></nav>
<div class="stats"><div class="stat"><b>4</b><span>建议补整父图 · 当前缺响应</span></div><div class="stat"><b>6 / 14</b><span>建议按子图读 · 6 父框 / 14 子图</span></div><div class="stat"><b>27 / 27</b><span>全部子裁图输入和真实响应齐全</span></div><div class="stat"><b>0</b><span>本次新增模型请求</span></div></div>
<section class="panel" id="roster"><h2>先看分析单位清单</h2><p>建议按源图的整体语义选择读取单位。表中的 case 审阅标记用于核对方案，不能将这些 ID／文件名写入线上规则。</p>
<div class="table-scroll"><table><thead><tr><th>原页／组图</th><th>建议读取</th><th>原生子框</th><th>已有证据</th></tr></thead><tbody>{nav_cases}</tbody></table></div></section>
<section class="panel" id="all-split"><h2>“全部按拆分读”有两种落地含义</h2><div class="grid2"><div class="logic-box"><h3>全部子图都分析，父图仍可保留</h3><p>原包已经做了 27 次子裁图请求。它按分析结果决定拆保：9 个父框被拆、Fig. 6 保留。保留时 7 份响应未使用。</p><p>若改成保留父图、附挂各子图内容，可以保护交付框；但子图标签不能替父图判类，局部内容也不能证明跨子图关系完整。</p></div><div class="logic-box"><h3>全部子图分析，并全部替换父图</h3><p>已有“FT 全拆”回放：双柱图和独立照片获益；两组线路图被拆半，Fig. 6 变 7 个碎片，Fig. 1 父图级 subtype 仍缺证据。</p><p>它不需要前置拆保判断，适合作为补偿对照；当前结果不足以支持它直接作为最终交付策略。</p></div></div>
<div class="table-scroll"><table><thead><tr><th>129 篇历史方案</th><th>子图分析单位数</th><th>图片／印章定位</th><th>定位命中／预测</th><th>定位且非空</th><th>图表定位</th><th>局部图表 F1</th></tr></thead><tbody>{''.join(metric_rows)}</tbody></table></div>
<p class="muted">当前 v3：118 图片／印章、73 图表。局部图表 F1 仅 11 张、78 个明示值；表格数据来自已有双开回放，未重跑线上标题重排或 chart-only。请求数表示分析输入数，不是 GPU 内部推理调用数或线上耗时。</p>
<div class="warning"><b>全拆的核心限制：</b>定位命中增加不等于 subtype／内容正确。消防两图仍为错误 text_image，维修照片 OCR 回退仍无 subtype。反过来，半框 IoU 失配是交付粒度问题，也不能直接说模型没读到内容。</div></section>
<section class="panel" id="logic"><h2>原来的代码到底怎样做</h2>
<div class="logic-grid"><div class="logic-box"><span class="badge">原生 MinerU 3.3.1</span><h3>布局 → 区域分析 → 分组</h3><pre>layout_detect(整页)\nprepare_for_extract(layout)\n  独立 image/chart → Image Analysis\n  image_block → skip\n  其覆盖 image/chart → skip\npost_process(实际内容)\nregroup → 父 image + sub_images</pre><p>sub_images 是布局元数据，包含 type/bbox。保留父资产不会自动触发父图分析。</p></div>
<div class="logic-box"><span class="badge">原始 P2T 8b747ca</span><h3>取结构 → 过滤 → 渲染</h3><pre>上传 PDF\nreturn_middle_json=true\nreturn_images=true\n上游 image_analysis =\n  图片开 || 图表开 || seal_rec\n→ apply_filters(各自开关)\n→ union_make Markdown\n→ 嵌入图片，返回 md/pages</pre><p>原 ZIP 没有 sub_images 补分析／拆保模块。两分析开关都关时继续原路径；印章等已有参数语义照旧。</p></div>
<div class="logic-box"><span class="badge">压缩包补偿代码</span><h3>先全读子图，再决定交付</h3><pre>27 张子图 → 各自 /file_parse\n→ 再布局 + 分析\ntext_only/empty 比例 ≥ 50%\n  → 保留父图，丢弃子图结果\n否则 → 拆分，回填实际子图结果\n原图注只挂一次</pre><p>结果拆 9、保留 1。它保住 Fig. 6，却拆掉两组共图注线路图。</p></div></div>
<details><summary>历史前置候选为何请求少，为什么还没定稿</summary><pre>网格 keep_multirow → 直接跳过\n共图注 keep_shared_caption → 直接跳过\n图片开启、无共图注且成排 → 裁子图\n图表开启、图注列(a)/(b)或子框均 chart → 探测子图\n仅各子图均有不同可解析表才允许探测后拆</pre><p>历史候选图片单开 12 张、双开 16 张；保留父图直接跳过，造成完整能力证据缺失。每篇 8 张／4 秒是未经线上验证的历史候选预算。</p></details>
<h3>3.3.1 体系已有固定区域抽取能力</h3><p><code>extract_with_layout</code> 可以把选定区域声明为一个 <code>image</code>，跳过再次布局，返回带实际 <code>type/sub_type/content</code> 的结构化结果。使用原生 Image Analysis 提示与后处理即可。普通 <code>content_extract(type="image")</code> 只返回字符串，不能单凭它可靠传回 subtype。</p>
<div class="diagram"><div class="node">首轮布局已知<br>选择一个读取方案</div><div class="arrow">→</div><div class="node">整父图一次<br>或 N 张子图</div><div class="arrow">→</div><div class="node">原生固定区域抽取<br>记录 type/sub_type/content</div><div class="arrow">→</div><div class="node">P2T 过滤与渲染<br>核对最终交付</div></div>
<p class="muted">固定区域是已存在的 Python 能力，原 /file_parse 表单没有外部 layout 参数。真实 P2T 如何访问同一 upstream 的这项能力，需要明确内网接口；不能凭本机函数存在就宣称线上已接通。若只重传父图到 /file_parse，仍可能再次落为 image_block。</p>
<details><summary>展开真实源码片段、行号和原文件</summary>{''.join(sources_html)}</details></section>
<section id="cases"><h2>逐案查看原图、父子框与实际输出</h2><p class="muted">图片、文字、表格均来自现有证据。点击图片可放大；各 case 下方可展开五种历史输出。正文不会将 Origin 当真值。</p></section>
<div class="toolbar"><button class="unit-filter active" data-filter="all" type="button">全部 10</button><button class="unit-filter" data-filter="parent" type="button">补整父图 4</button><button class="unit-filter" data-filter="children" type="button">补子图 6</button><input id="case-search" type="search" aria-label="筛选 case" placeholder="搜索文件名、图号或 bc_ID"><span class="muted" id="case-count">10 个 case</span></div>
{''.join(sections)}
{flowchart_html}
<section class="panel" id="next"><h2>接下来如何推进评测与 P2T 适配</h2>
<div class="step"><h3>1. 先审这 10 个框，分开“分析”和“交付”</h3><p>先确认哪些按父图读、哪些按子图读；允许“子图分析但仍保留父图交付”作为独立对照，但不能用子面板 subtype 代替父图标签。确认后将理由归纳成不读 GT、文件名或 Origin 的通用规则，不硬编码本页 case。</p></div>
<div class="step"><h3>2. 用已有响应评已覆盖项，缺的只列最小补推清单</h3><p>6 个子图组的 14 份响应可复用，另 13 份属于建议保留的 4 个父图组。4 份整图响应目前缺失，输入已导出到 inputs/parents；由用户安排内网推理。若改成固定区域入口，新的子图结果另存为诊断，不能和旧 /file_parse 结果混称同配置。</p></div>
<div class="step"><h3>3. 归一化评分，先把现有校准证据收齐</h3><p>四专项各占 25%。附录 51 页、页眉页脚 14 个校准块、11 张图表的 78 个明示值已有回归分；图片／印章需补齐冻结范围内 subtype、字段、关系与资产证据。消防文字分、subtype 失败与关系未证明分别报告。没有对应响应写 evidence_missing，确认空输出才可按既定范围记 0。</p><p>先形成完整校准分项与 badcase 差距，再冻结正式 evaluation GT 和最终成品证据。四项均可评分才报等权总分，误删独立否决。当前 70.51 仍只是局部图表分。</p></div>
<div class="step"><h3>4. 本机实现与内网验证</h3><p>确定规则后接入 P2T 本次请求，普通图片和图表不额外补推；图片单开／图表单开／双开／双关独立回归，双关对照原 ZIP。保留父图不能自动跳过分析。默认不父子都读，不用 4 秒超时定义模型能力。</p><p>最后从原 ZIP 生成单一补丁、测试、关闭回退说明和内网交接；用户安排真实内网 P2T 的最终 Markdown、标题重排和端到端 p50/p95。离线请求数与回放耗时不替代线上验收。</p></div>
<div class="warning">下一项仍需审的语义：chart-only 如何选择“尚未标为 chart”的复合块。双柱图的原生子框都写 image，若只补 type=chart 会漏掉它；若所有 image 都补推，成本与普通图片泄漏要单独验证。本页不将其中一种设为最终策略。</div>
<p><a href="manifest.json">完整清单与来源哈希</a> · <a href="analysis-plan.json">父图／子图输入计划</a></p></section>
<footer class="footer">由已有 PDF、原始 MinerU 回包、27 份真实裁图响应和历史 P2T 回放构建。HTML 在本地离线打开，不加载外部脚本或图片。工程参考 3.3.1/1.0.5；历史响应版本 3.1.14；目标 relevel_titles=true/title_rules=false，历史回放未执行标题重排。</footer>
</main><script>
let unit='all';const cards=[...document.querySelectorAll('.case')];
function filterCases(){{const q=document.getElementById('case-search').value.trim().toLowerCase();let n=0;for(const card of cards){{card.hidden=!((unit==='all'||card.dataset.unit===unit)&&card.dataset.search.toLowerCase().includes(q));if(!card.hidden)n++;}}document.getElementById('case-count').textContent=n+' 个 case';}}
document.querySelectorAll('.unit-filter').forEach(btn=>btn.addEventListener('click',()=>{{unit=btn.dataset.filter;document.querySelectorAll('.unit-filter').forEach(b=>b.classList.toggle('active',b===btn));filterCases();}}));
document.getElementById('case-search').addEventListener('input',filterCases);
document.querySelectorAll('.boxes-toggle').forEach(btn=>btn.addEventListener('click',()=>btn.closest('.source-layout').querySelector('.parent-image').classList.toggle('hide-boxes')));
document.querySelectorAll('a[href^="#bc_"]').forEach(a=>a.addEventListener('click',()=>{{unit='all';document.getElementById('case-search').value='';document.querySelectorAll('.unit-filter').forEach(b=>b.classList.toggle('active',b.dataset.filter==='all'));filterCases();}}));
</script></body></html>'''
    (output / "review.html").write_text(html, encoding="utf-8")
    (output / "README.md").write_text(
        "# 129 父图／子图分析审阅\n\n打开 `review.html`。本目录内图片、源码摘录、27 份子图响应和清单可离线使用。\n\n"
        "`analysis-plan.json` 是待确认的输入计划，不自动调用模型。4 份父图响应缺失；14 份子图响应可复用。\n"
        "当前推荐针对这 10 个框作审阅，不是线上硬编码规则；没有修改 GT 或跑新模型。\n",
        encoding="utf-8",
    )
    print(json.dumps({"output": str(output / "review.html"), **totals}, ensure_ascii=False))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--mineru", type=Path, default=Path("/Users/yixuan/.cache/uv/archive-v0/s-x4aZ_dPlgGkTri"))
    parser.add_argument("--utils", type=Path, default=Path("/Users/yixuan/.cache/uv/archive-v0/xjsu37LbubHSrRXw"))
    parser.add_argument("--p2t-zip", type=Path,
                        default=Path("/Users/yixuan/Documents/pdf2text_code_develop-1.6.0-8b747ca_20261123.zip"))
    parser.add_argument("--legacy-origin", type=Path,
                        default=Path("/private/tmp/feature-subimage-129.WFF6Bk/origin/ir"))
    build(parser.parse_args())


if __name__ == "__main__":
    main()
