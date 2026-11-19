# 129 四功能评测结果（2026-11-20）

本文只解释当前 `1120-feature-eval-package.zip` 的 129 份评测结果。旧的
`1119` 结果、`/v1/pdfparse` 最终 Markdown 代理结果和历史分数不参与本结论。

当前结果包位于本机：

```text
/Users/yixuan/Documents/pdf2text-materials-20261119/evaluation-packages/1120-feature-eval-package.zip
```

评测对象是 PDF2Text 的四个内容开关：`keep_appendix`、`keep_header_footer`、
`image_analysis`、`chart_analysis`。输入为 `legacy-129-feature-v3`（129 个文档、
372 页），上游分别是 `3.1-ft`（8009）和 `3.1-origin`（8010）。两批都使用
`mineru3`、部署快照 `1806ec1` 的 `mineru_filters.py`，并固定
`relevel_titles=true`、`title_rules=false`。

## 运行口径

每个上游只做两次 MinerU 采集：

```text
A: image_analysis=false
B: image_analysis=true
```

之后在本地离线回放过滤器，得到 `off`、`appendix`、`header_footer`、`image`、
`chart` 和内部对照 `controls/image_off`。因此一个上游是 `129 × 2 = 258`
次 MinerU 解析任务，而不是五组各跑一遍。

`bc_xxx` 是评测内部 ID，不是 PDF 文件名。source 的对应关系在
`artifacts/legacy-features-20261118/records.json` 的 `document_id` / `source_name`
字段中；例如：

```bash
jq -r '.records[] | select(.document_id == "bc_078") |
  [.document_id, (.source_name + ".pdf")] | @tsv' \
  artifacts/legacy-features-20261118/records.json
```

会得到 `bc_078    广东城规院_惠玩甘青_7.pdf`。下面的案例表均同时给出这两个
名字，PDF 都在 `data/legacy/dataset/pdf/source/`。

image 与 chart 的 on/off 评分必须使用同一份 B 识别结果。`image` 组关闭
`chart_analysis`，所以 chart 会降级为 image；`chart` 组开启它，所以 chart
保留为 chart。这个设计保证了开关清除率是成对的，也决定了 image 和 chart 的
预测数量不能从两张独立表中直接相加做总体 precision。

## 每个指标怎么读

| 指标 | 计算 | 当前实际含义 |
| --- | --- | --- |
| `on_recall` | 匹配上的 GT / GT 总数 | 该功能应该识别的块或页，找到了多少。匹配按页、类型或 bbox 进行。 |
| `on_precision` | 匹配上的预测 / 预测总数 | 输出的块有多少确实对应 GT；预测过多会降低它。 |
| `on_output_coverage` | 匹配且有非空生成内容的 GT / GT 总数 | GT 视觉块中最终有多少产生了描述或 chart body。它不是文字、数值或描述正确率。 |
| `clear_rate` | 关闭后被清掉的“关闭前已有输出” / eligible | 开关是否真的执行了清除。分母不是固定的 GT 数，而是该批识别实际产生的可清除内容。 |
| `off_body_retention` | 关闭附录后仍保留的正文页 / 正文页总数 | `keep_appendix=false` 是否误删正文。 |
| `on_page_number_recall` | 匹配的页码块 / GT 页码块 | 页码这一类 header/footer 边缘块的单独召回。 |
| `off_visual_retention` | image 关闭对照中仍保留的视觉块 / 关闭前视觉块 | 关闭 image analysis 后，图片框本身是否还在；这里检查的是描述清除，不是删除图片框。 |
| `off_downgrade_rate` | 关闭 chart 后变成 image 的 chart / 关闭前 chart | `chart_analysis=false` 是否把 chart 降级为 image。 |

`clear_rate=100%` 不能解释成模型的识别能力是 100%；它只说明过滤器对已经
识别出来的内容执行正确。识别漏掉的块不会进入清除率分母。

## 两批 129 的主结果

