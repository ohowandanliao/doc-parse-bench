# legacy 129 四项能力 GT 对账

版本：`legacy-129-feature-v3`；数据集：`legacy-features-20261119`；文档：129；页：372。

## 结论

新结构化 GT 作为标题、附录、页眉页脚和视觉块位置的主 GT。它有人工整页快照和标题同步修订，能保留页码、块类型、层级、顺序和坐标。已人工复核的文档按附录页码补丁；其余仍采用 PDF2Text 后半段标题截断边界作为代理。

旧 Markdown 作为视觉内容的来源审计：它有图片占位符和混合的表格转录，但没有可靠的页眉/页脚类型；其中表格未逐项标注为 chart，不能直接当作精确 chart-content GT。

因此四项模式采用：附录／页眉页脚使用新 GT；image analysis 将 image 与 seal 一起作为主分母并拆分诊断；chart analysis 使用新 chart 位置加旧 Markdown 候选内容，图表内容正式计分前仍需人工复核。

## 对账统计

| 项目 | 旧 Markdown | 新结构化 GT |
| --- | ---: | ---: |
| 文档 | 129 | 129 |
| 页 | 未可靠保存 | 372 |
| 标题 | 580 个 Markdown heading | 593 个 title 块 |
| 页眉/页脚块 | 无可靠类型 | 527（含 1 个页眉图片；页码另有 273；边缘块合计 800） |
| 图片引用/占位符 | 104 / 57 | image/seal 118（其中 seal 33） |
| chart 块 | 无独立类型 | 73 |
| 混合表格 | 304 | table 块见新 GT |
| 附录候选文档 | 2 | 4 |

## 计分边界

- `appendix`：按真实附录标题起算，默认延续到文末；明确要保留的独立尾页单独排除。当前 4 篇、51 页，页段见 `configs/legacy-129-appendix-overrides.json`。
- `header_footer`：按新 GT 的 header/footer 和 page_number 边缘块做匹配，并分别报告页码；旧 Markdown 只作文本交叉核对。
- `image_analysis`：主分母统计 image＋seal，并分别报告两类；匹配块有非空 generated span 就算转出了内容，seal 是 image 的视觉子类型，不是独立开关。
- `chart_analysis`：同时报告 chart 定位和有非空文本/表格内容的 chart；按本次能力口径，非空输出覆盖率可以计分，旧内容仍不能用于严格数值正确率。

## 2026-11-23 人工复核修订

- `bc_001` 第 1 页的股价/指数折线与成交量柱形图：`image` 改为 `chart`。
- `bc_017` 第 12 页的交付质量百分位柱状图：`image` 改为 `chart`。
- `bc_017` 同一图表的框包含图内标题和单位，不含下方图注。
- `bc_017` 第 26–37 页计入附录；第 38 页「行业基准数据发布单位简介」不属于附录，须保留。
- `bc_018` 第 5 页的「以下无正文」是签署提示，移出页眉标注。
- `bc_022` 第 1 页的刊头标志改为 `header_image`，关闭页眉页脚时应去掉。
- `bc_023` 第 4、5、6 页的光谱曲线和复杂散点图：继续保留为 `image`，不按简单统计图表处理。

详细 per-document 记录见 `records.json`。运行方式见项目中的 `docs/feature-evaluation.md`。
