"""Export the exact content scorer, frozen GT and saved evidence for offline use."""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

from doc_parse_bench.feature_evaluation.feature_rubric import (
    RUBRIC_VERSION,
    evaluate_feature_rubric,
)
from doc_parse_bench.io import fresh_directory, sha256, write_json

README = """# Legacy 129 离线评分包

在这个目录运行即可；只用 Python 3.10+ 标准库，不安装 MinerU 或本仓库依赖，不调用模型。

```sh
python3 score.py score --gt gt/rubric-pilot-gt.json --pred evidence/3.1-ft.json --output /tmp/legacy129-ft-new
python3 score.py score --gt gt/rubric-pilot-gt.json --pred evidence/3.1-origin.json --output /tmp/legacy129-origin-new
python3 selftest.py
```

输出目录必须为空或不存在，避免混入历史结果。`reference-scores/` 是随包参考结果。

校准范围的空证据模板。

```sh
python3 score.py template --gt gt/rubric-pilot-gt.json --model 3.1-ft --output /tmp/ft-blank.json
```

模板包含 case ID 与空的预测字段，填入经来源对齐的实际证据后评分。字段规则和同次开关配对见 `docs/inputs.md`，计算公式见 `docs/scoring.md`。
`gt/records.json` 是旧 v3 结构目标，`gt/rubric-pilot-gt.json` 冻结历史校准的分母。此包用于复算校准分项。

校准结果中，两版的附录均为 76.89，页眉页脚均为 81.48，图表均命中 78/78 个明示值。Origin 的风能图有列名冲突。
图片与印章专项和总分仍为 null，逐例分数和缺证据清单已输出。历史标题重排未执行，正式目标配置仍为 MinerU3/relevel_titles=true/title_rules=false。

`MANIFEST.json` 记录包内哈希。`code/doc_parse_bench/feature_evaluation/` 为仓库评分源码的快照。
"""

SELFTEST = '''"""Verify bundled hashes and reproduce the calibration scores without dependencies."""
import hashlib
import json
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

root = Path(__file__).resolve().parent
sys.path.insert(0, str(root / "code"))
from doc_parse_bench.feature_evaluation.feature_rubric import evaluate_feature_rubric

manifest = json.loads((root / "MANIFEST.json").read_text(encoding="utf-8"))
for row in manifest["files"]:
    path = root / row["path"]
    assert path.is_file(), row["path"]
    assert hashlib.sha256(path.read_bytes()).hexdigest() == row["sha256"], row["path"]
with TemporaryDirectory(prefix="legacy129-scorer-") as tmp:
    for model in ("3.1-ft", "3.1-origin"):
        result = evaluate_feature_rubric(
            root / "gt/rubric-pilot-gt.json", root / "evidence" / (model + ".json"),
            Path(tmp) / model,
        )
        assert result["rubric_version"] == manifest["rubric_version"]
        chart = result["features"]["chart"]
        assert chart["score"] == 100 and chart["matched_values"] == 78
        assert chart["header_conflict_cases"] == (
            ["bc_091:candidate.block.p1.0004"] if model == "3.1-origin" else []
        )
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
    features = package / "feature_evaluation"
    features.mkdir(parents=True)
    source = root / "src/doc_parse_bench"
    for name in ("__init__.py", "io.py"):
        shutil.copy2(source / name, package / name)
    for name in (
        "__init__.py",
        "feature_contract.py",
        "feature_rubric.py",
        "feature_score_cli.py",
    ):
        shutil.copy2(source / "feature_evaluation" / name, features / name)
    (output / "score.py").write_text(
        '"""Offline legacy129 scorer; no model calls or third-party dependencies."""\n'
        "import sys\nfrom pathlib import Path\n"
        'sys.path.insert(0, str(Path(__file__).resolve().parent / "code"))\n'
        "from doc_parse_bench.feature_evaluation.feature_score_cli import main\n\nmain()\n",
        encoding="utf-8",
    )
    (output / "README.md").write_text(README, encoding="utf-8")
    (output / "selftest.py").write_text(SELFTEST, encoding="utf-8")
    for name in ("manifest.json", "records.json", "rubric-pilot-gt.json"):
        destination = output / "gt" / name
        destination.parent.mkdir(exist_ok=True)
        shutil.copy2(root / "artifacts/legacy-features-20261119" / name, destination)
    for name in ("scoring.md", "inputs.md", "annotation.md"):
        destination = output / "docs" / name
        destination.parent.mkdir(exist_ok=True)
        shutil.copy2(root / "docs/feature-evaluation" / name, destination)
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
            "rubric_version": RUBRIC_VERSION,
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
            "current_round_status": "calibration_replay",
        },
    )
    print(json.dumps({"output": str(output)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
