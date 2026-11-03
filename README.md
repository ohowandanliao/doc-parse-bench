# doc-parse-bench

文档解析混合评测：统一处理标注系统 GT 和模型输出，运行官方 OmniDocBench、MPDocBench，并保留旧版 129 篇的历史兼容评测与 title 指标。

## 安装

使用 Python 3.11（兼容 3.10）：

```bash
git submodule update --init --recursive
uv sync --extra eval --extra dev
source .venv/bin/activate
```

只有两个官方上游是 submodule：`vendor/OmniDocBench/` 与 `vendor/Qwen-Doc/`，MPDocBench 位于后者的 `MPDocBench/`。模型适配、合页、图片清洗和历史兼容逻辑都由本工程维护，不依赖原代码包或 Documents 下的模型工程。

## 前处理与评测

`standard` 和 `legacy` 只选择前处理默认值。数据集、评测器和 AgentBuilder 扩展相互独立：

| 设置 | standard | legacy |
| --- | --- | --- |
| base64 图片引用替换 | 关闭 | 开启 |
| 图表 details 内容展开 | 关闭 | 开启 |
| 数据集与原生评测器 | 由 YAML 指定 | 使用相同 YAML 时不变 |
| 文本／表格／公式／阅读顺序／title 分项 | 均保留 | 均保留 |
| AgentBuilder 总分 | 计算 | 使用相同权重计算 |

```bash
# 同一份数据、同样的 OmniDocBench／MPDocBench 评测器
# 对比实验需在 YAML 中指定不同的 output，已有输出目录不会覆盖。
docbench run configs/standard.yaml
docbench run configs/standard.yaml --legacy
# 等价的完整配置，使用独立输出目录
docbench run configs/legacy.yaml
```

`--legacy` 开启已有图表内容展开及图片替换；`--no-legacy` 关闭该预设。
仍可用 `--replace-images`、`--expand-details` 单独覆盖。模型的 `chart_analysis` 要在生成预测时开启，
本工程不会自动调用模型，也不会从图片占位符虚构图表数据。native／chart-table 任务语义仍需与 GT 对齐。

默认两份配置都使用新标注数据和官方 OmniDocBench／MPDocBench 评测器。
OmniDocBench 按页，MPDocBench 按文档及跨页关系分别报告；两者均附加 AgentBuilder 分项和总分。
原生匹配、计分公式以及 AgentBuilder 权重不会随前处理预设变化。
已有细则包括文本准确度、表格准确度、TEDS、TEDS-S、公式编辑距离／准确度、FormulaCDM（启用时）、
阅读顺序准确度、title 和 AgentBuilder 总分；缺少的指标保持为空，不填入历史分数。

旧 129 篇 Markdown 的复现使用单独配置，显式选择历史兼容评测器：

```bash
docbench run configs/historical-reproduction.yaml
```

该配置的 `input_format: markdown` 与 `backends: [legacy_compat]` 决定历史输入和评测逻辑，
与 `profile: standard/legacy` 无关。旧命令 `evaluate --backend legacy` 保留为 `legacy_compat` 的兼容别名。

`--merge-context`、`--allow-missing`、`--cdm`、`--exact-teds` 也可独立覆盖，最终选项写入 `run.json`。
FormulaCDM 需要 TeX Live 等系统依赖；历史 Markdown 输入缺少页面关系，不能启用跨页推断。

输出目录必须为空，复跑时修改 YAML 中的 `output`。standard 产物：

```text
artifacts/runs/standard/
  run.json                       # 模式、最终选项、显式覆盖值
  prepared/gt_ir/                 # patch 覆盖后的统一 GT 和审计
  prepared/gt/OmniDocBench/       # 单页 GT
  prepared/gt/MPDocBench/         # 文档 GT、跨页关系和标题树
  prepared/pred_ir/<model>/
  prepared/pred/<model>/OmniDocBench/
  prepared/pred/<model>/MPDocBench/
  results/<model>/<benchmark>/    # 指标、逐样本得分、日志、输入哈希
  results/summary.{json,csv,md}
```

## 数据与结果

| 路径 | 内容 |
| --- | --- |
| `data/annotations/` | 新包的 runs、annotations、sources |
| `data/predictions/results/` | 四个模型的原始结果，目录使用完整模型名 |
| `data/legacy/groundtruth/` | 用于复现的 129 篇 GT |
| `data/legacy/dataset/` | 原旧集 PDF 与随包 GT |
| `data/legacy/unpaired_groundtruth/` | 没有对应 PDF 的额外旧 GT，不参与评分 |
| `data/legacy/results/` | 历史预测和 xlsx |
| `data/legacy/formula_cdm/` | 历史公式评分证据 |
| `archives/` | 原始压缩包 |
| `artifacts/` | 本地转换与评分产物 |

数据、压缩包和运行产物不随源码提交。当前新包实际是 81 份／597 页；两份 Unlimited OCR 2 输出截断，共缺 57 页。OvisOCR2 有 27 页检测到重复输出尾部，原内容保留并记录。旧、新集合至少有两份 PDF 完全重复，不能直接相加当作独立样本。

## 质量与复现

```bash
docbench audit-quality artifacts/prepared/baseline/gt_ir/documents artifacts/quality \
  --legacy-pdfs data/legacy/dataset/pdf/source --current-pdfs data/annotations/sources

docbench compare-xlsx \
  data/legacy/results/mineru_344_model_benchmark_pct_0811_with_sf_fastgpt_315.xlsx \
  artifacts/legacy/compatibility --tag p2t1.5.0_mineru3.1.14_fix \
  --output artifacts/legacy/xlsx_comparison
```

历史第 13、14 行各有八项非 CDM 指标复现；第 1 行尚有差异，未宣称整张表复现。详见 [验收记录](docs/validation.md)。

- [评测口径](docs/evaluation.md)：旧集真实模型范围、图表偏向、引擎共存和指标。
- [MPDocBench](docs/MPDocBench.md)：文档级 GT、模型合并、跨页／标题树／图片指标及单独运行。
- [数据质量](docs/quality.md)：审核结果、重复样本与合并条件。
- [数据契约](docs/data-contract.md)：整页快照、坐标、页码和关系。
- [新增标注与版本管理](docs/annotation-workflow.md)：后续批次接入、审核、冻结版本、来源留痕和复评。
- [模型适配](docs/model-adapters.md)：官方格式依据与合页边界。
- [架构](docs/architecture.md)：模块职责和开发方式。
- [截断重跑](docs/inference.md)：Unlimited OCR 2 的重跑方案。
- [重复输出检查](docs/output-quality.md)：四模型复读证据、统一筛查规则与原文报告。

开发检查：`pytest -q`、`ruff check src tests`、`ruff format --check src tests`。分步导入／导出及单后端命令保留为开发工具；业务使用优先选择 YAML 配置和独立前处理开关。
