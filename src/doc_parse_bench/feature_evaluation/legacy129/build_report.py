import argparse
import json
import re
from collections import Counter, defaultdict
from dataclasses import replace
from hashlib import sha256 as digest
from html import escape
from pathlib import Path
from zipfile import ZipFile

from bs4 import BeautifulSoup
from markdown_it import MarkdownIt

from ...io import fresh_directory, read_json, sha256, write_json
from ...mineru_middle import pdf_info_to_document
from ..feature_matrix import _match
from ..feature_rubric import CONFIG, EDGE_TYPES, EVIDENCE_SCHEMA, _text, evaluate_feature_rubric
from .score_pilot_charts import chart_observation
from .score_pilot_switches import _anchor_evidence, _margin_observation, _overlaps_reference

ROOT = Path(__file__).resolve().parents[4]
OUTPUT = ROOT / "artifacts/legacy129-evaluation-20261126"
GT = ROOT / "artifacts/legacy-features-20261125/rubric-evaluation-gt.json"
INPUT = GT.with_name("rubric-evaluation-sources.json")
GROUPS = (
    "both_off",
    "appendix_off",
    "header_footer_on",
    "both_on",
    "image_only",
    "chart_only",
    "controls_image_off",
)
MODELS = {"ft": "8009 FT", "origin": "8010 Origin"}
FEATURES = {
    "appendix": "附录",
    "header_footer": "页眉页脚",
    "image": "图片与印章",
    "chart": "图表",
}
PROTECTION_STATUS = {
    "intact": "双侧完整",
    "baseline_incomplete": "双侧内容不全",
    "pair_unverified": "开关对照待核",
    "deletion_on": "开启侧误删",
    "deletion_off": "关闭侧误删",
    "evidence_missing": "待补证据",
}
REVIEWED_CHART_ISSUES = {
    "bc_014:candidate.block.p6.0010": "FT 把 2020 年的 12.5 万件写成了 12.3 万件。",
    "bc_015:candidate.block.p11.0004": "Origin 把印刷页码拼到了 2023 年，数值 28456 正确。",
    "bc_015:candidate.block.p13.0006": "Origin 交换了 2019 年的收入增速 8.0% 与支出增速 7.5%。",
}
MARKDOWN = MarkdownIt("commonmark").enable("table")
IMAGE_DATA = re.compile(r"data:image/[^;]+;base64,[A-Za-z0-9+/=]+")
INLINE_MATH = re.compile(r"(?<!\\)\$([^$\n]+?)(?<!\\)\$")


def anchors(page, case, rendered):
    return [value for value in _anchor_evidence(page, case) if _text(value) in rendered]


def state(page, case, rendered):
    hits = anchors(page, case, rendered)
    if len(hits) == len(case["anchors"]):
        return "complete"
    return "partial" if hits else "missing"


def margin(case, on, off, off_raw, rendered):
    original = {
        (block["index"], tuple(block["bbox"])): block["type"]
        for key in ("preproc_blocks", "discarded_blocks")
        for block in off_raw.get(key, [])
        if block["type"] in EDGE_TYPES and "index" in block
    }
    for block in on.blocks:
        if block.bbox:
            scale = (on.width, on.height, on.width, on.height)
            box = tuple(round(coordinate * extent) for coordinate, extent in zip(block.bbox, scale))
            raw_type = original.get((block.metadata["native_index"], box))
            if raw_type:
                block.metadata["raw_type"] = raw_type
    if case["id"] == "bc_020:p1:margins":
        combined = next(block for block in on.blocks if block.text == "GEOCHEMICAL EXPLORATION")
        references = [
            row
            for row in case["blocks"]
            if row["type"] == "header" and _overlaps_reference(row["bbox"], combined)
        ]
        assert [row["text"] for row in references] == ["AL", "EXPLORATION"]
        observed = _margin_observation(
            case, replace(on, blocks=[block for block in on.blocks if block is not combined]), off
        )
        observed["on_blocks"].extend(
            {"id": f"{combined.id}:{index}", "source_id": row["id"], "text": row["text"]}
            for index, row in enumerate(references, start=1)
        )
        observed["attribution_note"] = (
            "原页核对合并页眉 GEOCHEMICAL EXPLORATION，AL 和 EXPLORATION 对应两个不重叠片段。"
        )
    else:
        observed = _margin_observation(case, on, off)
    assert all(
        row.get("image_available") is not True and _text(row["text"]) in rendered
        for row in observed["on_blocks"]
    ), f"成品中的页眉页脚需复核 {case['id']}"
    return observed


