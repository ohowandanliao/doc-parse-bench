"""Render source PDF excerpts beside the frozen four-feature GT for local review."""

from contextlib import closing
from html import escape
from pathlib import Path
from string import Template
from unicodedata import normalize
from urllib.parse import quote

from pypdfium2 import PdfDocument

from ...io import read_json, sha256

ROOT = Path(__file__).resolve().parents[4]
REVIEW = ROOT / "artifacts/legacy129-formal-gt-review-20261125"
GT = ROOT / "artifacts/legacy-features-20261125/rubric-evaluation-gt.json"
PDF_DIR = ROOT / "data/legacy/dataset/pdf/source"
OUTPUT = REVIEW / "sample-review"

SAMPLES = (
    (
        "附录边界",
        "关闭附录时按旧版规则从首个符合条件的标题页截断到文末。第 37 页的 D.6 至 D.8 和第 38 页的简介都随页删除。",
        (
            "bc_017:p37:appendix",
            "bc_017:p38:appendix",
            "bc_003:p19:protect-before-cutoff",
            "bc_003:p35:appendix",
        ),
    ),
    (
        "独立附件",
        "按旧版 MinerU 逻辑，这份单页 PDF 的标题以「附件」开头，两档都保留。旧规则查找后半段以「附录」或「Appendix」开头的标题。",
        ("bc_119:p1:独立资格认定细则",),
    ),
    (
        "页眉标志与印刷页码",
        "核对标志、机构名、页脚部门名和印刷页码。",
        ("bc_100:p1:margins",),
    ),
    (
        "流程图",
        "核对图内文字和箭头方向，尤其是「存在争议」的两个去向。",
        ("bc_003:candidate.block.p9.0002",),
    ),
    (
        "有字与无字照片",
        "核对近景石碑的两段字，以及远景照片的空文字字段。",
        ("bc_077:candidate.block.p1.0008", "bc_077:candidate.block.p1.0009"),
    ),
    (
        "印章与骑缝残章",
        "核对圆章的可辨片段，并判断右侧骑缝残章的可读性。",
        ("bc_019:candidate.block.p12.0004", "bc_019:candidate.block.p11.0006"),
    ),
    (
        "饼图金额与占比",
        "核对各类别的金额和百分比，两列使用各自单位。",
        ("bc_014:candidate.block.p5.0017",),
    ),
    (
        "分组柱状图",
        "按图例颜色核对三组系列、年份与柱顶数值。",
        ("bc_015:candidate.block.p10.0004",),
    ),
    (
        "五环图的计分范围",
        "查看每个圈位的类别含义能否从本页确认。",
        ("bc_017:candidate.block.p23.0003",),
    ),
)

FEATURES = {
    "appendix": "附录",
    "header_footer": "页眉页脚",
    "image": "图片与印章",
    "chart": "图表",
}
EDGE_LABELS = {
    "header": "页眉文字",
    "footer": "页脚文字",
    "header_image": "页眉图形",
    "footer_image": "页脚图形",
    "page_number": "印刷页码",
}
SUBTYPES = {
    "flowchart": "流程图",
    "natural_image": "照片",
    "seal": "印章",
    "text_image": "文字图",
    "other": "诊断图像",
}

