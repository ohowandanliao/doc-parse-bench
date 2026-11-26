# Legacy 129 实测和复算

11 月 25 日的成品采用已有的内网 P2T `68624-subimage-expand` 改造。8009 FT 的 2605 推理在图片和图表双开时有六篇触发内部补偿，共 25 次裁图请求，含一次重试。8010 Origin 的 2604 各开关组均为零裁图请求。`bc_062` 两个父图各走一次整图分析，回包仍是 `image_block`，按策略保留原图。独立六篇正式接口验收记录为 `8b747ca` 加冻结补丁，129 篇成品记录本批实际 `code_fingerprint`。

## 正式分数

| 专项 | 8009 FT | 8010 Origin | 分母 |
| --- | ---: | ---: | --- |
| 附录 | 82.21 | 82.21 | 48 页 |
| 页眉页脚 | 89.23 | 89.74 | 800 块 |
| 图片与印章 | 29.47 | 27.05 | 89 个目标 |
| 图表 | 99.68 | 99.04 | 47 张图、312 个明示值 |
| 总分 | 75.15 | 74.51 | 四项等权 |

两版各有 17/20 个保护项双侧完整。两版均确认 `bc_022` 关闭图片分析时丢失第 2 页 Fig. 1 印刷图注，误删门槛为失败。

## 文件位置

| 内容 | 路径 |
| --- | --- |
| 正式计分清单与 PDF 来源 | [rubric-evaluation-gt.json](../../artifacts/legacy-features-20261125/rubric-evaluation-gt.json) 和 [rubric-evaluation-sources.json](../../artifacts/legacy-features-20261125/rubric-evaluation-sources.json) |
| 本批复算脚本 | `src/doc_parse_bench/feature_evaluation/legacy129/` 的 `build_report.py` 和 `score_image_supplement.py` |
| 成品、补充回包和验收 ZIP | 本地 `artifacts/legacy129-evaluation-20261126/inputs/` |
| 逐案结果与审阅报告 | 本地 `artifacts/legacy129-evaluation-20261126/image-supplement/` 的 `index.html`、`ft/`、`origin/` |
| 本批标注与复核 | 本地 `artifacts/legacy129-formal-gt-review-20261125/`，本批合并脚本为 `legacy129/build_draft.py` |

本批用 v2 派生的 v3 区域组织专项，Terra 和 Luna 对照原 PDF 补标。11 月 26 日复核修订四张图，分别是 `4-1统计图3.pdf` 第 12 页上下两图，以及 `4-1统计图3.pdf` 和 `4-2段落中带「图x-x」.pdf` 第 10 页下图。图表分母为 312 个明示值。附录按原 MinerU3 规则从后半段首个以「附录」或 `Appendix` 开头的标题所在页截到文末。

## 复算

从保存的两版正式 evidence 重新计分，无需调用模型。以下命令从仓库根目录运行。

```sh
batch=artifacts/legacy129-evaluation-20261126
out=$(mktemp -d)
for model in ft origin; do
  .venv/bin/docbench evaluate-feature-rubric \
    --gt artifacts/legacy-features-20261125/rubric-evaluation-gt.json \
    --pred "$batch/image-supplement/$model-evidence.json" \
    --output "$out/$model"
done
```

重新核对回流包、生成逐图 evidence 和本地审阅页时使用同一批 `inputs/`、已对齐的图表证据及已核对的归属规则。

```sh
batch=artifacts/legacy129-evaluation-20261126
out=$(mktemp -d)
.venv/bin/python -m doc_parse_bench.feature_evaluation.legacy129.build_report \
  --zip "$batch/inputs/1125-legacy129-inference-finals-slim.zip" \
  --output "$out/base"
.venv/bin/python -m doc_parse_bench.feature_evaluation.legacy129.score_image_supplement \
  --base-evidence "$out/base" --output "$out/final"
open -a Safari "$out/final/index.html"
```

11 月的 pilot GT 与回归证据用于历史校准。更早的非空输出率和 full282 对照见 [11 月 20 日报告](legacy129-20261120.md)，旧结构回放命令见[结构回放](legacy129-structure.md)。
