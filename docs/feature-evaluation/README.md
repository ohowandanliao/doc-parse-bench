# PDF2Text 四功能评测

评测范围包括附录、页眉页脚、图片与印章、图表。每次用一份冻结的 GT 和按原页、源块核对的成品证据计算分数。

| 使用场景 | 文档 |
| --- | --- |
| 从标注 Agent v2 给新文档补图表、图片和印章 GT | [补标流程](annotation.md) |
| 查评分公式、清单格式和命令 | [评分口径](scoring.md) |
| 给新模型采集推理与过滤证据 | [评测输入与推理配置](inputs.md) |
| 复核 11 月 25 日 FT 与 Origin 的正式评测 | [Legacy 129 实测和复算](legacy129.md) |
| 重建既有 129 结构视图或回放旧开关矩阵 | [GT 版本登记](legacy129-gt-versions.md) · [结构回放](legacy129-structure.md) |

核心源码位于 [`src/doc_parse_bench/feature_evaluation/`](../../src/doc_parse_bench/feature_evaluation/)，正式计分入口为 `docbench evaluate-feature-rubric`。固定批次的复算和补标脚本在源码的 `legacy129/` 子目录，该批 GT 与证据保存在 `artifacts/`。
