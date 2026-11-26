"""Audit the existing bc_108 calibration flowchart, including directed edges."""

from __future__ import annotations

import json
import re
import shutil
from html import escape
from pathlib import Path

from doc_parse_bench.feature_evaluation.feature_rubric import (
    CONFIG,
    EVIDENCE_SCHEMA,
    evaluate_feature_rubric,
)
from doc_parse_bench.io import sha256

# Manually source-aligned node identities for this one reviewed calibration case.
# Text and directions are parsed from the literal Mermaid, never supplied from GT.
NODE_KEYS = {
    "ft": {"A": "start", "B": "apply", "C": "review", "D": "end", "E": "sign", "F": "issue"},
    "origin": {"A": "start", "B": "apply", "C": "review", "D": "sign", "E": "end", "F": "issue"},
}
NODE = re.compile(r'([A-Za-z_]\w*)\s*(?:\(\["([^"]*)"\]\)|\["([^"]*)"\]|\{"([^"]*)"\}|\{([^{}]*)\})')
BRANCH_KEYS = {"审核通过": "approved", "审核未通过": "rejected"}


def save(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def audit(root: Path, output: Path, pilot: dict, legacy_origin: Path | None) -> tuple[str, dict]:
    case = next(c for c in pilot["cases"] if c["id"] == "bc_108:candidate.block.p1.0004")
    folder = output / "flowchart-bc108"
    gt_path = folder / "gt.json"
    save(gt_path, {**pilot, "cases": [case],
                   "scope_note": "Existing calibration case; GT is a byte-content subset, not a new annotation."})
    models = {"ft": root / "artifacts/legacy129-subimage-20261123/ft-original-ir/image/documents/bc_108.json"}
    if legacy_origin and (legacy_origin / "image/documents/bc_108.json").is_file():
        models["origin"] = legacy_origin / "image/documents/bc_108.json"
    expected_edges = {(r["from"], r["to"]) for r in case["relations"]}
    expected_branches = {(r["from"], r["to"], r["branch_label"])
                         for r in case["relations"] if r.get("branch_label")}
    results = {}
    for model, source in models.items():
        ir = json.loads(source.read_text())
        block, = [b for p in ir["pages"] for b in p["blocks"] if b["type"] == "image"]
        text = "\n\n".join(str(s.get("content") or s.get("text") or "")
                           for s in block["metadata"].get("generated_spans", []))
        keys = NODE_KEYS[model]
        nodes = {}
        for match in NODE.finditer(text):
            identity, *texts = match.groups()
            value = next(t for t in texts if t is not None)
            if identity in nodes and value != nodes[identity]:
                raise ValueError("Conflicting Mermaid node declarations")
            nodes[identity] = value
        if set(nodes) != set(keys):
            raise ValueError(f"The saved {model} graph changed; review alignment again")
        fields = [{"id": f"bc108/{model}/node/{node}", "key": keys[node], "text": value}
                  for node, value in nodes.items()]
        edges, branches = [], []
        for line_number, line in enumerate(text.splitlines()):
            if "-->" not in line:
                continue
            left, right = line.strip().split("-->")
            left_id = re.match(r"[A-Za-z_]\w*", left)
            branch = re.match(r"\|([^|]*)\|", right)
            label = branch.group(1) if branch else None
            if branch:
                right = right[branch.end():]
            right_id = re.match(r"\s*([A-Za-z_]\w*)", right)
            if left_id is None or right_id is None:
                raise ValueError(f"Unsupported Mermaid edge syntax: {line}")
            start, end = keys[left_id.group()], keys[right_id.group(1)]
            edge = {"id": f"bc108/{model}/edge/{line_number}", "from": start, "to": end}
            edges.append(edge)
            if label is not None:
                fields.append({"id": f"bc108/{model}/branch/{line_number}",
                               "key": BRANCH_KEYS.get(label, "unmatched-branch-label"), "text": label})
                branches.append((start, end, label))
        observation = {"fields": fields, "relations": edges, "raw_content": text,
                       "source_ir_sha256": sha256(source)}
        meta = block["metadata"]
        if "sub_type" in meta:
            observation.update(sub_type=meta["sub_type"], subtype_id=f"bc108/{model}/{block['id']}")
        evidence_path = folder / f"{model}-evidence.json"
        save(evidence_path, {"schema_version": EVIDENCE_SCHEMA, "gt_sha256": sha256(gt_path),
                             "model": f"3.1-{model}", "config": CONFIG, "stage": "replay",
                             "relevel_applied": False, "cases": {case["id"]: observation},
                             "source_ir": str(source), "source_ir_sha256": sha256(source)})
        metrics = evaluate_feature_rubric(gt_path, evidence_path, folder / model)
        scored = json.loads((folder / model / "per_case.json").read_text())[case["id"]]
        observed_edges = {(e["from"], e["to"]) for e in edges}
        snapshot = folder / f"{model}-source-ir.json"
        shutil.copyfile(source, snapshot)
        results[model] = {
            "score": scored, "raw_content": text, "literal_fields": fields, "literal_relations": edges,
            "topology_without_label_gate": {
                "tp": len(observed_edges & expected_edges), "fp": len(observed_edges - expected_edges),
                "fn": len(expected_edges - observed_edges),
            },
            "branch_binding_diagnostic": {"correct": len(set(branches) & expected_branches), "expected": 2},
            "source_ir_sha256": sha256(source), "source_snapshot": str(snapshot.relative_to(output)),
            "overall": metrics["overall"],
        }
    save(folder / "audit.json", results)
    columns = []
    for model, result in results.items():
        s, topology = result["score"], result["topology_without_label_gate"]
        subtype = s["subtype"]
        main_score = "null（缺 subtype 证据）" if s["score"] is None else f'{s["score"]:.2f}'
        columns.append(f'''<section class="variant"><h3>{"FT · 原始完整结构" if model=="ft" else "Origin · 已核对的历史 IR"}</h3>
<p>实际 subtype：<b>{escape(str(subtype['observed'] or '未采到字段'))}</b></p>
<table><tbody><tr><td>节点／分支字段 F1</td><td>{s['fields']['score']:.2f}</td></tr>
<tr><td>只看端点方向的命中</td><td>{topology['tp']}/6（诊断）</td></tr>
<tr><td>要求节点文字正确的关系 F1</td><td>{s['relations']['score']:.2f}</td></tr>
<tr><td>分支标签绑定</td><td>{result['branch_binding_diagnostic']['correct']}/2（诊断）</td></tr>
<tr><td>60% 字段 + 40% 关系</td><td>{s['content_score']:.2f}</td></tr>
<tr><td>单图主分（校准）</td><td>{main_score}</td></tr></tbody></table>
<details><summary>实际 Mermaid 原文</summary><pre>{escape(result['raw_content'])}</pre></details>
<p><a href="flowchart-bc108/{model}-evidence.json">逐字段／边证据</a> · <a href="{result['source_snapshot']}">来源 IR</a></p></section>''')
    note = ""
    if "origin" in results:
        note = "Origin 把末条边写成“流程结束 → 领取机房临时工作证”，方向反了；申请节点还漏“申证”。其余五条拓扑边一致，但当前评分要求端点文字先正确，所以关系 F1 进一步扣分。旧 IR 没有 subtype，主分保持 null。"
    fragment = f'''<section class="panel" id="flowchart-content"><h2>流程图是否读对：一个 129 内的关系核对例</h2>
<p>珠海机场_工作证管理细则_9.pdf · 第 1 页 · bc_108。它是原有校准 case，独立流程图，无 sub_images，不加入上面的 10 个复合框或 18 个建议分析单位。</p>
<div class="source-layout"><div><a href="pages/bc_108-p1.png" target="_blank"><img class="page-img" src="pages/bc_108-p1.png" loading="lazy" alt="珠海机场流程图原 PDF 页"></a></div>
<div><p><b>FT 在这张图上读对了内容和结构：</b>六个节点、两条分支文字、六条有向边和两条分支绑定均对齐原页及已有 GT。这个结论来自逐条核对，不依赖 Mermaid 是否渲染成功。</p><p>{note}</p><p>消防两图当前输出只有文字列表，仍不能据文字 F1 断言接线关系正确；Fig. 1 的标注引线也不自动当成流程关系。</p></div></div>
<div class="variants">{''.join(columns)}</div><p class="muted">复用原有校准 GT，stage=replay、relevel_applied=false；分支标签绑定单独诊断，未修改评分代码。仅说明该 case 的能力，不是全量图片分或上线结论。</p></section>'''
    return fragment, results
