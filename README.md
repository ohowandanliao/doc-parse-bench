# doc-parse-bench

文档解析评测项目：统一标注与模型输出，运行 OmniDocBench、MPDocBench，并研究完整文档的标题结构评价。

标题评测入口：[TitleTree-v2 与 AgentBuilder-v2](docs/agentbuilder-v2.md)；方法论证：[结合完整 FastGPT 与 pdf2text 代码的评分复核](docs/标题评分复核_结合完整FastGPT与pdf2text代码_20261109.md)。代码职责与清理记录见 [项目代码整理](docs/code-organization.md)。

## 日常使用

选择数据版本、文件范围和模型结果，一次运行生成三个榜。活动 GT 为 `annotated-20261111`，81 份／597 页，路径索引在 `data/active_gt.json`。129 份材料的三个版本见 [129 GT 版本登记](docs/feature-evaluation/legacy129-gt-versions.md)。

```bash
git submodule update --init --recursive
uv sync --extra eval --extra dev
source .venv/bin/activate

# 在 YAML 中指定本次数据、模型及新的 output 目录
docbench run configs/standard.yaml
```

当前 CLI 仍保留 `profile: standard/legacy`；standard 作为日常入口，legacy 组合用于历史复现或专门的清洗对照。最终精简方案与尚待实现的部分见 [数据集与评测设计](docs/dataset-evaluation-design.md)。

`run` 仍生成含历史页面 title 的 AgentBuilder 榜；完整文档 TitleTree-v2 通过 `docbench rescore-agentbuilder --inputs /path/to/frozen-inputs.json --output /path/to/new-output` 单独计算，输入契约见 [v2 使用说明](docs/agentbuilder-v2.md)。

## 三个榜与图表专项

| 榜单 | 定义 |
| --- | --- |
| OmniDocBench | 页面原生指标；FormulaCDM 未计算时官方 Overall 留空 |
| MPDocBench | 文档、跨页、标题树和图片定位等原生指标 |
| AgentBuilder | Omni 页面文本准确率 30%＋普通表格 TEDS 30%＋顺序准确率 30%＋页面 title 10% |

完整公式、缺失分项和聚合方式见 [评分细则](docs/metrics-comparison.md)。自建数据上的分数不等于官方原始测试集成绩。

图表内容专项按整列匹配计算明示值命中率，使用经复核的 GT 和来源对齐的模型成品。`content_output_recall` 用于诊断是否实际交付了内容。[图表评分口径](docs/feature-evaluation/scoring.md#图表明示值命中率)

当前 standard 只是关闭历史清洗，仍可能保留 `visual_details`；严格的基础内容与图表附加内容分流尚待实现，现有分数保留其实际输入口径。

## 历史结果与实验复现

完整结果：[评测结果汇总（单文档）](docs/评测结果汇总.md)。这是 2026-11-03 批次、旧 GT 上的历史快照，包含 81 篇／597 页、15 个模型与处理配置，以及 129 篇历史结果和清洗对照；不能作为活动 `annotated-20261111` GT 上的成绩。

该文档随源码提交，可独立分享。主榜统一关闭 legacy；129 篇使用旧评测口径单列。覆盖页数、输入限制与缺失指标均在文内注明。原始分项产物在本地 [结果目录](artifacts/results/README.md)，可运行 `.venv/bin/python experiments/20261103/summarize_results.py` 同步更新汇总文档。验证范围见 [验收记录](docs/validation.md)。

该批次的四个专用脚本集中在 [experiments/20261103/](experiments/20261103/README.md)，用于复现固定模型、GT 和报告。CDM 补评也只适用于该历史批次；通用评测使用 `docbench evaluate --cdm` 或配置中的 `formula_cdm`。需要 TeX Live、ImageMagick、Ghostscript 和中文字体；本机 TeX 环境位于 `.cache/cdm-env/texlive/`。

## 图片工具与历史复现

仅为 review 替换 base64 图片，输出到新目录：

```bash
docbench prepare-markdown /path/to/raw_md /path/to/review_md --replace-images
```

历史 129 复现：

```bash
docbench run configs/historical-reproduction.yaml
```

图片替换与 details 处理可以独立选择；它们不负责开启模型 `chart_analysis`，也不是图表专项开关。原始 postprocess 的行为见 [Markdown 前处理](docs/markdown-preprocessing.md)。

`keep_appendix`、`keep_header_footer`、`image_analysis`、`chart_analysis` 使用独立的 [四功能评测](docs/feature-evaluation/README.md)。从 v2 给新文档补图表与图片 GT 见[补标流程](docs/feature-evaluation/annotation.md)，已评模型见 [Legacy 129 实测](docs/feature-evaluation/legacy129.md)。

## 文档与材料

- [数据集规模、分布与 Marathon 分析](docs/数据集规模与分布分析_20261106.md)：五个公开基准、582 份客户候选、条件样本量、Marathon 八项指标及接入建议。
- [从分片到回答：标题评分详解与 81 份 GT 实例](docs/从分片到回答_标题评分详解与81份GT实例_20261109.md)：先解释 chunking，再手算旧 title／HeadTEDS；实测长标题改正文的不同影响，给出 AgentBuilder-v2 候选与 RAG 验证方式。
- [标题层级评分与 Chunking／RAG 设计](docs/标题层级评分与Chunking_RAG设计_20261107.md)：title／HeadTEDS 错例、原包分片实测、路径 F1 定义与回答质量验证方案，当前为讨论稿。
- [评测口径](docs/evaluation.md)：当前输入、运行、缺失处理和结果。
- [数据集与评测设计](docs/dataset-evaluation-design.md)：最终方向、129 迁移及图表专项条件。
- [评分细则](docs/metrics-comparison.md)：三个榜的指标、权重与聚合定义。
- [数据质量](docs/quality.md)、[数据契约](docs/data-contract.md)、[标注版本管理](docs/annotation-workflow.md)：数据事实、格式与发布。
- [129 GT 版本登记](docs/feature-evaluation/legacy129-gt-versions.md)涵盖旧 Markdown、结构标注和四功能派生 GT。
- [模型适配](docs/model-adapters.md)、[MPDocBench](docs/MPDocBench.md)、[架构](docs/architecture.md)：转换与运行细节。
- [验收记录](docs/validation.md)、[输出异常](docs/output-quality.md)、[截断重跑](docs/inference.md)：验证范围和已知限制。
- [原始材料清单](archives/README.md)：81／129 原包、标注来源与缺失情况。
- [四功能评测](docs/feature-evaluation/README.md)包含补标、评分及历史复算。

`data/annotations/` 保存 81 份标注，`data/predictions/` 保存模型结果，`data/legacy/` 保存旧 129 材料。`archives/` 的原包和 `artifacts/` 的运行产物留在本机，仓库发布指定的 GT 和来源清单。

开发检查：`pytest -q`、`ruff check src tests`、`ruff format --check src tests`。
