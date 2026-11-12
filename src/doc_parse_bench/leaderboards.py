"""Three explicit scoreboards; AgentBuilder accepts only the page evaluator."""

import csv
from pathlib import Path

from .io import write_json
from .metrics import normalize_report_metrics

METADATA = (
    "model",
    "model_display_name",
    "preprocessing_profile",
    "expected",
    "provided",
    "dataset_documents",
    "dataset_version",
    "gt_sha256",
)
AGENTBUILDER_COLUMNS = (
    "agentbuilder_overall",
    "text_accuracy",
    "table_accuracy",
    "table_teds",
    "table_teds_s",
    "reading_order_accuracy",
    "formula_edit",
    "formula_accuracy",
    "formula_cdm",
    "title",
)
OMNI_COLUMNS = (
    "text_edit",
    "table_edit",
    "table_teds",
    "table_teds_s",
    "formula_edit",
    "formula_cdm",
    "reading_order_edit",
    "omnidocbench_overall",
)
MP_COLUMNS = (
    "mpdocbench_overall",
    "text_edit",
    "merged_text_edit",
    "table_edit",
    "table_teds",
    "table_teds_s",
    "merged_table_edit",
    "merged_table_teds",
    "merged_table_teds_s",
    "formula_edit",
    "formula_cdm",
    "reading_order_edit",
    "head_teds",
    "figure_f1",
    "text_relation_f1",
    "text_relation_cross_page_f1",
    "text_relation_same_page_f1",
    "table_relation_f1",
    "table_relation_cross_page_f1",
    "table_relation_same_page_f1",
)
HISTORICAL_COLUMNS = (
    "text_accuracy",
    "table_accuracy",
    "table_teds",
    "table_teds_s",
    "reading_order_accuracy",
    "formula_edit",
    "formula_accuracy",
    "formula_cdm",
    "title",
    "historical_weighted_overall",
    "legacy_stage_overall",
)


def markdown_table(rows: list[dict], columns: tuple | list) -> list[str]:
    lines = ["| " + " | ".join(columns) + " |", "| " + " | ".join("---" for _ in columns) + " |"]
    for row in rows:
        values = []
        for key in columns:
            value = (
                row.get("model_display_name", row.get("model")) if key == "model" else row.get(key)
            )
            label = (
                "—" if value is None else f"{value:.4f}" if isinstance(value, float) else str(value)
            )
            values.append(label.replace("|", "\\|").replace("\n", " "))
        lines.append("| " + " | ".join(values) + " |")
    return lines


def _group(row):
    return tuple(
        str(row.get(k, ""))
        for k in ("dataset_documents", "dataset_version", "gt_sha256", "preprocessing_profile")
    )


