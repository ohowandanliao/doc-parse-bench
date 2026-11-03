"""Repeatable multi-model evaluation and a compact comparison table."""

import csv
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from .backends.runner import canonical_backend, evaluate
from .io import fresh_directory, read_json, write_json


def benchmark(
    prepared: Path,
    output: Path,
    models: list[str] | None = None,
    backends: list[str] | None = None,
    jobs: int = 2,
    allow_missing: bool = False,
    cdm: bool = False,
    figure: bool = False,
    relations: bool = False,
    exact_teds: bool = False,
    preprocessing: dict | None = None,
) -> dict:
    prepared = prepared.resolve()
    models = models or sorted(p.name for p in (prepared / "pred").iterdir() if p.is_dir())
    backends = backends or ["OmniDocBench", "MPDocBench"]
    if not models:
        raise ValueError("准备目录中没有预测模型")
    if jobs < 1:
        raise ValueError("jobs 必须大于 0")
    output = fresh_directory(output)
    rows, failures = [], []
    with ThreadPoolExecutor(max_workers=jobs) as pool:
        tasks = {}
        for model in models:
            for backend in backends:
                future = pool.submit(
                    evaluate,
                    backend,
                    prepared / "gt" / backend / "gt.json",
                    prepared / "pred" / model / backend,
                    output / model / backend,
                    prepared / "gt" / backend / "markdown",
                    allow_missing,
                    cdm,
                    figure and backend == "MPDocBench",
                    relations and backend == "MPDocBench",
                    exact_teds,
                    preprocessing,
                )
                tasks[future] = (model, backend)
        for future in as_completed(tasks):
            model, backend = tasks[future]
            try:
                metrics = future.result()
                coverage = read_json(output / model / backend / "provenance.json")
                rows.append(
                    {
                        "model": model,
                        "backend": backend,
                        "expected": coverage["expected"],
                        "provided": coverage["provided"],
                        "preprocessing_profile": (preprocessing or {}).get(
                            "profile", "unspecified"
                        ),
                        **metrics,
                    }
                )
                print(f"完成 {model}/{backend}", flush=True)
            except Exception as error:
                failures.append({"model": model, "backend": backend, "error": str(error)})
                print(f"失败 {model}/{backend}: {error}", flush=True)
            write_json(output / "status.json", {"completed": rows, "failures": failures})
    _write_summary(rows, output)
    if failures:
        raise RuntimeError(f"{len(failures)} 项评测失败，详情见 {output / 'status.json'}")
    return {"evaluations": len(rows), "summary": str(output / "summary.md")}


def collect_reports(reports: list[Path], output: Path) -> dict:
    """Summarize completed runs without recomputing any metric."""
    rows = []
    seen = set()
    for root in reports:
        for path in sorted(root.rglob("metrics.json")):
            provenance = path.parent / "provenance.json"
            if not provenance.exists():
                continue
            origin = read_json(provenance)
            preprocessing_profile = (origin.get("preprocessing") or {}).get(
                "profile", "unspecified"
            )
            key = (
                path.parent.parent.name,
                canonical_backend(origin["backend"]),
                preprocessing_profile,
            )
            if key in seen:
                raise ValueError(f"同一模型/后端/前处理预设存在多次报告，请明确选择：{key}")
            seen.add(key)
            rows.append(
                {
                    "model": key[0],
                    "backend": key[1],
                    "expected": origin["expected"],
                    "provided": origin["provided"],
                    "preprocessing_profile": preprocessing_profile,
                    **read_json(path),
                }
            )
    if not rows:
        raise ValueError("没有已完成的评测报告")
    output = fresh_directory(output)
    _write_summary(rows, output)
    return {"evaluations": len(rows), "summary": str(output / "summary.md")}


