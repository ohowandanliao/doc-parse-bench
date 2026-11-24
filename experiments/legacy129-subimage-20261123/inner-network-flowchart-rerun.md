# 内网 P2T 复核清单

这是交给内网 AI 的输入和验收说明。清单全部来自 legacy 129，不新增正式评测样本；`inner-network-flowchart-cases.json` 是机器可读版本。

最新复合框审阅与实际输入见 [父子图 HTML](../../artifacts/legacy129-subimage-20261123/analysis-units-review-20261124/review.html) 和同目录的 `analysis-plan.json`。它列出 4 个建议整父图分析单位和 6 组 14 张建议子图，均为待确认方案，不自动调用模型。`bc_062` 共图注两组目前没有冻结的内容 subtype GT，不能将其子图预测 `text_image` 当作 GT。

## 输入和配置

输入 PDF 位于 `data/legacy/dataset/pdf/source/`，文件名和物理页码见 JSON。每个 case 只处理列出的物理页，但 P2T 仍应按真实 PDF 请求，不能把裁图当成正式整篇输入。正式目标配置固定为：

```text
provider=mineru3
backend=vlm-vllm-async-engine
relevel_titles=true
title_rules=false
```

对每个模型（`3.1-ft`、`3.1-origin`）按 JSON 的 switch matrix 跑开关组合：`both_off`、`image_on`、`chart_on`、`both_on`。`subimage_analysis` 是 P2T 适配开关，不是 MinerU upstream 参数；`both_off` 必须关闭它，作为原路径控制。不要用 GT、文件名或 Origin 答案决定线上拆分，也不要把 4 秒或每篇 8 张当作已确认的线上预算。

双关还要补一个兼容控制：保持 image/chart 都关闭，只切服务配置 `subimage_analysis=false/true`，最终请求、过滤和交付必须一致。原路径可能递归清掉父块印刷图注；此兼容控制以原 ZIP 行为为准，不能拿分析开启的图注输出来替代原版基线。

以 3.3.1/1.0.5 为工程参考时，可优先复用 `extract_with_layout` 固定区域分析（`image` 区域、`image_analysis=true`），保留实际 type/subtype/content。它是 Python API，原 `/file_parse` 没有外部 layout 表单；内网 AI 需先确认同一 upstream 如何提供这项能力。裁图重传 `/file_parse` 属于再次布局路径，不能未经验证就认为已分析了整个父图。

每个请求至少保存：

- P2T 对外 Markdown 和页数；
- 本次请求实际收到的 `middle_json`、图片资产和来源哈希；
- 每个复合父框的 `parent_index`、原生 `sub_images` 数量、分析单位（父图／子图／无）、`rule`、请求数、每次 `elapsed_ms`、失败类别（未调用、超时、上游错误、渲染过滤）；
- 拆分后每个块的 `source_id`、`subimage_source`、bbox、实际 `type`／`sub_type` 和内容。

标题重排必须真正执行；若内网只能提供渲染前 IR，单独标 `relevel_applied=false`，不要把它写成正式成品验收。

## 检查顺序

1. 先用 `both_off` 对照同一模型的原路径：没有新裁图、没有父／子图请求，且原图、印刷图注、普通图片、附录和页眉页脚与原版本一致。
2. 再看 `image_on`：流程图先核节点文字，再核连线端点、方向、分支标签和子图归属；`sub_type` 单独核验。能生成 Mermaid 只算输出形态证据，不能替代关系检查。
3. 看 `chart_on`：双柱图应补回 10 个明示值；普通图片不能因为 chart 开启而出现图片描述；图表输出按实际系列、类别、数值和单位记录。
4. 看 `both_on`：同一复合块不能因两个开关各跑一次而重复请求或重复交付；父图／子图的分析来源和最终交付粒度必须可追溯。

## 重点判定

- `bc_022` 第 2 页 Fig. 1：父图保留不等于跳过分析；不能从某个子面板复制父图 subtype。此 case 的正式 GT 只计节点字段，不把虚线引线当作关系。
- `bc_065` 第 1 页：两幅接线图的 GT subtype 都是 `flowchart`。历史 FT 文字 F1 曾为左图 100、右图 87.50，但两图被标成 `text_image` 时，图片主分仍为 0；文字分只作诊断。PE→PH 是右图的字段差异线索，不能单凭它宣布整张图的关系正确或错误。
- `bc_108` 第 1 页：六节点、两条分支文案、六条有向边是正式关系正例。逐条记录 `from`、`to` 和分支标签；不要只看 Mermaid 是否能渲染。
- `bc_062` 第 1 页：两个共图注线路父框是防误拆反例。若拆成半框导致原 GT 无法命中，归因到 P2T 分／合策略；若保留父图但没有分析响应，记证据不足。
- `bc_059` 和 `bc_078`：分别验证有字照片的 OCR／subtype 和无字照片的资产／subtype。描述文字不能替代 `natural_image` 标签。

## 回传格式

内网结果回传时按 JSON case ID 保持稳定，另外提供一份 HTML 并排页。内容证据按 `feature_rubric` schema 写入 `sub_type`、`subtype_id`、字段／关系 ID 和图表值 ID；确认缺失写 `null` 或 `missing`，没有采到字段则省略，不要把两者混成模型 0 分。未确定父图保留时是否整图分析前，所有保留父图的分析分数都标为 `evidence_missing`，不拼接子图回答。