| 功能 | 指标 | ft（8009） | origin（8010） |
| --- | --- | ---: | ---: |
| appendix | 召回 | 48/48 = 100.00% | 48/48 = 100.00% |
| appendix | 清除率 | 48/48 = 100.00% | 48/48 = 100.00% |
| appendix | 正文保留 | 324/324 = 100.00% | 324/324 = 100.00% |
| header/footer | 召回 | 626/801 = 78.15% | 621/801 = 77.53% |
| header/footer | 精确率 | 626/685 = 91.39% | 621/669 = 92.83% |
| header/footer | 页码召回 | 219/273 = 80.22% | 219/273 = 80.22% |
| header/footer | 清除率 | 626/626 = 100.00% | 621/621 = 100.00% |
| image（含 seal） | 召回 | 72/135 = 53.33% | 80/135 = 59.26% |
| image（含 seal） | 精确率 | 72/79 = 91.14% | 80/96 = 83.33% |
| image（含 seal） | 输出覆盖率 | 55/135 = 40.74% | 70/135 = 51.85% |
| image | seal 召回 | 12/33 = 36.36% | 10/33 = 30.30% |
| image | 清除率 | 56/56 = 100.00% | 79/79 = 100.00% |
| chart | 召回 | 56/56 = 100.00% | 56/56 = 100.00% |
| chart | 精确率 | 56/77 = 72.73% | 56/79 = 70.89% |
| chart | 输出覆盖率 | 56/56 = 100.00% | 56/56 = 100.00% |
| chart | 清除率 | 77/77 = 100.00% | 78/78 = 100.00% |
| chart | 关闭后降级为 image | 77/77 = 100.00% | 79/79 = 100.00% |

结论很直接：附录两批相同；header/footer 基本持平，ft 多找 5 个块但多报
一些；chart 的定位召回两批都是满分；image 是主要差异，origin 找到更多框且
产生更多描述，ft 的预测更保守、精确率更高，seal 反而是 ft 略好。

## image + chart 的合并诊断

这部分是诊断指标，不替换四个功能的主分数，也不并入 AgentBuilder 或
TreeTitle-v2。GT 视觉总数为：

```text
image/seal 135 + chart 56 = 191
```

合并时只使用 `chart_analysis=true` 的 `chart` IR 作为唯一预测集合。这样每个
预测框只计一次，避免把 `image` 组中“chart 降级后的 image”再次计数。

### 1. 类型敏感口径

预测必须与 GT 类型一致：image/seal 只能命中 image/seal，chart 只能命中 chart。

| 上游 | 预测视觉框 | 命中 | 召回 | 精确率 | F1 | 输出覆盖 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| ft | 156 | 128 | 128/191 = 67.02% | 128/156 = 82.05% | 73.78% | 111/191 = 58.12% |
| origin | 175 | 136 | 136/191 = 71.20% | 136/175 = 77.71% | 74.32% | 126/191 = 65.97% |

其中 `128 = 72 个 image/seal + 56 个 chart`，`136 = 80 个 image/seal + 56
个 chart`。这个口径回答的是“图片和图表类别是否都判对”。

### 2. 只看视觉位置的口径

另算一行把类型混淆视为视觉框命中：只要同页 bbox IoU ≥ 0.5，就算这个视觉
对象被找到，不要求 image 与 chart 标签一致。

| 上游 | 命中 | 召回 | 精确率 | F1 | 输出覆盖 |
| --- | ---: | ---: | ---: | ---: | ---: |
| ft | 149/191 | 78.01% | 149/156 = 95.51% | 85.88% | 132/191 = 69.11% |
| origin | 159/191 | 83.25% | 159/175 = 90.86% | 86.89% | 148/191 = 77.49% |

image 的“类型敏感召回”是 72/135（ft）和 80/135（origin）；放宽类型后变成
93/135 和 103/135。也就是说，ft 有 21 个、origin 有 23 个 image GT 被一个
位置重合的 chart 框覆盖。它们在严格 image 分数里算漏检，同时在 chart 精确率
里算多报，是同一批类型混淆的两面：

