# TitleTree-v2 与 AgentBuilder-v2

本项目复用 OmniDocBench 和 MPDocBench 的原生评测器，可对版本化的自有 GT 评分。使用相同新 GT 只是可比条件之一；还应固定评测器版本、预测前处理、指标定义及缺失处理方式。

TitleTree-v2 按完整文档比较标题文字、顺序和父子关系，明确虚拟根、空树、归一化与零下界，版本为 `TitleTree-v2/commonmark-math-nfc-1`。它与历史页面 title、MPDocBench 原生 HeadTEDS 分别报告。

AgentBuilder-v2 固定使用：

```text
0.3 × Omni 文本准确率
+ 0.3 × Omni 表格 TEDS
+ 0.3 × Omni 阅读顺序准确率
+ 0.1 × 文档 TitleTree-v2 宏平均
```

四项缺一则不发布总分；已计算的零分正常计入。它是项目的汇总口径，不是 OmniDocBench 或 MPDocBench 的官方 Overall。

```bash
docbench rescore-agentbuilder --inputs /path/to/frozen-inputs.json --output /path/to/new-output
```

输入清单指定固定 GT 和模型预测。带 `scores` 的历史清单会核对预测和 GT 的 SHA256，复算标题与新旧总分，并复用已核验的内容分项。输出目录须为空。原始分数为 0～1，展示时可乘 100 转为百分制。

## 从预测评测

用下面的清单运行 `docbench rescore-agentbuilder`。同一批可直接比较 MinerU 原始响应与通过 `docbench export-pred` 等入口导出的预测。路径相对于 `base_directory`，它自身相对于输入清单所在目录。

```json
{
  "base_directory": ".",
  "gt": "frozen-gt",
  "pdf2text_config": "postprocess-config.json",
  "models": [
    {"model": "MinerU-3.x", "raw": "mineru-raw"},
    {"model": "OvisOCR2", "predictions": "prepared/ovis"}
  ]
}
```

`predictions` 指向同时含 `OmniDocBench/` 逐页 Markdown 与 `MPDocBench/` 全文 Markdown 的目录。`raw` 指向 MinerU 3.x 网关响应或 `middle_json` 文件或目录，文件名对应 GT 文档 ID。使用 `raw` 时，在装有评测依赖和原批次 PDF2Text 渲染依赖的环境运行，并提供该批次结构修复关闭的 `pdf2text_config`。

MinerU 3.x 的 `para_blocks` 可能已把续表并入首页。评测入口按源页、块索引和位置框恢复 `preproc_blocks` 中的表格片段，交给原批次的 PDF2Text 后处理和渲染器生成 Omni 逐页预测。导出清单记录原始响应哈希和恢复位置。片段缺失或对应不唯一时会报出文件、页码及块索引。全文 Markdown 由原始 `para_blocks` 渲染。

每个模型的 Omni 文本、表格和阅读顺序分项与全文 `TitleTree-v2` 一起写入 `summary.json`。默认使用精确 TEDS 加速。清单可用 `allow_missing: true` 将缺失的预测按空输出计入固定范围。

## 模型推理设置

评测器只对已有预测评分，不负责开启或关闭模型 thinking。比较模型/后处理时应明确记录 thinking 的有效设置、模型版本、输出预算及失败回退策略；仅未发送参数不能证明 thinking 已关闭。

2026-11-12 的 PDF2Text 1112 对照使用新标注集 `annotated-20261111`（81 文档/597 页），DeepSeek Flash 明确发送 `{"thinking":{"type":"disabled"}}`。Qwen 3.6/3.8 尚未进行真实内网评分；建议首轮显式关闭 thinking 保持对照口径，若评估 thinking 收益则另设固定条件的对照。具体关闭参数取决于部署接口。

对应的 PDF2Text 适配客户端只向 DeepSeek 显式发送上述 thinking 参数；当前对 Qwen 未发送 thinking 开关，模式取决于内网服务默认值。首次对照应在服务端明确关闭并记录，不能从是否显示思考内容反推开关状态。
