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

## 新模型出分

采集完成后用 `docbench evaluate-legacy129` 读取本批成品 ZIP。附录从最终 Markdown 和同页结构核对表格锚点，图表用 `both_on`，图片和印章用 `image_only`。新数据集可以通过 `--gt` 和 `--sources` 指定专项计分清单和 PDF 来源清单，成品沿用以下命令要求的七组目录结构。

```sh
.venv/bin/docbench evaluate-legacy129 \
  --zip /path/to/finals.zip --model ckpt32 --output /path/to/new-score-directory
```

自动取证要求候选块与源框位于同一物理页、归属唯一，并满足标准框重叠（IoU ≥ 0.5）。图表提取成品表原文，图像内容使用可核对的类型标签、资产和原样字段。流程图连线、合框、缺少来源或字段归属有歧义的项进入 `visual_review.json`。`scores/pending_cases.json` 记录页眉页脚和保护项等其他缺证据项。

已核对的观测按[证据格式](inputs.md#交给评分器的-evidence)填写，可用本批输出的 `evidence.json` 作基础。保留成品 `products_sha256`、`gt_sha256`、图片的 `image_only_captures` 和配对组的 `captures`。将复核文件通过 `--reviewed-evidence` 交给同一命令即可从保存的成品出分。证据未齐时相应分数显示待核。

旧采集包的 `build_evidence.py` 供快速诊断。汇报使用上述入口产出的 `scores/metrics.json`，或者用已复核的 evidence 复算。

## 复算

跨环境复评使用同一份冻结 GT 和同一份模型证据。同步 `image-supplement/` 中的两份 `*-evidence.json`，与冻结 GT 一起核对 SHA-256。比对复评报告时检查 `provenance.json` 的 `gt_sha256`、`scorer_sha256`、`contract_sha256` 和对应模型的 `evidence_sha256`。以下命令从仓库根目录运行。

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

重建证据时复用同一份取证脚本、两份成品回包和对应的 `mineru_filters.py`。`--chart-evidence` 指向两份已复核证据所在目录。重建时会将图表主体与同页成品再次核对，读取附录表格的文字，登记页眉页脚的额外输出，并按实际图块提取图片与印章证据。

```sh
batch=artifacts/legacy129-evaluation-20261126
out=$(mktemp -d)
.venv/bin/python -m doc_parse_bench.feature_evaluation.legacy129.build_report \
  --zip "$batch/inputs/1125-legacy129-inference-finals-slim.zip" \
  --chart-evidence "$batch/image-supplement" \
  --output "$out/base"
.venv/bin/python -m doc_parse_bench.feature_evaluation.legacy129.score_image_supplement \
  --slim "$batch/inputs/1125-legacy129-inference-finals-slim.zip" \
  --supplement "$batch/inputs/1125-legacy129-supplement-imageonly-bothon.zip" \
  --filters "$batch/inputs/mineru_filters.py" \
  --base-evidence "$out/base" --output "$out/final"
open -a Safari "$out/final/index.html"
```

11 月的 pilot GT 与回归证据用于历史校准。更早的非空输出率和 full282 对照见 [11 月 20 日报告](legacy129-20261120.md)，旧结构回放命令见[结构回放](legacy129-structure.md)。
