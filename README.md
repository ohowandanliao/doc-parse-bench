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

## 两种固定模式

```bash
docbench run configs/standard.yaml
docbench run configs/legacy.yaml
```

| 默认设置 | standard | legacy |
| --- | --- | --- |
| 评测引擎 | 官方 OmniDocBench ＋ MPDocBench | 本工程的历史兼容实现 |
| 评测数据 | 新标注的页面／文档 GT | 旧 129 篇 Markdown GT |
| 图表任务 | chart 与真正 table 区分 | 保留历史 chart 转表格口径 |
| 额外 base64 图片替换 | 关闭，结构化视觉块已统一渲染 | 开启 |
| details 清洗 | 关闭 | 开启原 fix 规则 |
| 文档合并 | 使用模型原生关系 | 保留原文档 Markdown |
| title | 开启 | 开启 |
| 标题树／图片／跨页指标 | MPDocBench 开启 | 不适用 |
| 缺失预测 | 按空预测计分并报告 | 保持历史评分语义并报告 |
| FormulaCDM | 关闭，官方 Overall 留空 | 关闭，官方 Overall 留空 |
| 大表格 TEDS 精确加速 | 开启，复用上游解析与编辑成本 | 默认使用历史实现 |

模式在 `profiles.py` 中已赋好默认值。YAML 主要填写输入、输出和模型；直接选择模式即可运行。需要实验时可显式覆盖：

```bash
docbench run configs/standard.yaml --merge-context
docbench run configs/legacy.yaml --no-replace-images
```

也可覆盖 `--expand-details`、`--allow-missing`、`--cdm`、`--exact-teds` 及其 `--no-*` 形式。覆盖值记录到 `run.json`，不生成额外的模式名。FormulaCDM 需要 TeX Live 等系统依赖。历史 Markdown 无法推断跨页关系，legacy 不接受 `--merge-context`。

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
- [数据质量](docs/quality.md)：审核结果、重复样本与合并条件。
- [数据契约](docs/data-contract.md)：整页快照、坐标、页码和关系。
- [模型适配](docs/model-adapters.md)：官方格式依据与合页边界。
- [架构](docs/architecture.md)：模块职责和开发方式。
- [截断重跑](docs/inference.md)：Unlimited OCR 2 的重跑方案。

开发检查：`pytest -q`、`ruff check src tests`、`ruff format --check src tests`。分步导入／导出及单后端命令保留为开发工具；业务使用优先选择两个固定模式。
