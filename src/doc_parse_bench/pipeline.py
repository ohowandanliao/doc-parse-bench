"""Datasets and backends are explicit; profiles only set preprocessing defaults."""

from dataclasses import asdict
from pathlib import Path

import yaml

from .annotations import import_annotations
from .backends.runner import canonical_backend, evaluate
from .benchmark import benchmark, collect_reports
from .compatibility import prepare_legacy
from .compatibility.cleaning import CleaningOptions, normalize_markdown
from .exporters import export_gt, export_predictions
from .io import fresh_directory, write_json
from .predictions import import_predictions
from .profiles import resolve_options


def run(
    config_path: Path,
    overrides: dict | None = None,
    legacy_preprocessing: bool | None = None,
) -> dict:
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    profile = config["profile"]
    if legacy_preprocessing is not None:
        profile = "legacy" if legacy_preprocessing else "standard"
    options = resolve_options(profile, overrides)
    input_format = config.get(
        "input_format", "markdown" if "ground_truth" in config else "annotations"
    )
    allowed = {
        "annotations": ["OmniDocBench", "MPDocBench"],
        "markdown": ["legacy_compat"],
    }
    if input_format not in allowed:
        raise ValueError(f"未知输入格式：{input_format}")
    backends = [canonical_backend(value) for value in config.get("backends", allowed[input_format])]
    if not backends or len(set(backends)) != len(backends):
        raise ValueError("评测器列表不能为空或重复")
    if set(backends) - set(allowed[input_format]):
        raise ValueError(f"{input_format} 输入不能用于这些评测器：{backends}")
    if input_format == "markdown" and options.merge_context:
        raise ValueError("历史 Markdown 缺少页面关系，不能启用跨页推断")
    preprocessing = {
        "profile": profile,
        "replace_embedded_images": options.replace_embedded_images,
        "expand_chart_details": options.expand_chart_details,
    }
    base = config_path.resolve().parent

    def path(value):
        return (base / value).resolve()

    output = fresh_directory(path(config["output"]))
    write_json(
        output / "run.json",
        {
            "profile": profile,
            "input_format": input_format,
            "backends": backends,
            "preprocessing": preprocessing,
            "legacy_preprocessing_override": legacy_preprocessing,
            "options": asdict(options),
            "overrides": {k: v for k, v in (overrides or {}).items() if v is not None},
            "config": config,
        },
    )
    cleaning = CleaningOptions(options.replace_embedded_images, options.expand_chart_details)
    if input_format == "markdown":
        reports = []
        for name, model in config["models"].items():
            predictions = output / "prepared" / name
            prepare_legacy(path(model["source"]), predictions, cleaning)
            report = output / "results" / name / "legacy_compat"
            evaluate(
                "legacy_compat",
                path(config["ground_truth"]),
                predictions,
                report,
                allow_missing=options.allow_missing,
                cdm=options.formula_cdm,
                exact_teds=options.exact_teds,
                preprocessing=preprocessing,
            )
            reports.append(report)
        return collect_reports(reports, output / "summary")
    prepared = output / "prepared"
    document_map = path(config["document_map"]) if config.get("document_map") else None
    import_annotations(
        path(config["annotations"]),
        prepared / "gt_ir",
        document_map=document_map,
        dataset_version=config.get("dataset_version"),
    )
    export_gt(prepared / "gt_ir/documents", prepared / "gt", "native")
    for name, model in config["models"].items():
        ir = prepared / "pred_ir" / name
        import_predictions(path(model["source"]), ir, model["adapter"], document_map)
        dest = prepared / "pred" / name
        export_predictions(
            ir / "documents", dest, "native", "conservative" if options.merge_context else "native"
        )
        for markdown in dest.glob("*/*.md"):
            markdown.write_text(
                normalize_markdown(markdown.read_text(encoding="utf-8"), cleaning), encoding="utf-8"
            )
    return benchmark(
        prepared,
        output / "results",
        jobs=config.get("jobs", 2),
        backends=backends,
        allow_missing=options.allow_missing,
        cdm=options.formula_cdm,
        figure=options.figure_metric,
        relations=options.relation_metrics,
        exact_teds=options.exact_teds,
        preprocessing=preprocessing,
    )