PAGE = Template("""<!doctype html>
<html lang="zh-CN">
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>129 篇四功能 GT 抽样审阅</title>
<style>
:root { color-scheme: light; --paper: #f4f6f5; --ink: #142a29; --muted: #4f6764;
        --line: #cfdad7; --accent: #075c50; --surface: #fff; }
* { box-sizing: border-box; }
body { margin: 0; background: var(--paper); color: var(--ink); font: 16px/1.6 system-ui, sans-serif; }
main { max-width: 1280px; margin: 0 auto; padding: 32px 20px 56px; }
header { max-width: 80ch; }
h1 { font-size: clamp(1.7rem, 4vw, 2.55rem); line-height: 1.2; letter-spacing: -.025em; }
h2, h3 { line-height: 1.3; margin: 0; }
h2 { font-size: 1.35rem; }
h3 { font-size: 1rem; margin: 8px 0; }
a { color: var(--accent); text-underline-offset: 3px; }
a:focus-visible, summary:focus-visible { outline: 2px solid var(--accent); outline-offset: 3px; }
code { font-size: .80em; overflow-wrap: anywhere; }
.muted, figcaption { color: var(--muted); }
nav { display: flex; flex-wrap: wrap; gap: 8px 16px; padding: 14px 0 24px; }
article { margin: 0 0 20px; background: var(--surface); border: 1px solid var(--line);
          border-radius: 10px; padding: clamp(14px, 3vw, 24px); scroll-margin-top: 16px; }
article:target { border-color: var(--accent); }
.case { display: grid; grid-template-columns: minmax(0, 1.08fr) minmax(0, 1fr);
        gap: 18px; border-top: 1px solid var(--line); padding-top: 14px; margin-top: 14px; }
figure { margin: 0 0 10px; padding: 8px; background: #eff3f1; border-radius: 6px; }
figure img { display: block; max-width: 100%; max-height: 560px; height: auto; margin: auto; }
figcaption { margin-top: 5px; font-size: .85rem; }
table { width: 100%; border-collapse: collapse; font-size: .9rem; }
th, td { padding: 5px 8px; text-align: left; vertical-align: top;
         border-bottom: 1px solid var(--line); overflow-wrap: anywhere; }
th { background: #edf3f0; }
ol { padding-left: 1.5rem; }
details { margin-top: 12px; }
summary { cursor: pointer; color: var(--accent); }
@media (max-width: 760px) { .case { grid-template-columns: 1fr; } }
</style>
<main>
<header id="start">
<h1>129 篇四功能 GT 抽样审阅</h1>
<p>附录、页眉页脚、图片与印章、图表。选取了容易影响分数的样本，点原图可以放大。</p>
<p>如果某项需要改，回我样本编号、字段和正确内容即可。</p>
<p>附录已按旧版 MinerU 规则核对 129 篇。样本 05–09 已抽查。</p>
<p class="muted"><code>legacy-129-feature-v3 · split=evaluation · SHA-256 $digest</code></p>
</header>
<nav aria-label="样本目录">$navigation</nav>
$articles
</main>
</html>
""")


def table(headers, rows):
    head = "".join(f"<th scope='col'>{escape(value)}</th>" for value in headers)
    body = "".join(
        "<tr>" + "".join(f"<td>{escape(str(value))}</td>" for value in row) + "</tr>"
        for row in rows
    )
    return f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"


def figure(path, label):
    url = quote(path.relative_to(OUTPUT).as_posix())
    return (
        f"<figure><a href='{url}' target='_blank' rel='noopener'>"
        f"<img src='{url}' alt='{escape(label)}' loading='lazy'></a>"
        f"<figcaption>{escape(label)}</figcaption></figure>"
    )


def pixel_box(bbox, size):
    return tuple(round(value * dimension) for value, dimension in zip(bbox, size * 2))


def margin_box(blocks):
    return (
        max(0, min(block["bbox"][0] for block in blocks) - 0.025),
        max(0, min(block["bbox"][1] for block in blocks) - 0.012),
        min(1, max(block["bbox"][2] for block in blocks) + 0.025),
        min(1, max(block["bbox"][3] for block in blocks) + 0.012),
    )


def excerpts(case, pdf_path, asset_dir):
    page_tag = f"{case['document_id']}-p{case['page']:03d}"
    full_page = asset_dir / f"{page_tag}.png"
    boxes = []
    if "blocks" in case:
        for location, match in (("页眉", True), ("页脚", False)):
            blocks = [
                block for block in case["blocks"] if block["type"].startswith("header") == match
            ]
            if blocks:
                boxes.append((location, margin_box(blocks)))
    elif "bbox" in case:
        boxes.append(("源块裁图", case["bbox"]))
    with PdfDocument(pdf_path) as document:
        with closing(document[case["page"] - 1]) as page:
            if not full_page.exists():
                with closing(page.render(scale=2.5)) as bitmap, bitmap.to_pil() as rendered:
                    rendered.save(full_page)
            if not boxes:
                return figure(full_page, f"原 PDF 第 {case['page']} 页")
            images = []
            with closing(page.render(scale=4)) as bitmap, bitmap.to_pil() as rendered:
                source_suffix = case.get("source_id", "margins").rsplit(".", 1)[-1]
                for index, (label, bbox) in enumerate(boxes, start=1):
                    name = asset_dir / f"{page_tag}-{source_suffix}-{index}.png"
                    with rendered.crop(pixel_box(bbox, rendered.size)) as part:
                        part.save(name)
                    images.append(figure(name, label))
    page_url = quote(full_page.relative_to(OUTPUT).as_posix())
    images.append(f"<a href='{page_url}' target='_blank' rel='noopener'>查看整页</a>")
    return "".join(images)