def _write_summary(rows: list[dict], output: Path) -> None:
    rows = [
        {
            "preprocessing_profile": "unspecified",
            **row,
            "backend": canonical_backend(row["backend"]),
        }
        for row in rows
    ]
    rows.sort(key=lambda row: (row["backend"], row["model"], row["preprocessing_profile"]))
    fields = list(dict.fromkeys(key for row in rows for key in row))
    if rows:
        with (output / "summary.csv").open("w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.DictWriter(stream, fields)
            writer.writeheader()
            writer.writerows(rows)
    write_json(output / "summary.json", rows)
    lines = [
        "# 评测结果",
        "",
        "standard／legacy 只选择前处理预设；数据和评测器由配置独立指定。",
        "AgentBuilder 分项对所有后端均附加计算，不改变原生匹配与计分。",
        "不同数据集、后端或聚合单位的分数不能直接横比；未保存前处理预设的旧报告记为 unspecified。",
    ]
    specifications = {
        "OmniDocBench": (
            "OmniDocBench（按页）",
            "原生分项；FormulaCDM 未计算时，OmniDocBench 官方 Overall 留空。",
            [
                "text_edit",
                "formula_cdm",
                "table_teds",
                "table_teds_s",
                "reading_order_edit",
                "omnidocbench_overall",
            ],
        ),
        "MPDocBench": (
            "MPDocBench（按文档）",
            "原生分项包含跨页内容、标题树、图像和关系；不套用 OmniDocBench 的官方 Overall 公式。",
            [
                "text_edit",
                "merged_text_edit",
                "formula_cdm",
                "table_teds",
                "merged_table_teds",
                "figure_f1",
                "reading_order_edit",
                "head_teds",
                "text_relation_f1",
                "table_relation_f1",
            ],
        ),
        "legacy_compat": (
            "legacy_compat · 历史衍生评测器（按文档，与 legacy 前处理预设独立）",
            "历史兼容分项，保留旧匹配、清洗及聚合行为。",
            [
                "text_accuracy",
                "table_accuracy",
                "table_teds",
                "table_teds_s",
                "reading_order_accuracy",
                "formula_edit",
                "formula_cdm",
            ],
        ),
    }

    def table(group, columns):
        lines.extend(
            [
                "",
                "| " + " | ".join(columns) + " |",
                "| " + " | ".join(["---"] * len(columns)) + " |",
            ]
        )
        for row in group:
            values = []
            for column in columns:
                value = row.get(column)
                values.append(
                    "—"
                    if value is None
                    else f"{value:.4f}"
                    if isinstance(value, float)
                    else str(value)
                )
            lines.append("| " + " | ".join(values) + " |")

    for backend, (title, description, native_columns) in specifications.items():
        group = [row for row in rows if row["backend"] == backend]
        if not group:
            continue
        lines.extend(["", f"## {title}", "", description])
        table(group, ["model", "preprocessing_profile", "expected", "provided", *native_columns])
        lines.extend(
            [
                "",
                "AgentBuilder 自定义扩展（使用上述后端分项；title 为自定义标题分）：",
            ]
        )
        table(
            group,
            [
                "model",
                "preprocessing_profile",
                "text_accuracy",
                "table_accuracy",
                "table_teds",
                "table_teds_s",
                "reading_order_accuracy",
                "formula_accuracy",
                "formula_edit",
                "formula_cdm",
                "title",
                "agentbuilder_overall",
            ],
        )
        if backend == "legacy_compat":
            lines.extend(
                [
                    "",
                    "历史兼容总分（旧程序在加入 title 前计算）：",
                ]
            )
            table(group, ["model", "preprocessing_profile", "legacy_stage_overall"])
    lines.extend(
        [
            "",
            "AgentBuilder = 0.3 × 文本准确度 + 0.3 × 表格 TEDS + 0.3 × 阅读顺序准确度 + 0.1 × title。",
            "缺失分项时按可用权重归一化；title 在 OmniDocBench 按页平均，在 MPDocBench 和 legacy_compat 按文档平均。",
            "AgentBuilder 不替代各后端原生指标；HeadTEDS、跨页续接和 FigureF1 等不包含在此加权分内。",
        ]
    )
    (output / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
