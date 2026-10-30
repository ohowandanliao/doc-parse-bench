# Unlimited OCR2 截断重跑

本项目默认处理已有输出，不包含权重或 GPU 推理部署。两份需重跑的文档及建议参数在 `configs/unlimited-ocr-2-rerun.yaml`；这是可审阅的配置清单，不会自动调用服务。

| 文档 | 输入页数 | 实际返回页数 | 缺页 | 原 finish |
| --- | --- | --- | --- | --- |
| `rd_545b7a21` | 37 | 11 | 26 | length |
| `rd_567fbc16` | 38 | 7 | 31 | length |

两者 completion_tokens 都是 60000；原始结果尾部分别有空 header 块、公式 token 的大量重复。应排查重复退化和预算，而不是仅提高 max_tokens。

本地原始输出的具体证据：`rd_545b7a21` 中 `header[132, 132, 132, 132]` 重复出现 1079 次，末尾仍在重复；`rd_567fbc16` 最后 3000 个字符中 `varepsilon` 出现 272 次。这已经存在于 `raw` 字符串中，不是合页后生成的内容。它们说明至少这两份存在复读，不能据此断言其余 79 份全部正常。OvisOCR2 的 27 页重复尾部是另一组输出异常。

四模型已补做相同规则的全量复读筛查，统计范围和原文证据见 [重复输出检查](output-quality.md)。本次 Unlimited OCR 2 命中两份文档的 6 页；OvisOCR2 更广的内部循环检查命中 42 页，范围比此前的 27 页尾部检查更大。

推荐顺序：

1. 先对齐官方 `Unlimited-OCR-2/infer.py` 的生成参数：temperature=0、保留 special tokens、启用 `DeepseekOCRNoRepeatNGramLogitProcessor`，多页 ngram_size=35/window_size=1024。已有结果没有保存完整请求参数，不能断言旧推理已经启用了这些设置。
2. 优先使用官方定制 SGLang 的内部 10 页窗口机制，它保留上一窗口的 KV 尾部。官方 README 的开关名是 `SGLANG_UOCR_EANABLE_DOC_LIMIT`，拼写照上游，不自行“修正”。模型／服务实际支持的 max_model_len 要一致；公开模型配置是 131072。
3. 根据服务实际 prompt token 数分配生成预算并保留 margin，不能根据 GT 文本长度分配预算。仅在服务支持且不超上下文限制时提高输出上限。
4. 若仍然截断，再使用独立请求的 10 页窗口、重叠 1 页。原始窗口结果、绝对页码、合并／去重记录都要保存，并标记 `chunked` 实验。独立切窗会丢失一部分跨页上下文，不能冒充原生整篇推理。

验收不能只检查 `.json` 文件是否存在：需要页面标记数与输入一致、finish 非 length、无明显循环尾部，并保留 request、usage、模型版本和服务配置。

原始失败结果保留，用于 baseline 的失败率和得分。重跑结果输出到独立目录后，用 `import-pred --model Unlimited-OCR-2` 重新导入，再导出 OmniDocBench／MPDocBench 输入。若只替换失败样本，汇总报告应明确列出两份 retry 文档和变更的推理参数。
