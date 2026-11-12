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

输入清单指定固定 GT、历史报告及预测目录。入口核对预测和 GT 的 SHA256，复算标题与新旧总分；仅复用经哈希验证的内容分项，不重新调用识别模型。输出目录须为空。原始分数为 0～1，展示时可乘 100 转为百分制。

## 模型推理设置

评测器只对已有预测评分，不负责开启或关闭模型 thinking。比较模型/后处理时应明确记录 thinking 的有效设置、模型版本、输出预算及失败回退策略；仅未发送参数不能证明 thinking 已关闭。

2026-11-12 的 PDF2Text 1112 对照使用新标注集 `annotated-20261111`（81 文档/597 页），DeepSeek Flash 明确发送 `{"thinking":{"type":"disabled"}}`。Qwen 3.6/3.8 尚未进行真实内网评分；建议首轮显式关闭 thinking 保持对照口径，若评估 thinking 收益则另设固定条件的对照。具体关闭参数取决于部署接口。

对应的 PDF2Text 适配客户端只向 DeepSeek 显式发送上述 thinking 参数；当前对 Qwen 未发送 thinking 开关，模式取决于内网服务默认值。首次对照应在服务端明确关闭并记录，不能从是否显示思考内容反推开关状态。