def collect(archive, model, docs, gt_cases, chart_source):
    observations, captures, diagnostics = {}, {}, Counter()
    by_doc = defaultdict(list)
    for case in gt_cases:
        by_doc[case["document_id"]].append(case)
    chart_observations = chart_source["cases"]
    for document in docs:
        doc_id = document["document_id"]
        prefix = f"{model}/documents/{doc_id}"
        manifest = json.loads(archive.read(f"{prefix}/document.json"))
        assert manifest["status"] == "ok"
        for key in ("source_pdf", "pdf_sha256", "appendix_pages", "margin_pages"):
            assert manifest[key] == document[key], (model, doc_id, key)
        assert manifest["source_pages"] == document["pages"]
        pages, final, rendered, raws, metadata = {}, {}, {}, {}, {}
        for group in GROUPS:
            group_path = f"{prefix}/final/{group}"
            meta = json.loads(archive.read(f"{group_path}/meta.json"))
            assert meta["document_id"] == doc_id and meta["variant"] == group
            assert meta["relevel_applied"] and meta["filters"]["title_rules"] is False
            raw = archive.read(f"{group_path}/middle_json.json")
            markdown = archive.read(f"{group_path}/final.md")
            assert digest(raw).hexdigest() == meta["middle_json_sha256"]
            assert digest(markdown).hexdigest() == meta["markdown_sha256"]
            physical_pages = set(range(1, document["pages"] + 1))
            if group == "appendix_off":
                physical_pages.difference_update(document["appendix_pages"])
            raw_pages = {page["page_idx"] + 1: page for page in json.loads(raw)["pdf_info"]}
            assert raw_pages.keys() == physical_pages and meta["pages"] == len(physical_pages)
            metadata[group] = meta
            if group not in {"both_off", "appendix_off", "header_footer_on", "both_on"}:
                continue
            raws[group] = raw_pages
            pages[group] = {
                page.number: page
                for page in pdf_info_to_document(list(raw_pages.values()), document_id=doc_id).pages
            }
            final[group] = IMAGE_DATA.sub("", markdown.decode())
            plaintext = BeautifulSoup(final[group], "html.parser").get_text(" ")
            rendered[group] = _text(INLINE_MATH.sub(r"\1", plaintext))

        baseline = metadata["both_off"]
        capture = baseline["source"]["capture_sha256"]
        captures[doc_id] = {"off": capture}
        for feature, (group, filter_name, toggled) in {
            "appendix": ("appendix_off", "keep_appendix", False),
            "header_footer": ("header_footer_on", "keep_header_footer", True),
        }.items():
            assert baseline["filters"][filter_name] is not toggled
            assert metadata[group]["source"]["base_capture_sha256"] == capture
            assert metadata[group]["filters"] == baseline["filters"] | {filter_name: toggled}
            captures[doc_id][feature] = capture
        diagnostics["documents"] += 1
        diagnostics["appendix_cut_pages"] += len(document["appendix_pages"])

        images = [
            case
            for case in by_doc[doc_id]
            if case["feature"] == "image"
            and not case.get("protected")
            and case["sub_type"] != "other"
        ]
        visual_blocks = [
            (page.number, block)
            for page in pages["both_on"].values()
            for block in page.blocks
            if block.type in {"image", "seal"}
        ]
        diagnostics["image_box_matches"] += len(_match(images, visual_blocks, visual=True))
        for case in by_doc[doc_id]:
            number, case_id, feature = case["page"], case["id"], case["feature"]
            if feature == "appendix":
                on, off = "both_off", "appendix_off"
                if case.get("protected"):
                    observations[case_id] = {
                        f"{side}_state": state(pages[group].get(number), case, rendered[group])
                        for side, group in (("on", on), ("off", off))
                    }
                else:
                    observations[case_id] = {
                        "on_anchors": anchors(pages[on][number], case, rendered[on]),
                        "off_residual": number in pages[off],
                    }
            elif feature == "header_footer":
                on, off = "header_footer_on", "both_off"
                if case.get("protected"):
                    observations[case_id] = {
                        f"{side}_state": state(pages[group].get(number), case, rendered[group])
                        for side, group in (("on", on), ("off", off))
                    }
                else:
                    observations[case_id] = margin(
                        case, pages[on][number], pages[off][number], raws[off][number], rendered[on]
                    )
            elif feature == "chart" and case_id in chart_observations:
                observed = chart_observations[case_id]
                block = next(
                    block
                    for block in pages["both_on"][number].blocks
                    if block.id == observed["block_id"]
                )
                assert block.type == "chart" and _text(observed["payload"]) in _text(
                    final["both_on"]
                )
                assert observed["values"] == chart_observation(block, MARKDOWN)["values"]
                observations[case_id] = observed

    assert len(observations) == 400, (model, len(observations))
    return {
        "schema_version": EVIDENCE_SCHEMA,
        "model": MODELS[model],
        "stage": "final",
        "relevel_applied": True,
        "gt_sha256": sha256(GT),
        "config": CONFIG,
        "cases": observations,
        "captures": captures,
        "chart_source_gt_sha256": chart_source.get(
            "chart_source_gt_sha256", chart_source["gt_sha256"]
        ),
    }, diagnostics


