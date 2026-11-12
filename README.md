# doc-parse-bench

统一导入版本化标注和已有模型输出，调用 OmniDocBench、MPDocBench 原生评测器，并提供项目级 AgentBuilder 汇总。评测器位于 Git submodule；原始数据和运行产物不随源码提交。

## 安装与运行

使用 Python 3.10/3.11。在配置文件中填写自己的数据路径、数据版本、模型结果及新输出目录。

```bash
git submodule update --init --recursive
uv sync --extra eval --extra dev
source .venv/bin/activate
docbench run configs/standard.yaml
```

`standard`/`legacy` 控制预测前处理预设，不切换数据集或评分器。缺失、预处理及可选指标设置应在比较前固定并记录。

## 标题与综合分

历史页面 `title`、MPDocBench 原生 `HeadTEDS`、项目级完整文档 `TitleTree-v2` 分别报告。AgentBuilder-v2 使用 Omni 页面文本、TEDS、阅读顺序各30%，以及文档 TitleTree-v2 宏平均10%；四项不齐则不发布总分。

```bash
docbench rescore-agentbuilder --inputs /path/to/frozen-inputs.json --output /path/to/new-output
```

[新版定义、输入核验与thinking记录](docs/agentbuilder-v2.md)明确口径和复现条件。它不是两个原生评测器的官方 Overall。FormulaCDM/Figure等必要分项未运行时，相应官方 Overall 留空。

模型的thinking设置属于推理条件，应显式记录；不传参数不代表已关闭。

## 检查

```bash
pytest -q
ruff check src tests
ruff format --check src tests
```
