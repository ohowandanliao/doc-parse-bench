"""End-user workflows. Mode definitions set the policy; paths describe the data."""

from dataclasses import asdict
from pathlib import Path

import yaml

from .annotations import import_annotations
from .backends.runner import evaluate
from .benchmark import benchmark, collect_reports
from .compatibility import prepare_legacy
from .compatibility.cleaning import CleaningOptions, normalize_markdown
from .exporters import export_gt, export_predictions
from .io import fresh_directory, write_json
from .predictions import import_predictions
from .profiles import resolve_options


def run(config_path: Path, overrides: dict | None = None) -> dict:
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    profile = config["profile"]
    options = resolve_options(profile, overrides)
    base = config_path.resolve().parent

    def path(value):
        return (base / value).resolve()

    output = fresh_directory(path(config["output"]))
    write_json(
        output / "run.json",
        {
            "profile": profile,
            "options": asdict(options),
            "overrides": {k: v for k, v in (overrides or {}).items() if v is not None},
            "config": config,
        },
    )
    cleaning = CleaningOptions(options.replace_embedded_images, options.expand_chart_details)
    if profile == "legacy":
        reports = []
        for name, model in config["models"].items():
            predictions = output / "prepared" / name
            prepare_legacy(path(model["source"]), predictions, cleaning)
            report = output / "results" / name / "legacy"
            evaluate(
                "legacy",
                path(config["ground_truth"]),
                predictions,
                report,
                allow_missing=options.allow_missing,
                cdm=options.formula_cdm,
                exact_teds=options.exact_teds,
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
        allow_missing=options.allow_missing,
        cdm=options.formula_cdm,
        figure=options.figure_metric,
        relations=options.relation_metrics,
        exact_teds=options.exact_teds,
    )
