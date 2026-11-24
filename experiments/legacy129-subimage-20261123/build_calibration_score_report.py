"""Combine the reviewed legacy-129 evidence and write one calibration report.

This command never calls a model.  It only combines evidence already saved by
the appendix/header-footer, chart, and image-control replays, then runs the
source-aligned rubric scorer against the unchanged pilot GT.  Missing image
evidence stays missing; it is never converted to a zero or averaged away.
"""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

from doc_parse_bench.feature_rubric import (
    CONFIG,
    EVIDENCE_SCHEMA,
    RUBRIC_VERSION,
    evaluate_feature_rubric,
)
from doc_parse_bench.io import fresh_directory, read_json, sha256, write_json


def _relative(path: Path, root: Path) -> str:
    return str(path.resolve().relative_to(root.resolve()))


def _combine(
    *,
    root: Path,
    gt_path: Path,
    model: str,
    sources: list[Path],
    output: Path,
) -> Path:
    cases: dict[str, dict] = {}
    captures: dict[str, dict] = {}
    source_rows = []
    expected = {case["id"]: case for case in read_json(gt_path)["cases"]}
    for source in sources:
        evidence = read_json(source)
        if evidence.get("schema_version") != EVIDENCE_SCHEMA or evidence.get("stage") != "replay":
            raise ValueError(f"not replay rubric evidence: {source}")
        if any(evidence.get("config", {}).get(key) != value for key, value in CONFIG.items()):
            raise ValueError(f"incompatible source config: {source}")
        source_gt_path = source.with_name(
            "image-controls-gt.json" if source.name.endswith("-images.json") else "gt.json"
        )
        if evidence.get("gt_sha256") != sha256(source_gt_path):
            raise ValueError(f"source GT hash mismatch: {source}")
        subset = {case["id"]: case for case in read_json(source_gt_path)["cases"]}
        if any(expected.get(key) != case for key, case in subset.items()):
            raise ValueError(f"source GT is not an unchanged pilot subset: {source_gt_path}")
        for case_id, observation in evidence.get("cases", {}).items():
            if case_id not in subset:
                raise ValueError(f"source evidence outside source GT: {case_id}")
            if case_id in cases:
                raise ValueError(f"duplicate evidence case: {case_id}")
            cases[case_id] = observation
        for document_id, groups in (evidence.get("captures") or {}).items():
            existing = captures.setdefault(document_id, {})
            for group, digest in groups.items():
                if group in existing and existing[group] != digest:
                    raise ValueError(f"capture mismatch: {document_id}/{group}")
                existing[group] = digest
        source_rows.append(
            {
                "path": _relative(source, root),
                "sha256": sha256(source),
                "source_model": evidence.get("model"),
                "stage": evidence.get("stage"),
                "gt_path": _relative(source_gt_path, root),
                "gt_sha256": sha256(source_gt_path),
            }
        )

    combined = {
        "schema_version": EVIDENCE_SCHEMA,
        "gt_sha256": sha256(gt_path),
        "model": model,
        "stage": "replay",
        "relevel_applied": False,
        "config": CONFIG,
        "cases": cases,
        "captures": captures,
        "source_evidence": source_rows,
        "scope_note": (
            "组合已有 replay 证据；未覆盖的 GT case 保持 evidence_missing，不代表模型失败。"
        ),
    }
    destination = output / "evidence" / f"{model}.json"
    write_json(destination, combined)
    return destination


