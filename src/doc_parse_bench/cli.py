"""Stable CLI; implementation lives in focused modules."""

import argparse
import json
from pathlib import Path

from .annotations import import_annotations
from .backends.runner import evaluate
from .benchmark import benchmark, collect_reports
from .charts import augment_charts
from .compatibility import prepare_legacy
from .exporters import export_gt, export_predictions
from .history import compare_workbook
from .pipeline import run as run_profile
from .predictions import MODELS, import_predictions
from .quality import audit_quality


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="docbench", description="混合文档解析评测")
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", help="按 standard / legacy 固定模式完成准备和评测")
    run.add_argument("config", type=Path)
    for flag, target, help_text in (
        ("replace-images", "replace_embedded_images", "替换嵌入的 base64 图片"),
        ("expand-details", "expand_chart_details", "展开历史图表 details"),
        ("merge-context", "merge_context", "补充预测端保守跨页推断"),
        ("allow-missing", "allow_missing", "将缺失结果按空预测计分"),
        ("cdm", "formula_cdm", "启用 FormulaCDM，需完整 TeX 环境"),
        ("exact-teds", "exact_teds", "启用大表格精确计算加速"),
    ):
        run.add_argument(
            "--" + flag,
            dest=target,
            action=argparse.BooleanOptionalAction,
            default=None,
            help=help_text + "；默认使用模式预设",
        )
    anno = sub.add_parser("import-gt", help="叠加 runs 和整页标注快照")
    anno.add_argument("source", type=Path)
    anno.add_argument("output", type=Path)
    anno.add_argument("--annotations", type=Path)
    anno.add_argument("--document-map", type=Path)
    anno.add_argument("--dataset-version", help="数据版本标签，例如 v1.1；不改变评测模式")
    pred = sub.add_parser("import-pred", help="模型输出转统一结构")
    pred.add_argument("source", type=Path)
    pred.add_argument("output", type=Path)
    pred.add_argument("--model", required=True, choices=sorted(MODELS))
    pred.add_argument("--document-map", type=Path)
    for name in ("export-gt", "export-pred"):
        exporter = sub.add_parser(name, help="导出 OmniDocBench 和 MPDocBench 两套输入")
        exporter.add_argument("source", type=Path, help="中间格式 documents/ 目录")
        exporter.add_argument("output", type=Path)
        exporter.add_argument("--chart-policy", choices=["native", "chart-table"], default="native")
        if name == "export-pred":
            exporter.add_argument("--context", choices=["native", "conservative"], default="native")
    legacy = sub.add_parser("prepare-legacy", help="保留历史 fix 清洗口径")
    legacy.add_argument("source", type=Path)
    legacy.add_argument("output", type=Path)
    charts = sub.add_parser("augment-charts", help="从人工审核表格或显式 provider 增强图表")
    charts.add_argument("source", type=Path)
    charts.add_argument("output", type=Path)
    group = charts.add_mutually_exclusive_group(required=True)
    group.add_argument("--tables", type=Path)
    group.add_argument(
        "--provider", nargs="+", help="JSON stdin/stdout provider 命令，不通过 shell"
    )
    charts.add_argument("--pdf-dir", type=Path)
    run = sub.add_parser("evaluate", help="运行官方评测并补充旧版 title 分数")
    run.add_argument("--backend", choices=["OmniDocBench", "MPDocBench", "legacy"], required=True)
    run.add_argument("--gt", type=Path, required=True)
    run.add_argument("--pred", type=Path, required=True)
    run.add_argument("--output", type=Path, required=True)
    run.add_argument("--title-gt", type=Path)
    run.add_argument("--allow-missing", action="store_true")
    run.add_argument("--cdm", action="store_true")
    run.add_argument("--figure", action="store_true", help="启用 MPDocBench FigureF1")
    run.add_argument("--relations", action="store_true", help="启用 MPDocBench 跨页关系 F1")
    prepare = sub.add_parser("prepare", help="按配置准备完整数据集和多模型输入")
    prepare.add_argument("config", type=Path)
    batch = sub.add_parser("benchmark", help="批量评测准备目录内的模型并生成对比表")
    batch.add_argument("prepared", type=Path)
    batch.add_argument("output", type=Path)
    batch.add_argument("--models", nargs="+")
    batch.add_argument("--backends", nargs="+", choices=["OmniDocBench", "MPDocBench"])
    batch.add_argument("--jobs", type=int, default=2)
    batch.add_argument("--allow-missing", action="store_true")
    batch.add_argument("--cdm", action="store_true")
    batch.add_argument("--figure", action="store_true")
    batch.add_argument("--relations", action="store_true")
    collect = sub.add_parser("collect", help="汇总已完成评测，不重跑指标")
    collect.add_argument("reports", type=Path, nargs="+")
    collect.add_argument("--output", type=Path, required=True)
    compare = sub.add_parser("compare-xlsx", help="将已完成的旧版跑分与 XLSX 逐列对账")
    compare.add_argument("workbook", type=Path)
    compare.add_argument("run", type=Path)
    compare.add_argument("--tag", required=True)
    compare.add_argument("--output", type=Path, required=True)
    audit = sub.add_parser("audit-quality", help="检查 GT 结构、关系确认状态和旧新 PDF 重叠")
    audit.add_argument("source", type=Path)
    audit.add_argument("output", type=Path)
    audit.add_argument("--legacy-pdfs", type=Path)
    audit.add_argument("--current-pdfs", type=Path)
    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "run":
            keys = (
                "replace_embedded_images",
                "expand_chart_details",
                "merge_context",
                "allow_missing",
                "formula_cdm",
                "exact_teds",
            )
            result = run_profile(args.config, {key: getattr(args, key) for key in keys})
        elif args.command == "import-gt":
            result = import_annotations(
                args.source, args.output, args.annotations, args.document_map, args.dataset_version
            )
            result = {
                k: v
                for k, v in result.items()
                if k
                not in {
                    "sources",
                    "issues",
                    "pdf_sources",
                    "document_annotations",
                    "output_documents_sha256",
                }
            }
        elif args.command == "import-pred":
            result = import_predictions(args.source, args.output, args.model, args.document_map)
            result = {k: v for k, v in result.items() if k != "sources"}
        elif args.command == "export-gt":
            result = export_gt(args.source, args.output, args.chart_policy)
            result = {
                k: v
                for k, v in result.items()
                if not k.endswith("_files") and k != "source_documents_sha256"
            }
        elif args.command == "export-pred":
            result = export_predictions(args.source, args.output, args.chart_policy, args.context)
            result.pop("context_events", None)
        elif args.command == "prepare-legacy":
            result = prepare_legacy(args.source, args.output)
            result.pop("sources", None)
        elif args.command == "augment-charts":
            result = augment_charts(
                args.source, args.output, args.tables, args.provider, args.pdf_dir
            )
            result = {"charts": len(result["records"])}
        elif args.command == "evaluate":
            result = evaluate(
                args.backend,
                args.gt,
                args.pred,
                args.output,
                args.title_gt,
                args.allow_missing,
                args.cdm,
                args.figure,
                args.relations,
            )
        elif args.command == "benchmark":
            result = benchmark(
                args.prepared,
                args.output,
                args.models,
                args.backends,
                args.jobs,
                args.allow_missing,
                args.cdm,
                args.figure,
                args.relations,
            )
        elif args.command == "collect":
            result = collect_reports(args.reports, args.output)
        elif args.command == "compare-xlsx":
            result = compare_workbook(args.workbook, args.run, args.tag, args.output)
        elif args.command == "audit-quality":
            result = audit_quality(args.source, args.output, args.legacy_pdfs, args.current_pdfs)
        else:
            result = prepare_from_config(args.config)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except (ValueError, KeyError, RuntimeError, OSError) as error:
        parser.exit(1, f"错误：{error}\n")


def prepare_from_config(path: Path) -> dict:
    import yaml

    config = yaml.safe_load(path.read_text(encoding="utf-8"))
    base = path.resolve().parent

    def resolve(value):
        return (base / value).resolve()

    output = resolve(config["output"])
    policy = config.get("chart_policy", "native")
    context = config.get("context_policy", "native")
    document_map = resolve(config["document_map"]) if config.get("document_map") else None
    gt = output / "gt_ir"
    audit = import_annotations(
        resolve(config["annotations"]),
        gt,
        document_map=document_map,
        dataset_version=config.get("dataset_version"),
    )
    export_gt(gt / "documents", output / "gt", policy)
    models = {}
    for tag, model in config["models"].items():
        dest = output / "pred_ir" / tag
        report = import_predictions(resolve(model["source"]), dest, model["adapter"], document_map)
        export_predictions(dest / "documents", output / "pred" / tag, policy, context)
        models[tag] = {"documents": report["documents"], "pages": report["pages"]}
    return {
        "output": str(output),
        "gt_documents": audit["documents"],
        "gt_pages": audit["pages"],
        "patch_pages": audit["patch_pages"],
        "chain_pages": audit["chain_pages"],
        "models": models,
    }