def _write_board(directory, name, rows, columns, description):
    directory.mkdir(parents=True, exist_ok=True)
    fields = list(
        dict.fromkeys(
            [
                "leaderboard",
                "source_backend",
                "backend",
                "evaluation_unit",
                "rank",
                *[
                    k
                    for k in METADATA
                    if k in {"model", "preprocessing_profile", "expected", "provided"}
                    or any(k in r for r in rows)
                ],
                *columns,
            ]
        )
    )
    write_json(directory / "summary.json", rows)
    with (directory / "summary.csv").open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fields)
        writer.writeheader()
        writer.writerows(rows)
    display = ["rank", "model", "preprocessing_profile", "expected", "provided", *columns]
    lines = [f"# {name}", "", description, ""]
    lines.extend(markdown_table(rows, display) if rows else ["暂无此榜所需的评测结果。"])
    (directory / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_leaderboards(rows: list[dict], output: Path) -> dict:
    descriptions = {
        "AgentBuilder": "固定使用 OmniDocBench 页面匹配分项和按页平均的 title。文本/TEDS/顺序/title 权重为 0.3/0.3/0.3/0.1；缺项按可用权重归一化。按数据口径和前处理预设分别排名。",
        "OmniDocBench": "页面级原生指标；编辑距离越低越好，TEDS/CDM 越高越好。FormulaCDM 未计算时官方 Overall 留空，不以自定义总分替代。",
        "MPDocBench": "文档级原生指标，包括合并内容、标题树、图像和续接关系。官方 Overall 为八项任务相似度的等权平均；编辑距离先转为 1−距离，八项缺一则留空。关系 F1 单列，不计入官方总分。",
    }
    boards = {name: [] for name in descriptions}
    historical = []
    for raw in rows:
        row = normalize_report_metrics(raw, raw["backend"])
        backend = "legacy_compat" if row["backend"] == "legacy" else row["backend"]
        meta = {key: row[key] for key in METADATA if key in row}
        if backend == "legacy_compat":
            historical.append(
                {**meta, "backend": backend, **{k: row.get(k) for k in HISTORICAL_COLUMNS}}
            )
            continue
        names = ("AgentBuilder", "OmniDocBench") if backend == "OmniDocBench" else ("MPDocBench",)
        for name in names:
            columns = (
                AGENTBUILDER_COLUMNS
                if name == "AgentBuilder"
                else OMNI_COLUMNS
                if name == "OmniDocBench"
                else MP_COLUMNS
            )
            boards[name].append(
                {
                    **meta,
                    "leaderboard": name,
                    "source_backend": backend,
                    "backend": backend,
                    "evaluation_unit": "page" if backend == "OmniDocBench" else "document",
                    **{key: row.get(key) for key in columns},
                }
            )
    index = {"leaderboards": {}}
    for name, group in boards.items():
        if name == "AgentBuilder":
            group.sort(
                key=lambda row: (
                    _group(row),
                    row["agentbuilder_overall"] is None,
                    -(row["agentbuilder_overall"] or 0),
                    row["model"],
                )
            )
            ranks = {}
            for row in group:
                if row["agentbuilder_overall"] is not None:
                    key = _group(row)
                    ranks[key] = ranks.get(key, 0) + 1
                    row["rank"] = ranks[key]
        else:
            group.sort(key=lambda row: (_group(row), row["model"]))
        columns = (
            AGENTBUILDER_COLUMNS
            if name == "AgentBuilder"
            else OMNI_COLUMNS
            if name == "OmniDocBench"
            else MP_COLUMNS
        )
        directory = output / "leaderboards" / name
        _write_board(directory, name, group, columns, descriptions[name])
        index["leaderboards"][name] = {
            "entries": len(group),
            "source_backend": "OmniDocBench" if name == "AgentBuilder" else name,
            "markdown": f"leaderboards/{name}/summary.md",
            "json": f"leaderboards/{name}/summary.json",
            "csv": f"leaderboards/{name}/summary.csv",
        }
    write_json(output / "leaderboards/index.json", index)
    if historical:
        directory = output / "historical/legacy_compat"
        _write_board(
            directory,
            "历史兼容分析（不进入三个正式榜）",
            historical,
            HISTORICAL_COLUMNS,
            "保留历史分项和 historical_weighted_overall，独立于 legacy 前处理预设。",
        )
    lines = ["# 三个独立榜", "", "standard／legacy 只控制前处理，榜单和数据口径独立。", ""]
    for name, group in boards.items():
        target = index["leaderboards"][name]["markdown"]
        lines.extend(
            [
                f"## {name}",
                "",
                descriptions[name],
                "",
                f"[独立榜单]({target}) · [CSV]({index['leaderboards'][name]['csv']}) · [JSON]({index['leaderboards'][name]['json']})",
                "",
            ]
        )
        columns = (
            AGENTBUILDER_COLUMNS
            if name == "AgentBuilder"
            else OMNI_COLUMNS
            if name == "OmniDocBench"
            else MP_COLUMNS
        )
        lines.extend(
            markdown_table(group, ["model", "preprocessing_profile", *columns])
            if group
            else ["暂无结果。"]
        )
        lines.append("")
    if historical:
        lines.extend(
            [
                "## 历史兼容分析",
                "",
                "129 篇历史兼容结果不进入三个正式榜，旧加权分保留为 historical_weighted_overall。",
                "",
                "[历史分项](historical/legacy_compat/summary.md)",
                "",
            ]
        )
        lines.extend(
            markdown_table(historical, ["model", "preprocessing_profile", *HISTORICAL_COLUMNS])
        )
    (output / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return index