```text
ft:     21 个 GT image 被标成 chart；chart 误报 21 个
origin: 23 个 GT image 被标成 chart；chart 误报 23 个
```

所以不能只看 `image recall=53.33%` 就说这些图片完全没有被模型找到；其中相当
一部分是“找到了位置，但类别判成 chart”。同时也不能把放宽类型后的 78.01% /
83.25% 当作严格的 image 识别分数，它只是视觉定位诊断。

## image 覆盖率为什么差 11.11 个百分点

主表的 coverage 是：

```text
ft:     55 / 135 = 40.74%
origin: 70 / 135 = 51.85%
```

在已经匹配的框里，ft 实际产生内容的比例是 `55/72=76.39%`，origin 是
`70/80=87.50%`。因此差距同时来自两件事：origin 匹配到的图片更多，而且匹配
后更常生成描述。

GT 的 135 个 image 视觉块由 102 个普通 image 和 33 个 seal 组成。严格类型口径
拆开后是：

| 子类 | ft 命中 | ft 有输出 | origin 命中 | origin 有输出 |
| --- | ---: | ---: | ---: | ---: |
| 普通 image（102） | 60 | 50 | 70 | 66 |
| seal（33） | 12 | 5 | 10 | 4 |

差距主要来自普通 image 的检测粒度和描述产出，不是 seal；seal 方向相反，ft
略好。

### 具体文档

以下数字均为 `image` 主指标的严格类型口径，格式是“GT / 命中 / 有输出”。

| 文档 | GT | ft | origin | 原因 |
| --- | ---: | ---: | ---: | --- |
| `bc_078` | 4 | 4 / 2 / 0 | 4 / 4 / 4 | 一页 2×2 四张照片。ft 把上排、下排各合并成一个框；origin 拆成四框并逐图生成描述。 |
| `bc_059` | 5 | 5 / 1 / 1 | 5 / 5 / 5 | 底部四张并排小图被 ft 合成一个宽框，单图 IoU 不足；origin 四张分别命中并输出。 |
| `bc_077` | 2 | 2 / 0 / 0 | 2 / 2 / 2 | 左右两张图被 ft 合成一个横跨框，和任一 GT 的 IoU 都不到 0.5；origin 分开。 |
| `bc_065` | 3 | 3 / 1 / 1 | 3 / 3 / 3 | 底部并排图被 ft 合并；origin 分成三张并输出线路图文字。 |
| `bc_062` | 3 | 2 / 2 / 0 | 2 / 2 / 2 | 两批都找到两个框；ft 没有生成内容，origin 输出 Mermaid。coverage 只认非空，不判断 Mermaid 是否正确。 |

四个合并粒度最明显的文档（`bc_078`、`bc_059`、`bc_077`、`bc_065`）贡献了
15 个 coverage 差值中的 12 个；`bc_062` 再贡献 2 个，剩余差异来自少量文档。

## 按 source 复核的代表性掉分案例

不逐条列 129 份，只列能代表主要根因的样本。页码是 source PDF 的物理页码；
预测框和 GT 的具体 bbox 可在结果包的 `ft/ir/`、`origin/ir/` 和
`per_document.csv` 中继续追踪。