def text_score(score):
    return "待出分" if score is None else f"{score:.2f}"


def table(headings, rows):
    header = "".join(f'<th scope="col">{escape(str(text))}</th>' for text in headings)
    body = "".join(
        "<tr>" + "".join(f"<td>{escape(str(text))}</td>" for text in row) + "</tr>" for row in rows
    )
    return f'<div class="scroll"><table><thead><tr>{header}</tr></thead><tbody>{body}</tbody></table></div>'


def image_review_table(output, per_case, cases):
    evidence = {model: read_json(output / f"{model}-evidence.json")["cases"] for model in MODELS}
    rows = []
    for case in cases:
        if case["feature"] != "image" or case.get("protected") or case["sub_type"] == "other":
            continue
        case_id = case["id"]
        fields = (
            " · ".join(field["text"] for field in case["fields"]) or "核对原图及是否编造图中文字"
        )
        note = f"<p>{escape(fields)}</p>"
        columns = []
        for model in MODELS:
            row = per_case[model][case_id]
            observed = evidence[model][case_id]
            subtype = row.get("subtype")
            category = subtype.get("observed") or "缺少源图类型" if subtype else "按章文计分"
            text = "\n".join(observed.get("raw_content", [])) or "本项缺少可归属的输出内容。"
            diagnostics = []
            for label, key in (("字段", "fields"), ("有向关系", "relations")):
                if row.get(key) is not None:
                    counts = row[key]
                    diagnostics.append(
                        f"{label}命中 {counts['tp']}/{counts['tp'] + counts['fn']}，错报 {counts['fp']}"
                    )
            detail = "<p>" + escape("。".join(diagnostics)) + "</p>" if diagnostics else ""
            attribution = observed.get("attribution_note")
            if attribution:
                detail += f"<p>{escape(attribution)}</p>"
            columns.append(
                f"<td><details><summary>{text_score(row['score'])} · {escape(category)}</summary>"
                f"{detail}<pre>{escape(text)}</pre></details></td>"
            )
        location = f"{case['source_pdf']} · 第 {case['page']} 页"
        rows.append(
            f"<tr><td><details><summary>{escape(location)}</summary>"
            f"<p><code>{escape(case_id)}</code> · {escape(case['sub_type'])}</p>{note}</details></td>"
            f"{''.join(columns)}</tr>"
        )
    return (
        '<div class="scroll"><table><thead><tr><th scope="col">源图和 GT</th>'
        '<th scope="col">8009 FT</th><th scope="col">8010 Origin</th></tr></thead>'
        f"<tbody>{''.join(rows)}</tbody></table></div>"
    )


