"""Repeatable multi-model evaluation and a compact comparison table."""

import csv
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from .backends.runner import evaluate
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
            key = (path.parent.parent.name, origin["backend"])
            if key in seen:
                raise ValueError(f"同一模型/后端存在多次报告，请明确选择：{key}")
            seen.add(key)
            rows.append(
                {
                    "model": key[0],
                    "backend": key[1],
                    "expected": origin["expected"],
                    "provided": origin["provided"],
                    **read_json(path),
                }
            )
    if not rows:
        raise ValueError("没有已完成的评测报告")
    output = fresh_directory(output)
    _write_summary(rows, output)
    return {"evaluations": len(rows), "summary": str(output / "summary.md")}


def _write_summary(rows: list[dict], output: Path) -> None:
    rows.sort(key=lambda row: (row["backend"], row["model"]))
    fields = list(dict.fromkeys(key for row in rows for key in row))
    if rows:
        with (output / "summary.csv").open("w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.DictWriter(stream, fields)
            writer.writeheader()
            writer.writerows(rows)
    write_json(output / "summary.json", rows)
    columns = [
        "model",
        "backend",
        "provided",
        "text_accuracy",
        "table_teds",
        "reading_order_accuracy",
        "title",
        "head_teds",
        "merged_text_accuracy",
        "merged_table_teds",
    ]
    lines = [
        "# 混合评测结果",
        "",
        "各指标在各自 benchmark 内比较；缺失预测按所选策略处理。",
        "FormulaCDM 未启用时，OmniDocBench 官方 Overall 留空。",
        "",
        "| " + " | ".join(columns) + " |",
        "| " + " | ".join(["---"] * len(columns)) + " |",
    ]
    for row in rows:
        values = [
            f"{row[c]:.4f}" if isinstance(row.get(c), float) else str(row.get(c, "—"))
            for c in columns
        ]
        lines.append("| " + " | ".join(values) + " |")
    (output / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
