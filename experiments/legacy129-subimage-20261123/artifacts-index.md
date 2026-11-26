# 11 月 24 日校准产物

本页记录历史校准。正式计分、实测输入及复算见[四功能文档](../../docs/feature-evaluation/README.md)。以下目录相对仓库根。

GT 版本关系：2026-11-18 是历史 v2（records SHA `13270f9d…a9179`），2026-11-19 是本轮固定的 v3（records SHA `a1384023…9b29`）。129 专项当前只使用 v3；pilot GT SHA `6d98b544…10b72` 未改。旧版本不与当前结果混比。

| 用途 | 入口 | 状态 |
| --- | --- | --- |
| 候选补丁与离线交接 | `artifacts/legacy129-subimage-20261123/p2t-inner-handoff-20261124/` | 历史交接目录 |
| 统一校准分数 | `artifacts/legacy129-subimage-20261123/calibration-scores-20261124/summary.md` | 附录、边缘、图表可复算；图片／总分仍 null |
| 可版本化的评分证据 | `experiments/legacy129-subimage-20261123/calibration-evidence/` | 两版固定 evidence，不依赖重新推理 |
| 父图／子图案例审阅 | `artifacts/legacy129-subimage-20261123/analysis-units-review-20261124/review.html` | 10 父框／27 子图；建议尚未冻结为规则 |
| 历史 V2 并排交付 | `artifacts/legacy129-subimage-20261123/p2t-replay-v2-final/review.html` | 历史回归，不是最终上线实现 |
| 前置拆分候选／全部拆分对照 | `artifacts/legacy129-subimage-20261123/p2t-split-policy/review.html` | 历史候选 |
| 原始推理输入 | `archives/129-subimage-inference-full-20261123/` | 原样保留 |

旧中间回放的归档哈希见当时的[清理记录](artifact-cleanup-20261124.json)。

重建历史校准评分包并自检。

```sh
.venv/bin/python experiments/legacy129-subimage-20261123/build_scoring_bundle.py \
  --output /tmp/legacy129-scoring-bundle-new
.venv/bin/python -S /tmp/legacy129-scoring-bundle-new/selftest.py
```
