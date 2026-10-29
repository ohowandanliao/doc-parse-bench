"""Validate coverage, run pinned evaluators, attach title scores and provenance."""

import hashlib
import os
import shutil
import subprocess
import sys
from pathlib import Path

from ..compatibility import ENGINE_ROOT, PROJECT_ROOT, historical_overall
from ..io import fresh_directory, read_json, sha256, write_json
from ..metrics import compute_title_score, extract_title_lines, finite, summarize


def evaluate(
    backend: str,
    gt: Path,
    predictions: Path,
    output: Path,
    title_gt: Path | None = None,
    allow_missing: bool = False,
    cdm: bool = False,
    figure: bool = False,
    relations: bool = False,
    exact_teds: bool = False,
) -> dict:
    gt, predictions = gt.resolve(), predictions.resolve()
    if (figure or relations) and backend != "MPDocBench":
        raise ValueError("--figure 和 --relations 仅适用于 MPDocBench")
    tex_engine = "pdflatex" if backend == "OmniDocBench" else "xelatex"
    if cdm and shutil.which(tex_engine) is None:
        raise ValueError(f"FormulaCDM 需要 {tex_engine}/TeX Live；当前环境尚未安装")
    gt_manifest_path = gt.parent.parent / "manifest.json"
    pred_manifest_path = predictions.parent / "manifest.json"
    gt_manifest = read_json(gt_manifest_path) if gt_manifest_path.exists() else {}
    pred_manifest = read_json(pred_manifest_path) if pred_manifest_path.exists() else {}
    if gt_manifest.get("chart_policy") and pred_manifest.get("chart_policy"):
        if gt_manifest["chart_policy"] != pred_manifest["chart_policy"]:
            raise ValueError("GT 和预测的 chart_policy 不一致")
    root = (
        PROJECT_ROOT
        / "vendor"
        / ("OmniDocBench" if backend == "OmniDocBench" else "Qwen-Doc/MPDocBench")
        if backend != "legacy"
        else ENGINE_ROOT
    )
    if not root.is_dir():
        raise ValueError("缺少评测子模块，请运行 git submodule update --init --recursive")
    if backend == "legacy":
        expected = {p.name for p in gt.glob("*.md")}
        title_gt = gt
    else:
        expected = {Path(s["page_info"]["image_path"]).stem + ".md" for s in read_json(gt)}
    if not expected:
        raise ValueError("GT 为空")
    existing = {p.name for p in predictions.glob("*.md")}
    missing, extra = sorted(expected - existing), sorted(existing - expected)
    if missing and not allow_missing:
        raise ValueError(
            f"缺少 {len(missing)}/{len(expected)} 份预测，例如 {missing[:3]}；"
            "补齐结果或使用 --allow-missing 将缺失计为空预测"
        )
    if title_gt is None:
        raise ValueError("需要 --title-gt 指向导出的对应 benchmark Markdown GT")
    if any(not (title_gt / name).is_file() for name in expected):
        raise ValueError("title GT 与结构化 GT 文件集合不一致")
    output = fresh_directory(output)
    staged = output / "predictions"
    staged.mkdir()
    prediction_hashes = {}
    for name in sorted(expected):
        source = predictions / name
        if source.exists():
            shutil.copyfile(source, staged / name)
            prediction_hashes[name] = sha256(source)
        else:
            (staged / name).write_text("", encoding="utf-8")
            prediction_hashes[name] = None
    metrics = {
        "text_block": {"metric": ["Edit_dist"]},
        "display_formula": {"metric": ["Edit_dist"] + (["CDM"] if cdm else [])},
        "table": {"metric": ["TEDS", "Edit_dist"]},
        "reading_order": {"metric": ["Edit_dist"]},
    }
    if backend == "MPDocBench":
        metrics.update(
            {
                "merged_text_block": {"metric": ["Edit_dist"]},
                "merged_table": {"metric": ["TEDS", "Edit_dist"]},
                "head": {"metric": ["HeadTEDS"]},
            }
        )
        if figure:
            metrics["figure"] = {"metric": ["FigureF1"]}
        if relations:
            metrics["table_relation"] = {"metric": ["Relation_F1"]}
            metrics["text_relation"] = {"metric": ["Relation_F1"]}
    config = {
        "enable_cdm": cdm,
        "exact_teds": exact_teds,
        "end2end_eval": {
            "metrics": metrics,
            "dataset": {
                "dataset_name": "md2md_dataset" if backend == "legacy" else "end2end_dataset",
                "ground_truth": {"data_path": str(gt)},
                "prediction": {"data_path": str(staged)},
                "match_method": "quick_match",
                "match_workers": 1,
            },
        },
    }
    write_json(output / "config.json", config)
    runtime = output / "runtime"
    runtime.mkdir()
    env = {
        **os.environ,
        "MPLCONFIGDIR": str(output / "cache/matplotlib"),
        "HF_HOME": str(PROJECT_ROOT / ".cache/huggingface"),
        "TOKENIZERS_PARALLELISM": "false",
    }
    cmd = [
        sys.executable,
        "-m",
        "doc_parse_bench.backends.worker",
        backend,
        str(root),
        str(output / "config.json"),
    ]
    with (output / "evaluation.log").open("w", encoding="utf-8") as log:
        proc = subprocess.run(cmd, cwd=runtime, stdout=log, stderr=subprocess.STDOUT, env=env)
    if proc.returncode:
        tail = (output / "evaluation.log").read_text(encoding="utf-8")[-4500:]
        raise RuntimeError(f"{backend} 评测失败，日志：{output / 'evaluation.log'}\n{tail}")
    results = list(runtime.rglob("*metric_result.json"))
    if len(results) != 1:
        raise RuntimeError(f"无法唯一定位评测结果：{results}")
    raw = read_json(results[0])
    scores = {}
    for name in sorted(expected):
        reference = (title_gt / name).read_text(encoding="utf-8")
        pred = (staged / name).read_text(encoding="utf-8")
        scores[Path(name).stem] = {
            "title": compute_title_score(extract_title_lines(reference), extract_title_lines(pred))
        }
    title_scores = [s["title"] for s in scores.values() if s["title"] is not None]
    title = round(sum(title_scores) / len(title_scores), 4) if title_scores else None
    flat = summarize(raw, title)
    _attach_element_scores(results[0].parent, backend, scores)
    for values in scores.values():
        weights = {
            "text_accuracy": 0.3,
            "table_teds": 0.3,
            "reading_order_accuracy": 0.3,
            "title": 0.1,
        }
        present = {k: w for k, w in weights.items() if values.get(k) is not None}
        values["agentbuilder_overall"] = (
            round(sum(values[k] * w for k, w in present.items()) / sum(present.values()), 4)
            if present
            else None
        )
    # Keep old JSON names as aliases for consumers of the historical pipeline.
    if backend == "legacy":
        aliases = {
            "text_block": "text_accuracy",
            "table": "table_accuracy",
            "reading_order": "reading_order_accuracy",
            "formula": "formula_accuracy",
        }
        flat.update(
            {
                key: round(flat[value], 4) if flat.get(value) is not None else None
                for key, value in aliases.items()
            }
        )
        historical = {"overall": historical_overall(raw)}
        flat["legacy_stage_overall"] = historical.get("overall")
        flat["overall"] = historical.get("overall")
        for values in scores.values():
            values.update(
                {
                    key: round(values[value], 4) if values.get(value) is not None else None
                    for key, value in aliases.items()
                }
            )
            values["overall"] = values.get("agentbuilder_overall")
    commit = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "HEAD"], text=True, capture_output=True
    )
    provenance = {
        "backend": backend,
        "commit": commit.stdout.strip() if commit.returncode == 0 else "vendored-legacy",
        "expected": len(expected),
        "provided": len(expected) - len(missing),
        "missing_as_empty": missing,
        "extra_ignored": extra,
        "prediction_sha256": prediction_hashes,
        "prediction_manifest": pred_manifest,
        "gt_manifest_sha256": sha256(gt_manifest_path) if gt_manifest else None,
        "gt_sha256": sha256(gt) if gt.is_file() else {p.name: sha256(p) for p in gt.glob("*.md")},
        "cdm_enabled": cdm,
        "title_metric": "historical-v1; level=.3/content=.7",
        "figure_enabled": figure,
        "relation_metrics_enabled": relations,
        "teds_solver": "compiled-exact-tree-edit" if exact_teds else "upstream-apted",
        "complete_official_score": cdm and (backend != "MPDocBench" or figure),
    }
    if backend == "legacy":
        fingerprint = hashlib.sha256()
        for path in sorted(ENGINE_ROOT.rglob("*.py")):
            fingerprint.update(str(path.relative_to(ENGINE_ROOT)).encode())
            fingerprint.update(path.read_bytes())
        provenance["compatibility_engine_sha256"] = fingerprint.hexdigest()
        provenance["complete_official_score"] = False
    write_json(output / "metrics.json", flat)
    write_json(output / "per_doc_scores.json", scores)
    write_json(output / "provenance.json", provenance)
    rows = "\n".join(
        f"| {key} | {value:.6f} |" if value is not None else f"| {key} | unavailable |"
        for key, value in flat.items()
    )
    (output / "report.md").write_text(
        f"# {backend} 评测\n\n覆盖率：{len(expected) - len(missing)}/{len(expected)}；"
        f"缺失按空预测：{len(missing)}。\n\n| 指标 | 得分 |\n| --- | --- |\n{rows}\n\n"
        "FormulaCDM 未计算时官方 Overall 留空。FigureF1 和关系指标按本次配置启用。\n",
        encoding="utf-8",
    )
    return flat