def html_report(output, archive_path, metrics, diagnostics, cases, *, supplement_path=None):
    by_id = {case["id"]: case for case in cases}
    per_case = {model: read_json(output / model / "per_case.json") for model in MODELS}
    ft, origin = (metrics[model]["features"] for model in MODELS)
    details = {
        "appendix": f"两版均按清单截断 48 页。开启时双方都完整交付 {ft['appendix']['on_complete_pages']}/48 页的全部 GT 锚点。",
        "header_footer": "289 页、800 个 GT 块。按块汇总精确率和召回率后计算 F1。",
        "image": f"89 张图及印章。按源页和框初步定位 {diagnostics['ft']['image_box_matches']}/89 对 {diagnostics['origin']['image_box_matches']}/89。",
        "chart": f"可解析表格均为 47/47。明示值命中 {ft['chart']['matched_values']}/{ft['chart']['denominator']['count']} 对 {origin['chart']['matched_values']}/{origin['chart']['denominator']['count']}。",
    }
    if supplement_path:
        details["image"] = (
            f"仅开图片分析。两版均核验 {ft['image']['scored']}/{ft['image']['planned']} 个计分目标。"
        )
    rows = [
        (
            name,
            text_score(ft[feature]["score"]),
            text_score(origin[feature]["score"]),
            details[feature],
        )
        for feature, name in FEATURES.items()
    ]
    total_basis = "四项各占 25%。" if supplement_path else "图片与印章仍需逐图归属和内容核验。"
    rows.append(
        ("四项等权总分", *(text_score(value["overall"]) for value in metrics.values()), total_basis)
    )
    charts = [case for case in cases if case["feature"] == "chart" and case.get("values")]
    chart_issues = []
    for case in charts:
        case_id = case["id"]
        observations = [per_case[model][case_id] for model in MODELS]
        notes = [REVIEWED_CHART_ISSUES[case_id]] if case_id in REVIEWED_CHART_ISSUES else []
        for label, row in zip(MODELS.values(), observations):
            for match in row["column_matches"]:
                if match["header_conflicts"]:
                    notes.append(
                        f"{label} 的「{match['predicted_series']} {match['predicted_unit']}」"
                        f"对齐到「{match['series']} {match['unit']}」"
                    )
        if not notes and all(
            row["matched_values"] == row["expected_values"] for row in observations
        ):
            continue
        chart_issues.append(
            (
                f"{case['source_pdf']} · 第 {case['page']} 页 · {case_id.rsplit(':', 1)[-1]}",
                *(f"{row['matched_values']}/{row['expected_values']}" for row in observations),
                " ".join(notes) or "明示值有差异",
            )
        )
    appendix_docs = defaultdict(list)
    for case in cases:
        if case["feature"] == "appendix" and not case.get("protected"):
            appendix_docs[case["source_pdf"]].append(case)
    appendix_rows = [
        (
            name,
            len(group),
            *(
                sum(per_case[model][case["id"]]["on_complete"] for case in group)
                for model in MODELS
            ),
        )
        for name, group in appendix_docs.items()
    ]
    margin_rows = [
        (
            MODELS[model],
            *(metrics[model]["features"]["header_footer"][key] for key in ("tp", "fp", "fn")),
        )
        for model in MODELS
    ]
    gate_rows = [
        (
            FEATURES[by_id[key]["feature"]],
            by_id[key]["source_pdf"],
            by_id[key]["page"],
            *(PROTECTION_STATUS[per_case[model][key]["status"]] for model in MODELS),
        )
        for key, row in per_case["ft"].items()
        if row["protected"]
    ]
    intact = sum(row["protected"] and row["status"] == "intact" for row in per_case["ft"].values())
    gate_heading = "保护项"
    protection_note = "图片关闭对照同时关闭了图片与图表分析，图表双开与仅开图片来自独立请求。"
    image_details = ""
    supplement_hash = ""
    if supplement_path:
        group_labels = {
            "text_image": "文字图",
            "flowchart": "流程／线路图",
            "photo_with_text": "有字照片",
            "photo_without_text": "无字照片",
            "seal": "印章",
        }
        image_details = table(
            ("类别", "目标数", "8009 FT", "8010 Origin"),
            [
                (
                    name,
                    ft["image"]["groups"][key]["planned"],
                    text_score(ft["image"]["groups"][key]["score"]),
                    text_score(origin["image"]["groups"][key]["score"]),
                )
                for key, name in group_labels.items()
            ],
        )
        image_details += (
            "<p>两版有字照片组的登记字段均未完整命中。流程／线路图按既定 GT 核对文字和已登记的有向关系。"
            "合框标签按合框记录，子图标签按子图记录。同名分类器依输出分支顺序对齐。"
            "两枚合框印章依输出编号归属各自的章文。</p>"
            f"<details><summary>{ft['image']['scored']} 项逐图评分和实际输出</summary>"
            f"{image_review_table(output, per_case, cases)}</details>"
        )
        gate_heading = "保护项 · 两版均有确认误删"
        protection_note = (
            "同一采集的单开关复核确认，关闭图片分析会清掉 bc_022 第 2 页的 Fig. 1 印刷图注。"
            "两版成品仍交付原图。bc_091 的图表开关两侧均保留原图和印刷图注。"
            "另有 2 项在配对两侧均有内容缺失。"
        )
        supplement_hash = (
            f"<p>{escape(supplement_path.name)} SHA-256 <code>{sha256(supplement_path)}</code></p>"
        )
    links = "".join(
        f'<li><strong>{label}</strong> <a href="{model}/report.md">逐例评分</a> '
        f'<a href="{model}/pending_cases.json">待补证据</a> '
        f'<a href="{model}/per_case.json">评分明细</a> '
        f'<a href="{model}/provenance.json">复算来源</a></li>'
        for model, label in MODELS.items()
    )
    page = f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Legacy 129 四功能评测</title>