def _source_paths(root: Path, model: str) -> list[Path]:
    if model == "3.1-ft":
        switch = "ft-evidence.json"
        chart = "ft-adapted-evidence.json"
        image = "ft-adapted-images.json"
        flow = "ft-evidence.json"
    elif model == "3.1-origin":
        switch = "origin-evidence.json"
        chart = "origin-evidence.json"
        image = "origin-6docs-images.json"
        flow = "origin-evidence.json"
    else:
        raise ValueError(f"unsupported model: {model}")
    return [
        root / "artifacts/legacy129-subimage-20261123/rubric-switches" / switch,
        root / "artifacts/legacy129-subimage-20261123/rubric-charts/all-pilot-charts" / chart,
        root / "artifacts/legacy129-subimage-20261123/model-gap-v2" / image,
        root
        / "artifacts/legacy129-subimage-20261123/analysis-units-review-20261124/flowchart-bc108"
        / flow,
    ]


def _copy_image_control_scope(root: Path, output: Path, model: str) -> None:
    source_dir = root / "artifacts/legacy129-subimage-20261123/model-gap-v2"
    gt_source = source_dir / "image-controls-gt.json"
    evidence_source = (
        source_dir
        / {
            "3.1-ft": "ft-adapted-images.json",
            "3.1-origin": "origin-6docs-images.json",
        }[model]
    )
    scope = output / "image-controls" / model
    scope.mkdir(parents=True, exist_ok=True)
    gt = read_json(gt_source)
    evidence = read_json(evidence_source)
    gt_path = scope / "gt.json"
    write_json(gt_path, gt)
    evidence["gt_sha256"] = sha256(gt_path)
    evidence["model"] = model
    evidence["scope_note"] = (
        "6 个图片控制 case 的校准子集；缺少 text_image 与 seal，因此不产生图片专项总分。"
    )
    evidence_path = scope / "evidence.json"
    write_json(evidence_path, evidence)
    evaluate_feature_rubric(gt_path, evidence_path, scope / "scores")


def _copy_flow_scope(root: Path, output: Path, model: str) -> None:
    source_dir = (
        root
        / "artifacts/legacy129-subimage-20261123/analysis-units-review-20261124/flowchart-bc108"
    )
    gt_source = source_dir / "gt.json"
    evidence_source = (
        source_dir
        / {
            "3.1-ft": "ft-evidence.json",
            "3.1-origin": "origin-evidence.json",
        }[model]
    )
    scope = output / "flowchart-bc108" / model
    scope.mkdir(parents=True, exist_ok=True)
    gt = read_json(gt_source)
    evidence = read_json(evidence_source)
    gt_path = scope / "gt.json"
    write_json(gt_path, gt)
    evidence["gt_sha256"] = sha256(gt_path)
    evidence["model"] = model
    evidence_path = scope / "evidence.json"
    write_json(evidence_path, evidence)
    evaluate_feature_rubric(gt_path, evidence_path, scope / "scores")