def render_annotation(case):
    feature = case["feature"]
    if feature == "appendix":
        protected = case.get("protected")
        action = "保护项" if protected else "随附录截断的计分页"
        off = "保留此页内容" if protected else "删除整页"
        anchors = "".join(f"<li>{escape(anchor)}</li>" for anchor in case["anchors"])
        expected = table(
            ("附录开关", "预期交付"),
            (("保留附录", "保留此页内容"), ("关闭附录", off)),
        )
        return f"<h3>{action}</h3>{expected}<h3>保留时核对的原文锚点</h3><ol>{anchors}</ol>"
    if feature == "header_footer":
        return table(
            ("源块", "类别", "GT 文字"),
            (
                (
                    block["id"].rsplit(".", 1)[-1],
                    EDGE_LABELS[block["type"]],
                    block.get("text") or "—",
                )
                for block in case["blocks"]
            ),
        )
    if feature == "chart":
        if not case["values"]:
            return "<h3>诊断</h3><p>本图的明示值计分范围为空。</p>"
        return table(
            ("系列", "类别", "明示值", "单位"),
            (
                (point["series"], point["category"], point["value"], point["unit"])
                for point in case["values"]
            ),
        )
    subtype = SUBTYPES[case["sub_type"]]
    if case.get("reviewed_subtype"):
        subtype += f" · {SUBTYPES[case['reviewed_subtype']]}"
    fields = {field["key"]: field["text"] for field in case.get("fields", [])}
    content = [f"<h3>{escape(subtype)}</h3>"]
    if fields:
        content.append(table(("字段", "GT 文字"), fields.items()))
    else:
        content.append("<p>GT 文字字段为空。</p>")
    if relations := case.get("relations"):
        edges = table(
            ("起点", "终点"), ((fields[row["from"]], fields[row["to"]]) for row in relations)
        )
        content.append(
            f"<details open><summary>有向关系（{len(relations)} 条）</summary>{edges}</details>"
        )
    return "".join(content)


def render_case(case, pdf_path, asset_dir):
    feature = FEATURES[case["feature"]]
    asset_html = excerpts(case, pdf_path, asset_dir)
    note = escape(case.get("scope_note", ""))
    return (
        f"<div class='case'><div>{asset_html}</div><div>"
        f"<h3>{feature} · {escape(case['source_pdf'])} · 第 {case['page']} 页</h3>"
        f"<code>{escape(case['id'])}</code>{render_annotation(case)}"
        f"<p class='muted'>{note}</p></div></div>"
    )


def main():
    ground_truth = read_json(GT)
    cases = {case["id"]: case for case in ground_truth["cases"]}
    source_manifest = read_json(GT.with_name("rubric-evaluation-sources.json"))
    sources = {row["document_id"]: row for row in source_manifest["documents"]}
    pdfs = {normalize("NFC", path.name): path for path in PDF_DIR.glob("*.pdf")}
    selected = [cases[case_id] for _, _, case_ids in SAMPLES for case_id in case_ids]
    for document_id in sorted({case["document_id"] for case in selected}):
        source = sources[document_id]
        if sha256(pdfs[normalize("NFC", source["source_pdf"])]) != source["pdf_sha256"]:
            raise ValueError(f"Source PDF hash differs for {document_id}")
    asset_dir = OUTPUT / "sources"
    asset_dir.mkdir(parents=True, exist_ok=True)
    navigation = []
    articles = []
    for number, (title, prompt, case_ids) in enumerate(SAMPLES, start=1):
        anchor = f"sample-{number:02d}"
        label = f"{number:02d} {title}"
        navigation.append(f"<a href='#{anchor}'>{escape(label)}</a>")
        content = "".join(
            render_case(
                cases[case_id], pdfs[normalize("NFC", cases[case_id]["source_pdf"])], asset_dir
            )
            for case_id in case_ids
        )
        if number == 1:
            ranges = table(
                ("文档", "关闭时删除的物理页"),
                (
                    (row["document_id"], f"{pages[0]}–{pages[-1]}")
                    for row in sources.values()
                    if (pages := row["appendix_pages"])
                ),
            )
            content = ranges + content
        articles.append(
            f"<article id='{anchor}'><h2>{escape(label)}</h2>"
            f"<p>{escape(prompt)}</p>{content}</article>"
        )
    index = OUTPUT / "index.html"
    index.write_text(
        PAGE.substitute(
            digest=sha256(GT), navigation="\n".join(navigation), articles="\n".join(articles)
        ),
        encoding="utf-8",
    )
    print(index)


if __name__ == "__main__":
    main()
