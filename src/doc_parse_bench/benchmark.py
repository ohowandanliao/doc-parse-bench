"""Repeatable multi-model evaluation and a compact comparison table."""

import csv
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from .backends.runner import canonical_backend, evaluate
from .io import fresh_directory, read_json, write_json
from .leaderboards import write_leaderboards
from .metrics import normalize_report_metrics


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
                    **(
                        {"dataset_version": origin["dataset_version"]}
                        if origin.get("dataset_version")
                        else {}
                    ),
                    **(
                        {"gt_sha256": origin["gt_sha256"]}
                        if isinstance(origin.get("gt_sha256"), str)
                        else {}
                    ),
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
        normalize_report_metrics(
            {
                "preprocessing_profile": "unspecified",
                **row,
                "backend": canonical_backend(row["backend"]),
            },
            canonical_backend(row["backend"]),
        )
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
    write_leaderboards(rows, output)
