"""Stable CLI; implementation lives in focused modules."""

import argparse
import json
from pathlib import Path

from .annotations import import_annotations
from .backends.runner import evaluate
from .benchmark import benchmark, collect_reports
from .charts import augment_charts
from .compatibility import prepare_legacy
from .compatibility.cleaning import CleaningOptions
from .exporters import export_gt, export_predictions
from .feature_evaluation.feature_eval import build_feature_ground_truth, evaluate_features
from .feature_evaluation.feature_matrix import build_feature_ir, evaluate_feature_matrix
from .feature_evaluation.feature_rubric import evaluate_feature_rubric
from .history import compare_workbook
from .pipeline import run as run_profile
from .predictions import MODELS, import_predictions
from .quality import audit_quality
from .repetition import audit_repetition


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="docbench", description="混合文档解析评测")
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", help="按配置选择数据和评测器，standard / legacy 仅选择前处理")
    run.add_argument("config", type=Path)
    run.add_argument(
        "--legacy",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="启用图表 details 展开和 base64 图片替换预设；不改变数据或评测器",
    )
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
    feature_gt = sub.add_parser(
        "build-feature-gt",
        help="从 legacy-129-markdown-v1 与 legacy-129-annotated-v2 建立 legacy-129-feature-v3",
    )
    feature_gt.add_argument("new_source", type=Path, help="新 GT tar 包或已解压目录")
    feature_gt.add_argument("old_groundtruth", type=Path, help="旧 129 Markdown GT 目录")
    feature_gt.add_argument("output", type=Path, help="新的四项能力 GT 输出目录")
    feature_gt.add_argument("--old-pdf-dir", type=Path, help="旧 129 PDF 目录，用于页数对账")
    feature_gt.add_argument("--appendix-overrides", type=Path, help="人工复核的附录页码补丁 JSON")
    feature_gt.add_argument("--block-overrides", type=Path, help="人工复核的专项 GT 块补丁 JSON")
    feature_gt.add_argument("--dataset-version", default="legacy-features-20261119")
    feature_gt.add_argument(
        "--include-structured",
        action="store_true",
        help="额外保留展开的 structured/ 文档；默认只生成轻量 feature-v3 GT",
    )
    feature_eval = sub.add_parser(
        "evaluate-features",
        help="评测附录、页眉页脚、image analysis、chart analysis 四项能力",
    )
    feature_eval.add_argument("--gt", type=Path, required=True, help="build-feature-gt 输出目录")
    feature_eval.add_argument(
        "--pred",
        type=Path,
        required=True,
        help="PDF2Text 响应 JSON、统一 IR documents/ 或 Markdown 目录",
    )
    feature_eval.add_argument("--output", type=Path, required=True)
    feature_eval.add_argument("--allow-missing", action="store_true")
    feature_eval.add_argument(
        "--subset-manifest",
        type=Path,
        help="一次性子集清单 JSON；不指定时评测 v3 全部 129 份",
    )
    feature_eval.add_argument(
        "--subset-name",
        help="子集名称，例如 union、appendix、header_footer、image、chart；默认 union",
    )
    replay = sub.add_parser(
        "build-feature-ir",
        help="从 MinerU raw middle_json 按最新版 PDF2Text 过滤器生成四功能 IR",
    )
    replay.add_argument("--gt", type=Path, required=True, help="legacy-129-feature-v3 GT")
    replay.add_argument("--raw-off", type=Path, help="完整四功能回放所需的 image_analysis=false raw 目录")
    replay.add_argument("--raw-on", type=Path, required=True, help="image_analysis=true raw 目录")
    replay.add_argument("--visual-only", action="store_true", help="只有 raw-B 时，仅回放图片、图表")
    replay.add_argument(
        "--pdf2text-source",
        type=Path,
        required=True,
        help="包含 src/pdf2text/core/parse/mineru_filters.py 的 PDF2Text 源码目录或文件",
    )
    replay.add_argument("--model", default="mineru3", help="raw manifest 中的模型标识")
    replay.add_argument("--output", type=Path, required=True)
    replay.add_argument("--subset-manifest", type=Path)
    matrix = sub.add_parser(
        "evaluate-feature-matrix",
        help="评测四功能 on/off 清除率；独立于主线榜单",
    )
    matrix.add_argument("--gt", type=Path, required=True)
    matrix.add_argument("--pred", type=Path, required=True, help="build-feature-ir 输出目录")
    matrix.add_argument("--output", type=Path, required=True)
    matrix.add_argument(
        "--allow-gt-revision",
        action="store_true",
        help="允许用审阅后的 GT 重评已有 IR；输出 provenance 会记录旧/新 GT 哈希",
    )
    rubric = sub.add_parser("evaluate-feature-rubric", help="按复核证据计算四功能专项交付分")
    rubric.add_argument("--gt", type=Path, required=True, help="冻结的专项计分 GT JSON")
    rubric.add_argument("--pred", type=Path, required=True, help="单版来源对齐的输出证据 JSON")
    rubric.add_argument("--output", type=Path, required=True)
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
    mineru_pages = sub.add_parser("export-mineru-omni", help="恢复原页表格片段并导出 Omni 逐页预测")
    mineru_pages.add_argument("raw", type=Path, help="MinerU 3.x 原始 JSON 文件或目录")
    mineru_pages.add_argument("output", type=Path)
    mineru_pages.add_argument(
        "--pdf2text-config", type=Path, required=True, help="原评测的后处理配置 JSON"
    )
    for command, historical_default, help_text in (
        ("prepare-markdown", False, "独立处理 Markdown；图片替换与 details 清洗分别选择"),
        ("prepare-legacy", True, "历史 fix 预设；默认同时替换图片和清洗 details"),
    ):
        cleaner = sub.add_parser(command, help=help_text)
        cleaner.add_argument("source", type=Path)
        cleaner.add_argument("output", type=Path, help="新的输出目录，不覆盖原始 Markdown")
        cleaner.add_argument(
            "--replace-images",
            dest="replace_embedded_images",
            action=argparse.BooleanOptionalAction,
            default=historical_default,
            help="仅替换嵌入的 base64 图片引用，不恢复坐标、不识别图片内容",
        )
        cleaner.add_argument(
            "--expand-details",
            dest="expand_chart_details",
            action=argparse.BooleanOptionalAction,
            default=historical_default,
            help="应用历史 details 规则，可能以内部内容替掉图片；不启用模型 chart_analysis",
        )
    charts = sub.add_parser("augment-charts", help="从人工审核表格或显式 provider 增强图表")
    charts.add_argument("source", type=Path)
    charts.add_argument("output", type=Path)
    group = charts.add_mutually_exclusive_group(required=True)
    group.add_argument("--tables", type=Path)
    group.add_argument(
        "--provider", nargs="+", help="JSON stdin/stdout provider 命令，不通过 shell"
    )
    charts.add_argument("--pdf-dir", type=Path)
    run = sub.add_parser("evaluate", help="运行原生评测；AgentBuilder 独立榜仅从 OmniDocBench 生成")
    run.add_argument(
        "--backend",
        choices=["OmniDocBench", "MPDocBench", "legacy_compat", "legacy"],
        required=True,
    )
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
    collect = sub.add_parser("collect", help="从已有结果生成三个独立榜，不重跑指标")
    collect.add_argument("reports", type=Path, nargs="+")
    collect.add_argument("--output", type=Path, required=True)
    rescore = sub.add_parser(
        "rescore-agentbuilder", help="评测预测结果或复测冻结的 AgentBuilder-v2 报告"
    )
    rescore.add_argument("--inputs", type=Path, required=True, help="评测输入清单 JSON")
    rescore.add_argument("--output", type=Path, required=True, help="新的结果目录")
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
    repetition = sub.add_parser("audit-repetition", help="检查四模型原始输出的长连续重复并保存证据")
    repetition.add_argument("source", type=Path, help="包含各模型子目录的原始 JSON 目录")
    repetition.add_argument("output", type=Path)
    repetition.add_argument(
        "--evaluated", type=Path, help="prepared/pred/，比较重复是否进入评测 Markdown"
    )
    repetition.add_argument(
        "--ground-truth", type=Path, help="统一 GT documents/，补充重复单元在 GT 中出现次数"
    )
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
            result = run_profile(
                args.config, {key: getattr(args, key) for key in keys}, args.legacy
            )
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
        elif args.command == "build-feature-gt":
            result = build_feature_ground_truth(
                args.new_source,
                args.old_groundtruth,
                args.output,
                args.old_pdf_dir,
                args.dataset_version,
                args.include_structured,
                appendix_overrides=args.appendix_overrides,
                block_overrides=args.block_overrides,
            )
        elif args.command == "evaluate-features":
            result = evaluate_features(
                args.gt,
                args.pred,
                args.output,
                args.allow_missing,
                args.subset_manifest,
                args.subset_name,
            )
        elif args.command == "build-feature-ir":
            result = build_feature_ir(
                args.gt,
                args.raw_off,
                args.raw_on,
                args.pdf2text_source,
                args.model,
                args.output,
                args.subset_manifest,
                visual_only=args.visual_only,
            )
        elif args.command == "evaluate-feature-matrix":
            result = evaluate_feature_matrix(
                args.gt, args.pred, args.output, args.allow_gt_revision
            )
        elif args.command == "evaluate-feature-rubric":
            result = evaluate_feature_rubric(args.gt, args.pred, args.output)
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
        elif args.command == "export-mineru-omni":
            from .mineru_page_export import export_mineru_predictions

            result = export_mineru_predictions(args.raw, args.pdf2text_config, args.output)
        elif args.command in {"prepare-markdown", "prepare-legacy"}:
            result = prepare_legacy(
                args.source,
                args.output,
                CleaningOptions(args.replace_embedded_images, args.expand_chart_details),
            )
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
        elif args.command == "rescore-agentbuilder":
            from .agentbuilder_v2 import rescore_agentbuilder

            result = rescore_agentbuilder(args.inputs, args.output)
        elif args.command == "compare-xlsx":
            result = compare_workbook(args.workbook, args.run, args.tag, args.output)
        elif args.command == "audit-quality":
            result = audit_quality(args.source, args.output, args.legacy_pdfs, args.current_pdfs)
        elif args.command == "audit-repetition":
            result = audit_repetition(args.source, args.output, args.evaluated, args.ground_truth)
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