def _attach_element_scores(directory: Path, backend: str, scores: dict) -> None:
    prefix = "" if backend == "MPDocBench" else "eval_"
    modules = {
        "text_block": "text",
        "reading_order": "reading_order",
        "table": "table",
        "display_formula": "formula",
        "merged_text_block": "merged_text",
        "merged_table": "merged_table",
        "head": "head",
        "figure": "figure",
        "table_relation": "table_relation",
        "text_relation": "text_relation",
    }
    for module, name in modules.items():
        per_page = directory / f"{prefix}{module}_per_page_edit.json"
        if per_page.exists():
            for key, value in read_json(per_page).items():
                stem = Path(key).stem
                if stem in scores and (value := finite(value)) is not None:
                    scores[stem][f"{name}_edit"] = value
                    scores[stem][f"{name}_accuracy"] = 1 - value
        path = directory / f"{prefix}{module}_result.json"
        if not path.exists():
            continue
        groups = {}
        for sample in read_json(path):
            img_id = sample.get("img_id", "")
            stem = Path(img_id).stem
            # Formula IDs add a numeric suffix after .jpg / .pdf.
            if stem not in scores:
                stem = Path(img_id.rsplit("_", 1)[0]).stem
            if stem not in scores:
                continue
            for metric, suffix in (
                ("TEDS", "teds"),
                ("TEDS_structure_only", "teds_s"),
                ("HeadTEDS", "teds"),
                ("CDM", "cdm"),
                ("FigureF1", "f1"),
                ("Relation_F1", "f1"),
            ):
                value = finite(sample.get("metric", {}).get(metric))
                if value is not None:
                    groups.setdefault((stem, f"{name}_{suffix}"), []).append(value)
        for (stem, metric), values in groups.items():
            scores[stem][metric] = sum(values) / len(values)
