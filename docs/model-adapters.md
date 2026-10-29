# 模型适配及官方依据

本机参考代码位于 `Documents/`，评测器本身只依赖小型转换库，不 import 模型推理工程。下载清单原件是同级 `OCR官方代码来源.md`。

| 模型 | 已有结果 | 适配方式 | 官方代码依据 |
| --- | --- | --- | --- |
| MinerU 2.5 Pro | `pages[].blocks` | 直接保留类型／bbox／content；title 缺 level 时记为 1；保留 `merge_prev` | [MinerU](https://github.com/opendatalab/MinerU)，本机 `505fcb09dba26baeb914871ab131c4698ac6067e` |
| NaviDC / TeleOCR | `pages[].blocks` | 结构化块渲染，恢复原本未加 `#` 的标题，HTML 表格不改写内容 | [TeleOCR](https://github.com/caipeng328/TeleOCR)，`1e71f4fe792d12bbb86d2671c5ed6f3a1499b27d` 的 `vlm_middle_json_mkcontent.py` |
| OvisOCR2 | `pages[].md`，blocks=null | 按 Markdown 结构提取标题／表格／文本，解析 `images/bbox_l_t_r_b.jpg` 为视觉块 | [OvisOCR2](https://huggingface.co/ATH-MaaS/OvisOCR2)，`cbdede82e048659b83310476ff807da825f8fe78` 的 README 推理 prompt |
| Unlimited OCR2 | `raw` 原生文档 token 字符串 | 重新解析 `<PAGE>/<BLOCK>/<LEVEL>/<FORK>/<MERGE>`，恢复跨页链、标题 level 和 bbox | [Unlimited-OCR](https://github.com/baidu/Unlimited-OCR)，`6c5d1906ba638a7cd87bc00f14452a47fdabf16b` 的 `utils/process_unlimitedOCR2.py` |

## Unlimited OCR2

原结果的 `pages[].blocks` 由旧版简化解析器生成，部分 title 被当成 unknown，正文还含 `title<LEVEL1>...<FORK>`；因此存在 `raw` 时优先重新解析 raw。支持 LEVEL 在 bbox 前／后两种写法，保留空页，不能因空页面而让后续页码左移。

`cross_text/append_text`、`cross_table/append_table` 转成预测自己的 `truncated` 关系，`<MERGE>` 保留同页拼接。图表坐标从 0–1000 转成归一化坐标。与官方转换器不同，默认不强制把多个顶层标题改成单根，保留模型原始标题树用于公平比较。

两份原始结果 `rd_545b7a21`、`rd_567fbc16` 的 `finish=length`，`completion_tokens=60000`，分别只返回 11/37、7/38 页。适配器会报告这 57 页缺失；转换逻辑无法恢复模型从未输出的内容。

## MinerU / NaviDC

标题类型来自模型而非 GT；已保存结果若没有原生层级，只能默认一级并记录 `level_source=default_missing_native_level`。层级信息已经丢失时，单靠这些结果不能宣称还原了原始标题树。后续重新推理应保存原生 level 和未经简化的结果。

空 list 容器不重复渲染，但容器内已展开的正文子块保留。`table_body` 或 content 中的 Markdown 表格会转成 HTML；正文、公式和表格内容不会从 GT 补全。当前 MinerU 原生 chart 块中有数据表，native 评测把它渲染为视觉块，chart-table 才把它当表格。

另支持 MinerU `*_content_list.json`（`page_idx` 从 0 开始）及普通 `.md`／`.txt`。输入目录优先读取顶层 JSON，否则读取 Markdown，否则 txt；不递归混读多个输出版本。原生复杂 middle JSON 应先导出为明确的 `pages/blocks`，避免把模型内部容器误当正文。

## 上下文合并

`export-pred --context native` 保留模型原生关系。`--context conservative` 在原生关系基础上，检查相邻页面的文本开放句尾、续句、列对齐或重复表头，生成带 evidence 的预测链接；Ovis 没有正文 bbox 时使用更严格的内容条件。中文开放虚词规则和无几何表头匹配仍是启发式，应作为独立后处理实验比较。

OmniDocBench 始终导出页内块，跨页拼接只作用于 MPDocBench。合并器只读预测，不接收 GT 文本或 GT 链接。标题层级保持模型输出，不通过对照 GT 优化。