def _summary_markdown(output: Path, gt_path: Path, metrics: dict[str, dict]) -> None:
    lines = [
        "# Legacy 129 校准评分报告",
        "",
        "本报告只重用已保存的 replay 证据，不新增模型请求。GT 和四项评分口径没有在本次合成中改动。",
        "",
        "- GT：`gt/rubric-pilot-gt.json`",
        f"- GT SHA-256：`{sha256(gt_path)}`",
        "- GT split：`calibration`；因此不输出正式四项总分。",
        "- 目标配置：MinerU3、`relevel_titles=true`、`title_rules=false`；历史回放实际未执行标题重排。",
        "",
        "## 可评分分项",
        "",
        "| 模型 | 专项 | 分数 | 证据覆盖 | 状态 | 备注 |",
        "| --- | --- | ---: | ---: | --- | --- |",
    ]
    labels = {
        "appendix": "附录",
        "header_footer": "页眉页脚",
        "image": "图片与印章",
        "chart": "图表",
    }
    for model, report in metrics.items():
        for feature, values in report["features"].items():
            coverage = values["coverage"]
            score = "—" if values["score"] is None else f"{values['score']:.2f}"
            rate = "—" if coverage["rate"] is None else f"{coverage['rate']:.1f}%"
            note = "校准分项" if values["score"] is not None else "证据不足，不能记为 0"
            lines.append(
                f"| {model} | {labels[feature]} | {score} | "
                f"{coverage['scored']}/{coverage['planned']} ({rate}) | "
                f"`{values['score_status']}` | {note} |"
            )
    lines += [
        "",
        "## 现阶段结论",
        "",
        "- 附录分数为 76.89，按 4 篇文档的页级开关结果做文档宏平均；FT 与 Origin 相同。",
        "- 页眉页脚分数为 81.48，按已完整核对的 4 页、14 个边缘块做微平均；FT 与 Origin 相同。",
        "- 图表分数为 FT 70.51、Origin 54.22，范围是 11 张图、78 个明示值。",
        "- 图片与印章专项仍是 `pending_evidence`：已有 6 个图片控制 case 和 1 个流程图关系 case，缺少完整的文字图、照片、印章分层证据，不能平均成图片专项分。",
        "- 误删 gate 与质量分独立；校准中已确认的保护项仍按 `deletion_on`／`deletion_off` 单列。",
        "",
        "## 如何把内网结果接进来",
        "",
        "1. 保持 `gt/rubric-pilot-gt.json` 原样，不改 case、字段、明示值或分母。",
        "2. 按评分包的证据说明生成 FT／Origin evidence；没有采到的字段省略，确认空输出写空列表或 `null`。",
        "3. 把 `stage` 改为 `final` 仅用于真实最终成品；在 GT 仍为 `calibration` 时，整体分仍保持 `null`。",
        "4. 正式评价需要另行审核并冻结 evaluation 清单及对应 final evidence；不能只把校准 GT 的 split 改名来形成正式总分。",
        "",
    ]
    (output / "summary.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = args.root.resolve()
    output = fresh_directory(args.output)
    gt_path = root / "artifacts/legacy-features-20261119/rubric-pilot-gt.json"
    if not gt_path.is_file():
        raise SystemExit(f"missing pilot GT: {gt_path}")

    gt_dest = output / "gt" / "rubric-pilot-gt.json"
    gt_dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(gt_path, gt_dest)
    # Keep the v3 dataset identity next to the rubric GT without duplicating model output.
    records = root / "artifacts/legacy-features-20261119/records.json"
    manifest = root / "artifacts/legacy-features-20261119/manifest.json"
    expected_records_hash = "a1384023b6bc67aba52b312091f7bd729c2fc0eba7940e745d422e56fd0c9b29"
    if sha256(records) != expected_records_hash:
        raise ValueError("v3 records.json differs from the reviewed 129 dataset")
    write_json(
        output / "gt" / "dataset-hashes.json",
        {
            "rubric_pilot_gt_sha256": sha256(gt_path),
            "records_sha256": sha256(records),
            "manifest_sha256": sha256(manifest),
            "records_declared_sha256": expected_records_hash,
        },
    )

    metrics = {}
    for model in ("3.1-ft", "3.1-origin"):
        evidence_path = _combine(
            root=root,
            gt_path=gt_path,
            model=model,
            sources=_source_paths(root, model),
            output=output,
        )
        report = evaluate_feature_rubric(gt_dest, evidence_path, output / "scores" / model)
        metrics[model] = report
        _copy_image_control_scope(root, output, model)
        _copy_flow_scope(root, output, model)

    write_json(
        output / "metrics-summary.json",
        {
            "rubric_version": RUBRIC_VERSION,
            "gt_sha256": sha256(gt_dest),
            "records_sha256": sha256(records),
            "models": {
                model: {
                    "stage": report["stage"],
                    "split": report["split"],
                    "overall": report["overall"],
                    "overall_status": report["overall_status"],
                    "features": report["features"],
                    "deletion_gate": report["deletion_gate"],
                }
                for model, report in metrics.items()
            },
        },
    )
    _summary_markdown(output, gt_dest, metrics)
    print(json.dumps({"output": str(output), "gt_sha256": sha256(gt_dest)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
