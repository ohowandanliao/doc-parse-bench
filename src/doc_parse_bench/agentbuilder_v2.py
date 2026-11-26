"""Re-score frozen predictions with both historical headings and AgentBuilder-v2."""

import csv
import importlib.util
from pathlib import Path
from statistics import mean

from .backends.runner import evaluate
from .heading import (
    TITLE_TREE_VERSION,
    compare_heading_trees,
    extract_headings,
    gt_heading_tree,
    markdown_heading_tree,
)
from .io import fresh_directory, read_json, safe_name, sha256, write_json
from .metrics import (
    AGENTBUILDER_V2_WEIGHTS,
    agentbuilder_score,
    agentbuilder_v2_score,
    compute_title_score,
    extract_title_lines,
    normalize_report_metrics,
)
from .mineru_page_export import export_mineru_predictions


def _checked_predictions(directory, provenance, expected, gt_hash):
    if provenance["gt_sha256"] != gt_hash:
        raise ValueError(f"评分报告与本次 GT 不一致：{directory}")
    hashes = provenance["prediction_sha256"]
    if set(hashes) != set(expected):
        raise ValueError(f"预测清单与固定 GT 集合不一致：{directory}")
    values = {}
    for name, original_hash in sorted(hashes.items()):
        safe_name(name)
        path = directory / name
        if original_hash is None:
            if path.exists() and path.read_text(encoding="utf-8").strip():
                raise ValueError(f"原记录缺失的预测出现非空内容：{path}")
            values[name] = ""
        else:
            if not path.is_file() or sha256(path) != original_hash:
                raise ValueError(f"预测与历史 SHA256 不一致：{path}")
            values[name] = path.read_text(encoding="utf-8")
    return values


