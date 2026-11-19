# legacy 129 四项能力 GT 对账

版本：`legacy-129-feature-v3`；数据集：`legacy-features-20261118`；文档：129；页：372。

## 结论

新结构化 GT 作为标题、附录、页眉页脚和视觉块位置的主 GT。它有人工整页快照和标题同步修订，能保留页码、块类型、层级、顺序和坐标。附录边界严格按 PDF2Text 的标题开头及后半段规则计算。

旧 Markdown 作为视觉内容的来源审计：它有图片占位符和混合的表格转录，但没有可靠的页眉/页脚类型；其中表格未逐项标注为 chart，不能直接当作精确 chart-content GT。

因此四项模式采用：附录／页眉页脚使用新 GT；image analysis 将 image 与 seal 一起作为主分母并拆分诊断；chart analysis 使用新 chart 位置加旧 Markdown 候选内容，图表内容正式计分前仍需人工复核。

## 对账统计

| 项目 | 旧 Markdown | 新结构化 GT |
| --- | ---: | ---: |
| 文档 | 129 | 129 |
| 页 | 未可靠保存 | 372 |
| 标题 | 580 个 Markdown heading | 593 个 title 块 |
| 页眉/页脚块 | 无可靠类型 | 528（页码 273；边缘块合计 801） |
| 图片引用/占位符 | 104 / 57 | image/seal 135（其中 seal 33） |
| chart 块 | 无独立类型 | 56 |
| 混合表格 | 304 | table 块见新 GT |
| 附录候选文档 | 2 | 4 |

## 计分边界

- `appendix`：复现 PDF2Text 的 `附录`/`Appendix` 标题开头且位于文档后半段的边界；`附件` 不进入此分母。
- `header_footer`：按新 GT 的 header/footer 和 page_number 边缘块做匹配，并分别报告页码；旧 Markdown 只作文本交叉核对。
- `image_analysis`：主分母统计 image＋seal，并分别报告两类；`seal` 仍需记录 `seal_rec` 配置，因为它是共享上游能力。图片占位符本身不代表图内文字已识别。
- `chart_analysis`：同时报告 chart 定位和有实际文本/表格内容的 chart；当前旧内容是候选 GT，未审核前不宣称精确内容分。

详细 per-document 记录见 `records.json`。运行方式见项目中的 `docs/feature-evaluation.md`。
