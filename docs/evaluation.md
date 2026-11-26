# 当前评测流程

日常评测固定同一数据版本、文件范围和输入处理规则，在同批模型预测上一起运行两个原生后端，生成三个独立榜。完整指标定义只在 [评分细则](metrics-comparison.md) 维护；后续数据与图表专项方案见 [数据集与评测设计](dataset-evaluation-design.md)。

129 份文档的旧 Markdown `legacy-129-markdown-v1` 用于历史兼容，`legacy-129-annotated-v2` 用于显式 129 AgentBuilder/TreeTitle-v2 评测，`legacy-129-feature-v3` 提供四功能结构视图。各版本来源和正式内容计分清单见 [129 GT 版本登记](feature-evaluation/legacy129-gt-versions.md)。

## 输入与模型适配

| 后端 | GT | 预测 |
| --- | --- | --- |
| OmniDocBench end2end | 每页一个 sample 的 JSON | 每页一个 Markdown |
| MPDocBench end2end | 每文档一个 sample、含页码与关系的 JSON | 每文档一个 Markdown；FigureF1 还需可解析的页码和图片坐标 |
| legacy_compat | 旧 Markdown GT | 旧文档 Markdown，用于历史复现 |

模型原生 JSON、DSL 或 Markdown 先由对应适配器读取，再导出评分器要求的格式；这不是额外的评测维度。适配只使用预测自身信息，不从 GT 补正文、标题或关系。具体契约与损失见 [模型适配](model-adapters.md)。

## 日常运行

```bash
docbench run configs/standard.yaml
```

先在 YAML 中明确数据路径、`dataset_version`、模型及新的 output 目录。当前 `run` 会重新准备 GT 与预测，再运行配置中的后端；评测期间保持输入不变。冻结 GT 的分步运行见 [版本管理](annotation-workflow.md) 和 [MPDocBench](MPDocBench.md)。

Omni 与 MP 保留各自匹配和聚合单位；AgentBuilder 仅取同批 Omni 页面分项＋页面 title，不额外启动匹配器。历史匹配器和 MP 文档分项产生的旧加权分不能作为新版 AgentBuilder 分数。

## AgentBuilder-v2 复测

AgentBuilder-v2 使用 Omni 文本、表格 TEDS、阅读顺序，以及完整文档 TitleTree-v2，权重为 0.3／0.3／0.3／0.1。必要分项缺失时不发布总分；缺失预测继续按冻结清单作为空预测处理。它与上文的历史 AgentBuilder 分开命名。

```bash
docbench rescore-agentbuilder \
  --inputs artifacts/research/heading-rag-code-review-20261109/retest_inputs.json \
  --output artifacts/results/agentbuilder-v2-new-run
```

需要 eval 依赖。清单明确选择 GT、历史报告和预测目录；命令核对输入 SHA256，重算旧页面 title、原生 HeadTEDS 距离和新标题树，再计算新旧总分。文本／表格／顺序复用核验后的既有指标，原生标题复算使用保存的提取输入对；不重新运行 OCR、全文匹配或 RAG。输出目录必须为空。

[15 配置复测结果](../artifacts/results/agentbuilder-v2/summary.md)及[方法、案例与采用依据](标题评分复核_结合完整FastGPT与pdf2text代码_20261109.md)已整理。

## 历史清洗的边界

当前 CLI 保留 standard／legacy 前处理预设，数据和后端独立选择：standard 关闭 base64 替换与 details 清洗，legacy 默认开启这两项；单项均可覆盖。日常不要求两套都跑，legacy 组合主要保留用于旧结果复现或明确的处理消融。

这两项不是模型推理开关。details 处理可能用内部表格替掉图片；base64 替换也可能丢弃 alt。操作和原包证据见 [Markdown 前处理](markdown-preprocessing.md)。仅需查看时对 review 副本操作。

**当前 standard 仍可能保留适配器生成的 visual_details，尚未实现严格的基础／图表附加内容分流。** 不因关闭 legacy 就宣称图表内容完全不影响匹配。今后投影规则改变时生成新基线，保留旧分数和输入记录。

PDF2Text 的 `keep_appendix`、`keep_header_footer`、`image_analysis` 和 `chart_analysis` 使用独立的[四功能评测](feature-evaluation/README.md)。分数基于同一批 PDF 的冻结 GT 和实际成品。已评样本见 [Legacy 129 实测](feature-evaluation/legacy129.md)。

## 图表内容不等于图像定位

Omni、MP 的默认端到端流程不以 figure 内部文字或数据表作为内容识别真值；MP 的 FigureF1 评图像页码和位置。旧 129 则把部分图表转录混入普通 table，属于不同任务定义，不能直接合并其分数。

`augment-charts` 和 `--chart-policy chart-table` 用于准备数据表或增强输出。经过来源核对的成品可交给 `docbench evaluate-feature-rubric` 计算图表明示值命中率。[图表评分口径](feature-evaluation/scoring.md#图表明示值命中率)

## 缺失、版本与产物

- `run` 的当前 profile 默认允许缺失，并按空预测处理；分步 `evaluate` 默认拒绝缺失，显式加 `--allow-missing` 后才按空预测计分。
- 文件数齐全仍可能有截断页；报告保留预期／实际页数与 `incomplete_documents`。适配错误应报失败，不能伪装成正常空预测。
- 比较固定 GT 身份、上游版本、指标配置和处理策略；图表增强、规则或 VLM 结构处理用独立实验标签。
- `metrics.json` 保存汇总，`per_doc_scores.json` 保存逐单位分数（Omni 为页），`runtime/result/` 保存上游结果，`evaluation.log` 和 `provenance.json` 保存运行信息。
- `summary.md` 链接三个 `leaderboards/<榜单>/summary.{md,csv,json}`；历史兼容结果另列。

历史结果入口：[评测结果](../artifacts/results/README.md)。这是 2026-11-03 批次、旧 GT 的 15 个配置及清洗对照，不能作为活动 `annotated-20261111` GT 的成绩。用 `.venv/bin/python experiments/20261103/summarize_results.py` 可从该批已完成报告更新入口；新实验使用 `docbench collect` 生成独立汇总。模型覆盖、旧复现与输入限制见 [验收记录](validation.md)。

## 公式与计算设置

2026-11-03 批次通过 `experiments/20261103/complete_official_scores.py` 复用已保存的公式匹配补评 FormulaCDM，并计算 Omni 三项与 MP 八项官方 Overall；该脚本固定选择 30 份历史报告，不用于新 GT。新实验通过 `--cdm` 或配置中的 `formula_cdm` 计算，需要相应 TeX 与渲染依赖。公式编辑距离不能替代 CDM；历史公式分只有在匹配对及环境均一致且有证据时才能继承，不能按模型名或 Excel 行号填入。

MP 官方 CDM 使用的旧式 RANSAC 模型接口与 scikit-image 0.26 不兼容，评测依赖固定为 0.24.0；补评入口同时适配随机种子参数改名。中英文相同公式与不同公式的渲染自检记录在补评批次的 `environment-checks.json`。

`run` 默认开启已验证的大表格精确 TEDS 加速；代价定义与上游一致，不裁剪表格、不近似。分步 `evaluate` 默认使用上游求解器。求解设置留在 provenance，细节见 [架构](architecture.md)。