def _native_head_metric(root):
    source = root / "vendor/Qwen-Doc/MPDocBench/metrics/head_metric.py"
    spec = importlib.util.spec_from_file_location("retest_native_heading", source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.HeadTEDS(), source


def _native_retest(root, report, gold_samples, native):
    provenance = read_json(report / "provenance.json")
    source_report = root / provenance.get("completion", {}).get("source_report", report)
    files = list((source_report / "runtime").rglob("head_result.json"))
    if len(files) != 1:
        raise ValueError(f"无法唯一定位原生标题输入对：{source_report}")
    samples = read_json(files[0])
    results = {}
    for sample in samples:
        name = Path(sample["img_id"]).stem
        if name in results or name not in gold_samples:
            raise ValueError(f"原生标题输入对有重复或多余文档：{name}")
        gold = gold_samples[name]
        nodes = {n["anno_id"]: n for n in gold["layout_dets"] if n["category_type"] == "title"}
        relations = [
            r
            for r in gold["extra"]["relation"]
            if r["relation_type"] == "parent_son"
            and (r["source_anno_id"] == "root" or r["source_anno_id"] in nodes)
            and r["target_anno_id"] in nodes
        ]
        if sample["gt"] != [relations, nodes]:
            raise ValueError(f"冻结标题输入对的 GT 不一致：{name}")
        prediction = sample.get("norm_pred") or sample["pred"]
        reference = sample.get("norm_gt") or sample["gt"]
        value, _ = native.evaluate(prediction, reference)
        if abs(value - sample["metric"]["HeadTEDS"]) > 1e-10:
            raise ValueError(f"原生 HeadTEDS 逐文档复算不一致：{name}")
        results[name] = float(value)
    if set(results) != set(gold_samples):
        raise ValueError("原生标题输入对不包含完整固定文档集合")
    return results, files[0]


def _write_csv(path, rows):
    fields = list(dict.fromkeys(key for row in rows for key in row))
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def _evaluate_models(
    inputs: Path,
    settings: dict,
    root: Path,
    gt: Path,
    gold_trees: dict,
    gt_self: list,
    output: Path,
) -> dict:
    models = {safe_name(config["model"]): config for config in settings["models"]}
    if not models or len(models) != len(settings["models"]):
        raise ValueError("评测模型列表为空或含重复名称")
    for model, config in models.items():
        if bool(config.get("raw")) == bool(config.get("predictions")):
            raise ValueError(f"{model} 需要指定 raw 或 predictions 路径之一")
        if config.get("raw") and not settings.get("pdf2text_config"):
            raise ValueError(f"{model} 的 MinerU 原始响应需要 pdf2text_config")
    omni_gt = gt / "OmniDocBench/gt.json"
    page_names = [Path(sample["page_info"]["image_path"]).stem for sample in read_json(omni_gt)]
    page_documents = {name.rsplit("__p", 1)[0] for name in page_names}
    if (
        not page_names
        or len(page_names) != len(set(page_names))
        or page_documents != set(gold_trees)
    ):
        raise ValueError("OmniDocBench 页面和 MPDocBench 标题的 GT 文档范围不一致")

    output = fresh_directory(output)
    write_json(output / "gt_self_check.json", gt_self)
    allow_missing = settings.get("allow_missing", False)
    rows = []
    for model, config in models.items():
        directory = output / model
        restored_tables = None
        if config.get("raw"):
            prepared = directory / "prepared"
            export = export_mineru_predictions(
                root / config["raw"],
                root / settings["pdf2text_config"],
                prepared,
                include_documents=True,
            )
            restored_tables = export["restored_tables"]
        else:
            prepared = root / config["predictions"]
        if any(not (prepared / backend).is_dir() for backend in ("OmniDocBench", "MPDocBench")):
            raise ValueError(
                f"{model} 的预测目录需要 OmniDocBench 和 MPDocBench 子目录：{prepared}"
            )
        report = directory / "OmniDocBench"
        metrics = evaluate(
            "OmniDocBench",
            omni_gt,
            prepared / "OmniDocBench",
            report,
            title_gt=gt / "OmniDocBench/markdown",
            allow_missing=allow_missing,
            exact_teds=settings.get("exact_teds", True),
        )
        document_scores = []
        for name, tree in sorted(gold_trees.items()):
            path = prepared / "MPDocBench" / f"{safe_name(name)}.md"
            if path.is_file():
                prediction = path.read_text(encoding="utf-8")
                prediction_hash = sha256(path)
            elif allow_missing:
                prediction = ""
                prediction_hash = None
            else:
                raise ValueError(f"{model} 缺少全文预测：{name}")
            document_scores.append(
                {
                    "document": name,
                    "prediction_sha256": prediction_hash,
                    **compare_heading_trees(tree, markdown_heading_tree(prediction)),
                }
            )
        title_tree = mean(item["title_tree_v2"] for item in document_scores)
        v2_metrics = {
            "text_accuracy": metrics.get("text_accuracy"),
            "table_teds": metrics.get("table_teds"),
            "reading_order_accuracy": metrics.get("reading_order_accuracy"),
            "title_tree_v2": title_tree,
        }
        total = agentbuilder_v2_score(v2_metrics, "OmniDocBench")
        coverage = read_json(report / "provenance.json")
        row = {
            "model": model,
            "documents": len(gold_trees),
            "provided_pages": coverage["provided"],
            "expected_pages": coverage["expected"],
            "restored_tables": restored_tables,
            **v2_metrics,
            "agentbuilder_v2_overall": total,
        }
        rows.append(row)
        write_json(directory / "documents.json", document_scores)
        write_json(directory / "metrics.json", row)

    rows.sort(
        key=lambda row: (
            row["agentbuilder_v2_overall"] is None,
            -(row["agentbuilder_v2_overall"] or 0),
            row["model"],
        )
    )
    write_json(output / "summary.json", rows)
    _write_csv(output / "summary.csv", rows)
    write_json(
        output / "verification.json",
        {
            "agentbuilder_version": "AgentBuilder-v2",
            "metric_version": TITLE_TREE_VERSION,
            "weights": AGENTBUILDER_V2_WEIGHTS,
            "inputs_sha256": sha256(inputs),
            "gt_sha256": {
                backend: sha256(gt / backend / "gt.json")
                for backend in ("OmniDocBench", "MPDocBench")
            },
        },
    )
    return {
        "models": len(rows),
        "documents_per_model": len(gold_trees),
        "summary": str(output / "summary.json"),
    }


def rescore_agentbuilder(inputs: Path, output: Path) -> dict:
    """Evaluate predictions or reproduce archived AgentBuilder-v2 scores."""
    inputs = inputs.resolve()
    settings = read_json(inputs)
    root = (inputs.parent / settings["base_directory"]).resolve()
    gt = root / settings["gt"]
    gold_samples = read_json(gt / "MPDocBench/gt.json")
    gold = {Path(sample["page_info"]["image_path"]).stem: sample for sample in gold_samples}
    if len(gold) != len(gold_samples):
        raise ValueError("MPDocBench GT 含重复文档")
    gold_trees = {name: gt_heading_tree(sample) for name, sample in gold.items()}
    gt_self = []
    for name in sorted(gold):
        markdown = (gt / "MPDocBench/markdown" / f"{name}.md").read_text()
        result = compare_heading_trees(gold_trees[name], markdown_heading_tree(markdown))
        gt_self.append({"document": name, **result})
        if result["title_tree_v2"] != 1:
            raise ValueError(f"GT 标题适配自比较不满分：{name}")
    if "scores" not in settings:
        return _evaluate_models(inputs, settings, root, gt, gold_trees, gt_self, output)
    if any("raw" in config for config in settings["models"]):
        raise ValueError("原始响应评测清单中的 raw 与归档复测的 scores 不能同时设置")

    originals = read_json(root / settings["scores"])
    pages = sorted(p.name for p in (gt / "OmniDocBench/markdown").glob("*.md"))
    gold_page_text = {name: (gt / "OmniDocBench/markdown" / name).read_text() for name in pages}
    native, native_source = _native_head_metric(root)
    output = fresh_directory(output)
    write_json(output / "gt_self_check.json", gt_self)
    rows, verification = [], []
    for config in settings["models"]:
        model = safe_name(config["model"])
        matching = [r for r in originals if r["model"] == model]
        pair = {r["backend"]: r for r in matching}
        if len(matching) != 2 or set(pair) != {"OmniDocBench", "MPDocBench"}:
            raise ValueError(f"每个模型应恰有一份页面报告和文档报告：{model}")
        reports = {backend: root / row["source_report"] for backend, row in pair.items()}
        predictions = {}
        for backend, report in reports.items():
            stored_metrics = read_json(report / "metrics.json")
            required_metrics = (
                [
                    "text_accuracy",
                    "table_teds",
                    "reading_order_accuracy",
                    "title",
                    "agentbuilder_overall",
                ]
                if backend == "OmniDocBench"
                else ["head_teds", "mpdocbench_overall"]
            )
            if any(stored_metrics.get(key) != pair[backend].get(key) for key in required_metrics):
                raise ValueError(f"汇总清单与来源报告分项不一致：{model}/{backend}")
            predictions[backend] = _checked_predictions(
                root / config["predictions"] / backend,
                read_json(report / "provenance.json"),
                pages if backend == "OmniDocBench" else [f"{name}.md" for name in gold],
                sha256(gt / backend / "gt.json"),
            )
        old_pages = [
            {
                "page": name,
                "title": compute_title_score(
                    extract_title_lines(gold_page_text[name]),
                    extract_title_lines(predictions["OmniDocBench"][name]),
                ),
            }
            for name in pages
        ]
        stored_pages = read_json(reports["OmniDocBench"] / "per_doc_scores.json")
        for page in old_pages:
            if page["title"] != stored_pages[Path(page["page"]).stem]["title"]:
                raise ValueError(f"历史 title 逐页复算不一致：{model}/{page['page']}")
        applicable = [p["title"] for p in old_pages if p["title"] is not None]
        old_title = round(mean(applicable), 4) if applicable else None
        if old_title != pair["OmniDocBench"]["title"]:
            raise ValueError(f"历史页面 title 复算不一致：{model}/{old_title}")
        native_scores, native_inputs = _native_retest(root, reports["MPDocBench"], gold, native)
        if abs(mean(native_scores.values()) - pair["MPDocBench"]["head_teds"]) > 1e-10:
            raise ValueError(f"历史 HeadTEDS 总分复算不一致：{model}")
        document_scores = []
        for name in sorted(gold):
            prediction = predictions["MPDocBench"][f"{name}.md"]
            result = compare_heading_trees(gold_trees[name], markdown_heading_tree(prediction))
            document_scores.append(
                {
                    "document": name,
                    **result,
                    "native_head_teds_retest": native_scores[name],
                    "predicted_headings": extract_headings(prediction),
                }
            )
        title_tree = mean(r["title_tree_v2"] for r in document_scores)
        old_metrics = {**pair["OmniDocBench"], "title": old_title}
        old_overall = agentbuilder_score(old_metrics)
        if old_overall != pair["OmniDocBench"]["agentbuilder_overall"]:
            raise ValueError(f"历史 AgentBuilder 总分复算不一致：{model}")
        total = agentbuilder_v2_score({**old_metrics, "title_tree_v2": title_tree}, "OmniDocBench")
        if total is None:
            raise ValueError(f"AgentBuilder-v2 缺少必要分项：{model}")
        mp_overall = normalize_report_metrics(
            {**pair["MPDocBench"], "head_teds": mean(native_scores.values())}, "MPDocBench"
        )["mpdocbench_overall"]
        if abs(mp_overall - pair["MPDocBench"]["mpdocbench_overall"]) > 1e-10:
            raise ValueError(f"历史 MP Overall 复算不一致：{model}")

        def group(predicate):
            values = [r["title_tree_v2"] for r in document_scores if predicate(r["gt_headings"])]
            return mean(values) if values else None

        row = {
            "model": model,
            "model_display_name": pair["OmniDocBench"].get("model_display_name", model),
            "treatment": pair["OmniDocBench"].get("treatment", "原始"),
            "preprocessing_profile": pair["OmniDocBench"]["preprocessing_profile"],
            "documents": len(gold),
            "provided_pages": pair["OmniDocBench"]["provided"],
            "expected_pages": len(pages),
            "text_accuracy": old_metrics["text_accuracy"],
            "table_teds": old_metrics["table_teds"],
            "reading_order_accuracy": old_metrics["reading_order_accuracy"],
            "historical_title_retest": old_title,
            "historical_title_applicable_pages": len(applicable),
            "native_head_teds_retest": mean(native_scores.values()),
            "head_teds_same_input": mean(r["head_teds_same_input"] for r in document_scores),
            "title_tree_v2": title_tree,
            "title_tree_v2_positive": group(lambda n: n > 0),
            "title_tree_v2_no_heading": group(lambda n: n == 0),
            "title_tree_v2_small_tree": group(lambda n: 1 <= n <= 3),
            "clipped_documents": sum(r["clipped"] for r in document_scores),
            "historical_agentbuilder_retest": old_overall,
            "agentbuilder_v2_overall": total,
            "overall_delta": total - old_overall,
            "mpdocbench_overall_retest": mp_overall,
        }
        rows.append(row)
        directory = output / model
        write_json(directory / "documents.json", document_scores)
        write_json(directory / "historical_pages.json", old_pages)
        write_json(directory / "metrics.json", row)
        verification.append(
            {
                "model": model,
                "prediction_hashes_verified": {k: len(v) for k, v in predictions.items()},
                "old_title_equal": True,
                "old_title_per_page_equal": True,
                "old_agentbuilder_equal": True,
                "old_head_teds_equal": True,
                "old_mp_overall_equal": True,
                "native_metric_input_sha256": sha256(native_inputs),
                "source_reports": {
                    k: {
                        "metrics": sha256(p / "metrics.json"),
                        "provenance": sha256(p / "provenance.json"),
                    }
                    for k, p in reports.items()
                },
            }
        )
        print(f"{model}: old={old_overall:.4f}, v2={total:.4f}, title={title_tree:.4f}", flush=True)
    old_order = sorted(rows, key=lambda r: (-r["historical_agentbuilder_retest"], r["model"]))
    old_ranks = {r["model"]: i for i, r in enumerate(old_order, 1)}
    rows.sort(key=lambda r: (-r["agentbuilder_v2_overall"], r["model"]))
    for rank, row in enumerate(rows, 1):
        row.update(rank_v2=rank, rank_old=old_ranks[row["model"]])
    write_json(output / "summary.json", rows)
    _write_csv(output / "summary.csv", rows)
    write_json(
        output / "verification.json",
        {
            "metric_version": TITLE_TREE_VERSION,
            "agentbuilder_version": "AgentBuilder-v2",
            "weights": AGENTBUILDER_V2_WEIGHTS,
            "missing_component_policy": "unavailable; no weight redistribution",
            "scope": "Fresh old/new heading distances and totals; verified existing content metrics reused",
            "gt_self_check_perfect": len(gt_self),
            "gt_documents": len(gold),
            "gt_pages": len(pages),
            "gt_headings": sum(tree[1] for tree in gold_trees.values()),
            "inputs_sha256": sha256(inputs),
            "gt_sha256": {k: sha256(gt / k / "gt.json") for k in ["OmniDocBench", "MPDocBench"]},
            "source_sha256": {
                p.name: sha256(p)
                for p in [
                    Path(__file__),
                    Path(__file__).with_name("heading.py"),
                    Path(__file__).with_name("metrics.py"),
                    native_source,
                ]
            },
            "models": verification,
        },
    )
    lines = [
        "# AgentBuilder-v2：81 份文档复测",
        "",
        "文本、表格 TEDS、阅读顺序采用经输入哈希核验的既有 Omni 页面分项；标题改用完整文档 TitleTree-v2。",
        "权重为 0.3／0.3／0.3／0.1，四项必须齐全。以下旧 title、旧 HeadTEDS 与旧总分均已重新计算并与存档一致。",
        "旧 HeadTEDS 重新运行原生距离函数，输入为存档提取结果；本次未重新运行全文内容匹配、OCR 或 RAG。",
        "",
        "| 模型 | 处理 | 旧排名→v2 | 旧 title | 原生 HeadTEDS | 规范输入含 root 分 | TitleTree-v2 | 旧总分 | v2 总分 | 变化 |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for r in rows:
        lines.append(
            f"| {r['model_display_name']} | {r['treatment']} | {r['rank_old']}→{r['rank_v2']} | "
            f"{r['historical_title_retest']:.4f} | {r['native_head_teds_retest']:.4f} | "
            f"{r['head_teds_same_input']:.4f} | {r['title_tree_v2']:.4f} | "
            f"{r['historical_agentbuilder_retest']:.4f} | {r['agentbuilder_v2_overall']:.4f} | "
            f"{r['overall_delta']:+.4f} |"
        )
    lines += [
        "",
        "规范输入含 root 分与 v2 使用完全相同的树和距离，仅分母与下界处理不同；该列不是官方 MPDocBench 成绩。",
        "75 份含标题／6 份无标题分组、1–3 标题分组、截断数量及全部旧分核对见 summary.csv／verification.json。",
    ]
    (output / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {
        "models": len(rows),
        "documents_per_model": len(gold),
        "summary": str(output / "summary.md"),
    }
