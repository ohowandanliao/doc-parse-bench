# `image_block` 复合图分析缺口与补偿方案

更新时间：2026-11-24。结论基于 P2T 参考的 MinerU 3.3.1／`mineru-vl-utils` 1.0.5 代码逻辑；采集包的 FT／Origin 响应实际报告 MinerU 3.1.14，二者版本来源分别记录。

## 结论

这不是“2605 所有输出都被跳过”。页面布局检测仍然执行，独立 `image`／`chart` 仍然可以进入内容分析。在本次 FT 129 包中，81 个顶层 `image` 块里有 10 个 `image_block` 复合父框，涉及 6 篇文档和 27 个子框；其余 71 个顶层 image 不走这条复合容器 skip 路径。

但对这 10 个复合父框，3.3.1 的内容分析链确实形成了一个闭环缺口：

```text
image_block 父容器        → skip_list 直接跳过
被父容器覆盖的 image/chart → non_standalone_visual_indices → 跳过
two_step_extract           → 只给返回 indices 回填内容
regroup_visual_blocks      → 只留下父 image + sub_images bbox/type
```

因此父图 body 没有内容，子图也没有内容或 subtype。若交付要求复合图的图内文字、表格、描述或 subtype，这属于 MinerU 3.3.1 的**功能缺口／bug**：容器跳过本身可以是避免父子重复抽取的设计，但代码没有提供替代的父图或子图分析路径。

这也解释了为什么 2605 与 2604 的比较会被布局粒度混淆：Origin 在本批没有 `sub_images`，FT 才触发了这个 skip 缺口。空父图不能直接判成 FT 模型不会识别；它首先是上游布局和内容抽取编排问题。

## 补偿原则

一个复合父框一次只选择一种分析单位，默认不父子双跑：

1. **组图语义**：共用一个图号／图注、装置和面板组成一幅完整示意，或网格本身应作为一个视觉单元。选择整父图一次，最终交付父图。
2. **独立面板语义**：每个面板是独立照片、独立图表或独立接线图，且拆开不会破坏源图归属。选择各子图一次，最终拆分交付。
3. **父图失败**：如果父图分析返回空、再次返回 `image_block`、超时或未采到，保留父图资产并记录 `parent_analysis_unavailable`；不能复制子图 subtype 或把局部结果拼成整图答案。
4. **子图失败**：如果独立面板的请求未采到或结果不足以安全拆分，保留父图，不把失败当作模型内容错误。
5. **有限回退**：只有在预先判断为独立面板时，才允许父图／子图路线回退；组图不因父图失败自动拆成子图。每次回退单独记录请求数和路线。

这样既补上复合图内容分析，又避免默认把请求数翻倍。分析单位、交付单位、实际 type／subtype、原始响应和失败原因都写入日志和证据。

## 两条实现路线

### 首选：固定布局抽取

3.3.1 配套的 `mineru-vl-utils` 已有 `extract_with_layout`／`aio_extract_with_layout`。P2T 拿到原始父框和图片资产后，可以把一个父框或一个子框声明为外部 `image`／`chart` layout，调用同一 `Image Analysis` 提示和后处理，得到 `type`、`sub_type`、`content`，不会再次做页面布局。

这条路线适合整父图补偿，因为它避免父图再次被识别成 `image_block`。现有 `/file_parse` 表单没有外部 layout 参数，所以内网 AI 需要确认同一 upstream 是否提供内部调用或增加一个只供 P2T 使用的固定区域接口；不能仅凭本机 Python 函数存在就宣称线上已经可用。

### 兼容过渡：crop-as-page

当前 P2T 已有裁图上传 `/file_parse` 的能力。它可以作为过渡路线：父图或子图裁成 JPEG，发一次 `image_analysis=true` 的结构请求，读取真实 `type`／`sub_type`／内容。

这条路线会再次布局，父图可能再次产生 `image_block`。因此必须：

- 把路线标成 `crop_page`，不能写成 fixed-layout；
- 将 `unresolved`、空输出、超时、未调用分别记录；
- 父图响应再次出现 `image_block` 时不伪造父图内容；
- 只有结果满足完整性条件时才拆分或回填；
- 用内网真实响应验证端到端，而不是用离线 4 秒预算判断成功。

## 129 当前最小补偿清单

HTML 审阅已把 10 个父框分成待补单位：

- **整父图 4 个**：`5-1双栏表格2.pdf` 第 2 页 Fig. 1、第 5 页 Fig. 6；`依爱消防_电气火灾监控系统_2.pdf` 第 1 页两组共图注线路图。当前没有对应整父图响应。
- **子图 14 个**：双柱图 2 个、维修手册独立照片 4 个、消防系统 `_5` 两幅独立接线图 2 个、惠玩甘青独立照片 6 个。已有 14 份可复用真实子图响应。

详见[父图／子图审阅页面](../../artifacts/legacy129-subimage-20261123/analysis-units-review-20261124/review.html)和 `analysis-plan.json`。页面展示了全部拆分的损失：线路组图被切成半框，Fig. 6 被切成文字碎片；双柱图的 10 个明示值是拆分正例。

## 评测和上线归因

- 复合父框空输出：先归为 `upstream_layout_analysis_gap`，不是 FT 模型失败。
- 已补得子图内容：按实际响应评 subtype、字段、表格值；不能把子图结果升级成父图关系正确。
- 父图固定区域响应：可进入父图内容和 subtype 评分；若只采到布局或再次返回 image_block，记 evidence missing。
- P2T 拆／保误差：归到 `p2t_unit_selection`、`p2t_attribution` 或 `p2t_filtering`，与模型识别错误分开。
- 两个开关都关：不发父／子图补偿请求，过滤和最终交付与原 ZIP 一致。
- 质量分和误删 gate 分开；局部图表 F1、非空率和请求数不能代替四专项总分或线上 p95。

## 代码推进顺序

1. 在 `mineru_subimages.py` 增加统一 `AnalysisPlan`：`parent`、`children`、`none`，并让 `SubimageDecision` 记录 `analysis_unit`、`route`、`unresolved_reason`。
2. 增加父图完整裁图和固定 layout analyzer 接口；保留 crop-as-page 兼容实现，先不自动父子双跑。
3. 把当前 `keep_shared_caption`／`keep_multirow` 的“直接跳过分析”改成 `parent` 计划；独立 strip 继续 `children` 计划；图表单开候选单独测，不扩大为所有 image。
4. 为父图成功、父图 unresolved、独立子图成功、子图失败、双关回退增加测试；保留普通 image/chart、附录、页眉页脚回归。
5. 只用内网真实 fixed-layout 或 crop-page 响应完成父图证据；再冻结 final evaluation evidence 和 P2T 补丁。