<style>
:root {{ color-scheme:light; --border:#dde3ed; --accent:#254b99; }}
body {{ margin:0; font:16px/1.6 -apple-system,BlinkMacSystemFont,sans-serif; background:#f6f8fb; color:#19273f; }}
main {{ max-width:1120px; margin:auto; padding:42px 24px 56px; }}
h1 {{ margin:0; font-size:clamp(26px,4vw,38px); }}
h2 {{ margin:28px 0 8px; font-size:20px; }}
p {{ margin:8px 0 14px; }}
.meta {{ color:#4f6080; }}
.scroll {{ overflow-x:auto; }}
table {{ width:100%; border-collapse:collapse; background:white; font-variant-numeric:tabular-nums; }}
th,td {{ text-align:left; border-bottom:1px solid var(--border); padding:9px 12px; }}
th {{ background:#eaf0fb; }}
details {{ margin-top:12px; border:1px solid var(--border); border-radius:8px; background:white; padding:10px 14px; }}
summary {{ cursor:pointer; font-weight:650; }}
a {{ color:var(--accent); }}
code {{ overflow-wrap:anywhere; }}
li a {{ margin-left:.6em; }}
pre {{ white-space:pre-wrap; overflow-wrap:anywhere; max-width:26rem; }}
td {{ vertical-align:top; }}
.gate {{ background:#fff4e7; padding:10px 14px; border-radius:8px; }}
</style></head>
<body><main>
<h1>Legacy 129 四功能评测</h1>
<p class="meta">8009 FT 与 8010 Origin · 同一组 129 篇 PDF · 11 月 25 日内网 P2T 推理成品</p>
{table(("专项", "8009 FT", "8010 Origin", "证据范围"), rows)}
{('<p class="gate">保护项判定为失败。两版在关闭图片分析时都会丢失 Fig. 1 的印刷图注。</p>' if supplement_path else "")}
<h2>图表掉点</h2>
<p>按年份或类别对齐行，再做整列一对一匹配。百分比值统一全角与半角、可省略百分号，保持原数值。单元格自带百分号时只与百分比明示值配对。表头简称通过数据核对，明确的列名及单位冲突留在明细中。</p>
<p>按原 PDF 复核修正了四张图的 GT。两张第 10 页下图的系列及单位写错，<code>bc_016</code> 第 12 页两图的标注归属有误。修订后仍评 47 张图及 312 个明示值。</p>
<p>风资源图的 10 个占比两版均读对。Origin 把占比列写成了蕴藏量。FT 输出的蕴藏量为估读值，原图只有折线和刻度。</p>
{table(("图表", "FT 命中", "Origin 命中", "复核说明"), chart_issues)}
<h2>逐项复核</h2>
<details><summary>附录页与正文锚点</summary>
{table(("含附录的文档", "关闭态截断页", "FT 开启态完整页", "Origin 开启态完整页"), appendix_rows)}
</details>
<details><summary>页眉页脚命中与错报</summary>
{table(("模型", "TP 命中", "FP 错报", "FN 漏报"), margin_rows)}
<p>开启态恢复了边缘块类型，按页、原块索引和坐标归属，并与最终 Markdown 核对。<code>bc_020</code> 首页合并页眉的两个片段经原页复核。</p>
</details>
<details><summary>图片与印章判分范围</summary>
<p>图片分要求源图归属和实际 subtype，再核对该图登记的文字、关系或原图保留情况。若整张图被当正文 OCR，文字编辑分可能相同。源图归属及类型是该图片专项的计分依据。Claude 系统卡示例在这 129 篇之外。</p>
{image_details}
</details>
<details><summary>{gate_heading} · 两版各 {intact}/{len(gate_rows)} 双侧完整</summary>
<p>{protection_note}</p>
{table(("专项", "文档", "物理页", "8009 FT", "8010 Origin"), gate_rows)}
</details>
<h2>评分证据</h2>
<ul>{links}</ul>
<details><summary>数据指纹</summary>
<p>{escape(archive_path.name)} SHA-256 <code>{sha256(archive_path)}</code></p>
{supplement_hash}
<p>GT SHA-256 <code>{sha256(GT)}</code></p>
</details>
</main></body></html>
"""
    (output / "index.html").write_text(page, encoding="utf-8")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--zip", type=Path, required=True)
    parser.add_argument("--chart-evidence", type=Path, default=OUTPUT)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = fresh_directory(args.output)
    cases = read_json(GT)["cases"]
    docs = read_json(INPUT)["documents"]
    metrics, diagnostics = {}, {}
    with ZipFile(args.zip) as archive:
        for model in MODELS:
            prefix = f"{model}/documents/"
            manifest_ids = {
                name.split("/")[2]
                for name in archive.namelist()
                if name.startswith(prefix) and name.endswith("/document.json")
            }
            assert manifest_ids == {doc["document_id"] for doc in docs} and len(docs) == 129
            chart_path = args.chart_evidence / f"{model}-evaluation-evidence.json"
            if not chart_path.is_file():
                chart_path = args.chart_evidence / f"{model}-evidence.json"
            chart_source = read_json(chart_path)
            evidence, diagnostics[model] = collect(archive, model, docs, cases, chart_source)
            evidence_path = output / f"{model}-evidence.json"
            write_json(evidence_path, evidence)
            metrics[model] = evaluate_feature_rubric(GT, evidence_path, output / model)
    html_report(output, args.zip, metrics, diagnostics, cases)
    for model, result in metrics.items():
        print(MODELS[model], {feature: row["score"] for feature, row in result["features"].items()})
        print(
            diagnostics[model],
            Counter(
                row["status"]
                for row in read_json(output / model / "per_case.json").values()
                if row["protected"]
            ),
        )


if __name__ == "__main__":
    main()
