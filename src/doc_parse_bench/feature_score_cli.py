"""Run the legacy-129 content scorer using only the Python standard library."""

import argparse
import json
from pathlib import Path

from .feature_rubric import CONFIG, EVIDENCE_SCHEMA, evaluate_feature_rubric
from .io import read_json, sha256, write_json


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    score = commands.add_parser("score", help="按冻结 GT 和来源对齐证据计算内容分")
    score.add_argument("--gt", type=Path, required=True)
    score.add_argument("--pred", type=Path, required=True)
    score.add_argument("--output", type=Path, required=True)
    template = commands.add_parser("template", help="生成空证据模板；不会把 GT 答案填入预测")
    template.add_argument("--gt", type=Path, required=True)
    template.add_argument("--model", required=True)
    template.add_argument("--stage", choices=("replay", "final"), default="replay")
    template.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "score":
            result = evaluate_feature_rubric(args.gt, args.pred, args.output)
        else:
            if args.output.exists():
                raise ValueError(f"证据文件已存在，请使用新路径：{args.output}")
            gt = read_json(args.gt)
            result = {
                "schema_version": EVIDENCE_SCHEMA,
                "gt_sha256": sha256(args.gt),
                "model": args.model,
                "stage": args.stage,
                "config": dict(CONFIG),
                "relevel_applied": None,
                "captures": {},
                "cases": {case["id"]: {} for case in gt["cases"]},
            }
            write_json(args.output, result)
            result = {"output": str(args.output), "cases": len(result["cases"])}
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except (ValueError, KeyError, TypeError, OSError) as error:
        parser.exit(1, f"错误：{error}\n")


if __name__ == "__main__":
    main()