| bc ID | source PDF | 页码 | 看到的现象 | 根因归类 |
| --- | --- | ---: | --- | --- |
| `bc_078` | `广东城规院_惠玩甘青_7.pdf` | 1 | source 是 2×2 四张照片；ft 输出上下两条宽框，origin 输出四个单图框。 | 相邻图片合并，单图 IoU 和逐图描述都受影响。 |
| `bc_077` | `广东城规院_惠玩甘青_4.pdf` | 1 | source 是左右两张照片；ft 输出一个横跨两图的框，origin 拆开。 | 图片粒度过粗，ft 两张都无法按 IoU 命中。 |
| `bc_059` | `依爱消防_工程维修手册_44.pdf` | 44 | source 底部有四张并排电路照片；ft 合成一个宽框，origin 四框全部命中。 | 小图拼排导致合并框覆盖多个 GT。 |
| `bc_065` | `依爱消防_电气火灾监控系统_5.pdf` | 1 | source 有三张线路/示意图；ft 只命中一个合并框，origin 命中三张。 | 多图布局下的检测粒度差异。 |
| `bc_016` | `4-1统计图3.pdf` | 9、10、11、15、24 | source 中有普通图；两版在相同位置输出 `raw_type=chart`。 | image→chart 类型混淆；严格 image 分低、chart precision 也被拖低。 |
| `bc_062` | `依爱消防_电气火灾监控系统_2.pdf` | 1 | 两版都找到 2/3 个图；ft 无生成内容，origin 生成 Mermaid。 | 同框的内容生成差异；coverage 只认非空，不判断 Mermaid 正确性。 |
| `bc_003` | `1-3单元格内换行1.pdf` | 20、21 | source 从普通正文切换到评估报告附录，页眉从 `T/CCUA 005—202` 变成 `T/CCUA 005—2023`，页码同时有 `14`、`第1页/共6页`、物理页 `15`。 | 两版共同漏掉格式变化后的 header/page number，属于上游边缘块识别问题。 |
| `bc_014` | `4-1统计图1.pdf` | 1、4、6 | source 页眉含统计公报标识、页脚页码，且页面内图表密集；其中一个 GT image 被输出成 chart。 | 边缘块/视觉类型同时存在，chart 误报与 image 漏检相互对应。 |
| `bc_019` | `4-3扫描2.pdf` | 1、3、5、8 | source 是扫描合同和大量红色印章；很多 seal 没有独立视觉框。 | 扫描/印章小目标漏框，属于 image 子类 seal 的召回问题。 |

从全量统计看，header/footer 的两版共同缺口主要集中在
`bc_003`、`bc_010`、`bc_016`、`bc_017`：合计漏 69 个 header 和 54 个 page
number。它们解释了绝大部分 header/footer 低召回；ft 与 origin 在这里几乎没有
差异。image 的模型差异则集中在多图拼排、扫描印章和 image→chart 混淆三类。

### image/chart 类型混淆例子

`bc_016` 第 9 页的 GT image bbox 是
`[0.23, 0.37, 0.76, 0.57]`。两批都输出了几乎相同位置的框，但
`raw_type=chart`。因此它在严格 image 评分中是漏检，在 chart 评分中是一个额外
chart；在“只看视觉位置”的合并诊断中则算命中。这正是两个主指标同时受影响的
原因。

### seal 例子

`bc_018` 有 11 个 seal。ft 命中 8 个，其中 4 个产生印章文字；origin 命中 5
个，其中也有 4 个产生文字。`bc_019` 有 22 个 seal 加 1 个普通 image，ft 命中
4 个且 1 个有输出，origin 命中 5 个但没有输出。seal 不应单独作为第五个开关，
它只是 image analysis 的视觉子类型诊断。

## 结论边界

1. 四个开关的过滤行为都通过了：两批 `clear_rate` 均为 100%。这证明关闭开关
   会清掉过滤器定义的内容，不证明模型没有漏检。
2. 129 的 image/chart GT 只有位置和类型，缺少逐图描述和图表数值的人工真值。
   `on_output_coverage` 只能回答“有没有非空输出”，不能回答内容是否正确。
3. 两个上游是独立采集，跨 `ft`/`origin` 的差异包含 MinerU 识别和模型输出波动；
   每个功能内部的 on/off 是同一份 raw 的配对，清除率结论更可靠。
4. 这份报告只属于四功能专项，不改变原有 AgentBuilder-v2、TreeTitle-v2、
   OmniDocBench 或 MPDocBench 的分数。

重跑入口仍见 [四功能专项评测](feature-evaluation.md)。结果包中的
`ft/scores/metrics.json`、`origin/scores/metrics.json` 和 `per_document.csv`
分别保存汇总与逐文档证据；raw middle_json 未重复放进压缩包，采集哈希在各自
`raw-*-manifest.json` 和 `provenance.json` 中。
