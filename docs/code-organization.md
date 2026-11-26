# 项目代码整理

整理日期：2026-11-16。项目保留通用文档解析评测与标题结构评测两条能力；固定批次的编排代码集中到历史实验目录。

## 后续项目从哪里开始

| 入口 | 代码 | 用途 |
| --- | --- | --- |
| `docbench run` | `pipeline.py`、`cli.py` | 配置数据、适配器和评测后端，准备输入并评分 |
| `docbench import-gt`／`import-pred` | `annotations.py`、`predictions.py`、`schema.py` | 标注和已有模型输出转为统一结构 |
| `docbench export-gt`／`export-pred` | `exporters.py`、`markdown.py`、`context.py` | 按页面／整文档导出内容及跨页关系 |
| `docbench evaluate`／`benchmark` | `backends/`、`benchmark.py` | 隔离运行原生指标，保存覆盖率、来源和分项 |
| `docbench collect` | `benchmark.py`、`leaderboards.py`、`metrics.py` | 汇总已完成实验 |
| `docbench rescore-agentbuilder` | `heading.py`、`agentbuilder_v2.py`、`metrics.py` | 文档标题树、新旧标题分及综合分的冻结输入复测 |
| `docbench build-feature-ir`／`evaluate-feature-matrix` | `mineru_middle.py`、`feature_evaluation/feature_matrix.py` | 129 raw middle_json 回放、清除率及结构诊断 |
| `docbench evaluate-feature-rubric` | `feature_evaluation/feature_rubric.py`、`feature_evaluation/feature_score_cli.py` | 读取冻结 GT 和已对齐的证据，计算四项交付分及误删门槛 |

以上文件均位于 `src/doc_parse_bench/`。对应回归测试在 `tests/`，标题指标重点看 `tests/test_heading_v2.py`。`run` 仍输出含历史页面 title 的 AgentBuilder；完整文档 TitleTree-v2 使用独立复测入口，并未自动替换所有旧榜。

标题方向的方法依据是 [评分复核](标题评分复核_结合完整FastGPT与pdf2text代码_20261109.md)，简明输入与运行说明见 [AgentBuilder-v2](agentbuilder-v2.md)。后续研究需要区分已有树编辑方法的规范化修订与新增贡献：去掉 root 的分母已有 READoc 先例，结构分和 RAG 效用的关系仍需独立验证。

## 四功能文件位置

| 用途 | 位置 |
| --- | --- |
| 正式评分、结构回放 | [`src/doc_parse_bench/feature_evaluation/`](../src/doc_parse_bench/feature_evaluation/) |
| 本轮批次复算与 GT 审阅 | [`src/doc_parse_bench/feature_evaluation/legacy129/`](../src/doc_parse_bench/feature_evaluation/legacy129/) |
| 补标、评分和采集文档 | [四功能文档目录](feature-evaluation/README.md) |
| Legacy 129 GT、输入和报告 | [实测文件位置](feature-evaluation/legacy129.md#文件位置) |
| P2T 内部切分 | P2T 仓库的 `src/pdf2text/core/parse/mineru_subimages.py`，由同目录的 `mineru_client.py` 调用。[推理路由](feature-evaluation/inputs.md#推理路由) |

## 一次性内容的处理

| 原位置 | 判断 | 整理结果 |
| --- | --- | --- |
| `scripts/evaluate_result_bundle.py` | 固定 JSONL 交付包、81／129 文档、旧 GT 与双前处理实验 | 移到 `experiments/20261103/` |
| `scripts/compose_mineru_benchmark.py` | 固定三款 MinerU、外部组合工程及 243 份处理任务 | 移到同一历史目录 |
| `scripts/complete_official_scores.py` | 固定 30 份历史报告及本机公式环境 | 移到同一历史目录 |
| `scripts/summarize_results.py` | 固定 66 份来源与旧总账，不是通用结果收集器 | 移到同一历史目录 |
| 根目录 `allinone.md` | 一次性的论文检索与数据规模研究汇编 | 从主目录移除，原文归入本地 `archives/code-cleanup-20261116/allinone.md` |
| 项目自身的 `__pycache__/`、`.pytest_cache/`、`.ruff_cache/`、`.DS_Store` | 可自动重建的缓存和系统文件 | 删除；继续由 `.gitignore` 排除 |

历史脚本之间存在依赖，四份一起保留才能复现结果；迁移后的说明和命令见 [历史批次](../experiments/20261103/README.md)。所有变更前的脚本、研究汇编及相关文档已先备份到本地 `archives/code-cleanup-20261116/before-cleanup.tar.gz`，逐文件 SHA256 记录在同目录 `manifest.json`。

## 继续保留的代码与材料

| 内容 | 保留原因 |
| --- | --- |
| `heading.py`、`agentbuilder_v2.py`、标题测试及研究文档 | 标题评测方向的实现、方法与反例证据 |
| `compatibility/`、`history.py`、旧 title 算法及历史配置 | 129 份旧数据复现，以及新旧指标对照；现有 CLI、评分器和测试仍有依赖 |
| `compose_bridge.py`、`context.py` | 可复用的预测结构适配与跨页导出，有独立测试 |
| `charts.py`、`mineru_middle.py`、`feature_matrix.py`、质量／重复审计、模型适配器 | 仍有 CLI 入口，不能按旧日期判定无用；四功能回放独立于主线榜单 |
| `vendor/`、`.venv/`、`.cache/cdm-env/` | 原生评测器及运行依赖；CDM 目录内是 TeX 环境 |
| `data/`、原始压缩包、旧 GT 和历史结果 | 数据版本、配对关系、逐文档分数与可复现来源 |
| `artifacts/research/`、验证产物和研究报告 | 文档引用的源码快照、受控扰动和数值证据，不能按“一次运行”直接删掉 |

活动 GT 为 `annotated-20261111`（81 文档／597 页），以 `data/active_gt.json` 为准。旧 129 份的 PDF 在 `data/legacy/dataset/pdf/source/`，GT 在 `data/legacy/groundtruth/`。11 月初结果与该活动 GT 分开保存。

129 GT 的历史 Markdown、结构标注和专项派生视图各有独立版本。[129 GT 版本登记](feature-evaluation/legacy129-gt-versions.md)

## 验证

整理前完整测试为 78 项通过、1 项失败。失败来自本地 GT 集成测试仍要求异常清单为空，而 `annotated-20261111` 已记录一条表格指向标题的无效续接。测试已改为按数据版本精确核对已知异常，并验证它被排除出 IR 和评测关系；未知异常仍使测试失败。

整理后完整 pytest 为 **79 项通过**；`ruff check src tests experiments`、`ruff format --check src tests experiments` 和 `git diff --check` 通过。迁移后四个模块均可导入并正确定位项目根目录，三个支持参数的脚本及通用 CLI 的 `--help` 正常。历史汇总的只读核验确认 **66 份来源报告**的哈希和分数与清单一致，没有重新推理或重跑原生模型评分。
