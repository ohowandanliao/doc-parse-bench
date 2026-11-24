# 129 专项本地产物入口

最新评分实现和 GT 版本见 [评分交付口径](../../docs/legacy129-scoring-contract.md)。以下目录相对仓库根。

GT 版本关系：2026-11-18 是历史 v2（records SHA `13270f9d…a9179`），2026-11-19 是本轮固定的 v3（records SHA `a1384023…9b29`）。129 专项当前只使用 v3；pilot GT SHA `6d98b544…10b72` 未改。旧版本不与当前结果混比。

| 用途 | 入口 | 状态 |
| --- | --- | --- |
| 内网适配＋离线评分交接 | `artifacts/legacy129-subimage-20261123/p2t-inner-handoff-20261124.zip` | evaluation 是当前评分实现；p2t-reference 仍是历史候选基线 |
| 统一校准分数 | `artifacts/legacy129-subimage-20261123/calibration-scores-20261124/summary.md` | 附录、边缘、图表可复算；图片／总分仍 null |
| 可版本化的评分证据 | `experiments/legacy129-subimage-20261123/calibration-evidence/` | 两版固定 evidence，不依赖重新推理 |
| 父图／子图案例审阅 | `artifacts/legacy129-subimage-20261123/analysis-units-review-20261124/review.html` | 10 父框／27 子图；建议尚未冻结为规则 |
| 历史 V2 并排交付 | `artifacts/legacy129-subimage-20261123/p2t-replay-v2-final/review.html` | 历史回归，不是最终上线实现 |
| 前置拆分候选／全部拆分对照 | `artifacts/legacy129-subimage-20261123/p2t-split-policy/review.html` | 历史候选 |
| 原始推理输入 | `archives/129-subimage-inference-full-20261123/` | 原样保留 |
| 中间回放归档 | `archives/legacy129-intermediate-replays-20261124.zip` | 包含 p2t-replay-v2、p2t-pre-crop 全文件及 SHA 清单 |

此次仅将这两份中间回放从活动目录改为可恢复 ZIP，2,602 个文件逐个验证 CRC 和 SHA-256 后才移除原目录内容。原始 PDF、GT、推理包、V1／V2 历史结果、当前审阅页和候选补丁都保留。压缩前 130,612,775 bytes，ZIP 36,905,279 bytes，净减少 93,707,496 bytes（约 89.4 MiB）。归档哈希和保留目录列表见 [清理记录](artifact-cleanup-20261124.json)。

恢复命令（仓库根运行）：

```sh
unzip archives/legacy129-intermediate-replays-20261124.zip \
  -d artifacts/legacy129-subimage-20261123/
```

评分包构建命令（输出必须为空或新目录）：

```sh
.venv/bin/python experiments/legacy129-subimage-20261123/build_scoring_bundle.py \
  --output /tmp/legacy129-scoring-bundle-new
.venv/bin/python -S /tmp/legacy129-scoring-bundle-new/selftest.py
```
