"""Export the exact content scorer, frozen GT and saved evidence for offline use."""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

from doc_parse_bench.feature_rubric import evaluate_feature_rubric
from doc_parse_bench.io import fresh_directory, sha256, write_json

README = """# Legacy 129 离线评分包

在这个目录运行即可；只用 Python 3.10+ 标准库，不安装 MinerU 或本仓库依赖，不调用模型。

```sh
python3 score.py score --gt gt/rubric-pilot-gt.json --pred evidence/3.1-ft.json --output /tmp/legacy129-ft-new
python3 score.py score --gt gt/rubric-pilot-gt.json --pred evidence/3.1-origin.json --output /tmp/legacy129-origin-new
python3 selftest.py
```

输出目录必须为空或不存在，避免混入历史结果。`reference-scores/` 是随包参考结果。

内网实际成品的空证据模板：

```sh
python3 score.py template --gt gt/rubric-pilot-gt.json --model 3.1-ft --stage final --output /tmp/ft-blank.json
```

模板所有 case 均为空，不能直接当作失败预测；填入实际来源对齐证据后才评。
评分器不会从任意 Markdown 自动判定字段归属或推断 subtype。字段 schema、确认空输出、证据不足、同次开关配对和范围见 `docs/feature-evaluation-129-rubric.md`。

`docs/legacy129-scoring-contract.md` 是本轮收敛说明：公式、GT 是否改过、归一化规则和复算结果。
`gt/records.json` 是完整 v3 结构目标；`rubric-pilot-gt.json` 是内容校准范围，二者不可互换。
本包的 pilot GT 仍为 calibration；即使 evidence 标成 final，也不会产生正式总分。
不能把 split 改名代替正式评价清单审核，也不能将未采到的字段填零来凑总分。

现有校准分：附录两版 76.89；页眉页脚两版 81.48；图表 FT 70.51、Origin 54.22，仅 11 图/78 明示值。
图片与印章专项和总分仍为 null，逐例分数和缺证据清单已输出。历史标题重排未执行，正式目标配置仍为 MinerU3/relevel_titles=true/title_rules=false。

`MANIFEST.json` 记录包内哈希。`code/doc_parse_bench/` 是仓库同名文件的原样复制，评分逻辑与 docbench 入口一致。
本包提供离线评分与现有历史证据，不包含新增内网推理结果或已验收的 P2T 适配代码。

本轮已停止补证据、补 GT 和补推，现有 null 原样保留。
下次评测需要提供的原始服务响应、成品、资产、来源映射及配置，见 `docs/legacy129-next-evaluation-inputs.md`。
"""

SELFTEST = '''"""Verify bundled hashes and reproduce the calibration scores without dependencies."""
import hashlib
import json
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

root = Path(__file__).resolve().parent
sys.path.insert(0, str(root / "code"))
from doc_parse_bench.feature_rubric import evaluate_feature_rubric

manifest = json.loads((root / "MANIFEST.json").read_text(encoding="utf-8"))
for row in manifest["files"]:
    path = root / row["path"]
    assert path.is_file(), row["path"]
    assert hashlib.sha256(path.read_bytes()).hexdigest() == row["sha256"], row["path"]
with TemporaryDirectory(prefix="legacy129-scorer-") as tmp:
    for model, chart in [("3.1-ft", 70.51282051282051), ("3.1-origin", 54.21686746987952)]:
        result = evaluate_feature_rubric(
            root / "gt/rubric-pilot-gt.json", root / "evidence" / (model + ".json"),
            Path(tmp) / model,
        )
        assert abs(result["features"]["chart"]["score"] - chart) < 1e-9
        assert abs(result["features"]["appendix"]["score"] - 76.89102564102564) < 1e-9
        assert abs(result["features"]["header_footer"]["score"] - 81.48148148148148) < 1e-9
        assert result["features"]["image"]["score"] is None
        assert result["overall"] is None
        assert result["overall_status"] == "calibration_only"
        assert result["deletion_gate"]["observed_status"] == "fail"
print("PASS: bundle hashes and both calibration score reports")
'''


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = args.root.resolve()
    output = fresh_directory(args.output)
    package = output / "code/doc_parse_bench"
    package.mkdir(parents=True)
    for name in (
        "__init__.py",
        "io.py",
        "feature_contract.py",
        "feature_rubric.py",
        "feature_score_cli.py",
    ):
        shutil.copy2(root / "src/doc_parse_bench" / name, package / name)
    (output / "score.py").write_text(
        '"""Offline legacy129 scorer; no model calls or third-party dependencies."""\n'
        "import sys\nfrom pathlib import Path\n"
        'sys.path.insert(0, str(Path(__file__).resolve().parent / "code"))\n'
        "from doc_parse_bench.feature_score_cli import main\n\nmain()\n",
        encoding="utf-8",
    )
    (output / "README.md").write_text(README, encoding="utf-8")
    (output / "selftest.py").write_text(SELFTEST, encoding="utf-8")
    for name in ("manifest.json", "records.json", "rubric-pilot-gt.json"):
        destination = output / "gt" / name
        destination.parent.mkdir(exist_ok=True)
        shutil.copy2(root / "artifacts/legacy-features-20261119" / name, destination)
    for name in (
        "legacy129-scoring-contract.md",
        "feature-evaluation-129-rubric.md",
        "legacy129-next-evaluation-inputs.md",
    ):
        destination = output / "docs" / name
        destination.parent.mkdir(exist_ok=True)
        shutil.copy2(root / "docs" / name, destination)
    shutil.copy2(
        root / "experiments/legacy129-subimage-20261123/agentbuilder-impact-check-20261124.json",
        output / "docs/agentbuilder-impact-check-20261124.json",
    )
    for model in ("3.1-ft", "3.1-origin"):
        source = (
            root / "experiments/legacy129-subimage-20261123/calibration-evidence" / f"{model}.json"
        )
        destination = output / "evidence" / source.name
        destination.parent.mkdir(exist_ok=True)
        shutil.copy2(source, destination)
        evaluate_feature_rubric(
            output / "gt/rubric-pilot-gt.json", destination, output / "reference-scores" / model
        )
    write_json(
        output / "MANIFEST.json",
        {
            "schema_version": "doc-parse-bench.legacy129-scoring-bundle.v1",
            "rubric_version": "legacy129-content-v1",
            "files": [
                {
                    "path": str(path.relative_to(output)),
                    "bytes": path.stat().st_size,
                    "sha256": sha256(path),
                }
                for path in sorted(output.rglob("*"))
                if path.is_file()
            ],
            "new_model_calls": 0,
            "current_round_status": (
                "closed_without_evidence_backfill; input requirements documented for next evaluation"
            ),
        },
    )
    print(json.dumps({"output": str(output)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
