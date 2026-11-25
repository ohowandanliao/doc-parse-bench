# Legacy 129 内容 GT 标注流程

从原 PDF 和 `legacy-129-feature-v3` 的源块位置生成标注任务。Terra 和 Luna 从原页转录，复核者处理分歧和位置、内容、格式错误，同一份冻结 GT 用于评估 FT 和 8010。现有评分器读取 `doc-parse-bench.feature-rubric-gt.v1`。见 [GT 版本登记](gt-versions.md) 和 [评分字段](feature-evaluation-129-rubric.md#代码输入与运行)。

## 标注步骤

1. **锁定输入**。登记每篇的 `document_id`、PDF 名、SHA-256 和物理页数。用 v3 `records.json` 提取附录页、边缘块、图片、印章和图表。保留源块 ID 和左上角原点的归一化 `bbox`。按文档、物理页、源块 ID 关联已有校准标注。
2. **生成原图**。从同一 PDF 渲染原页和高分辨率裁图。相邻图注、系列名或页边正文会影响判断时附原页。标注任务只装入源材料和字段规则。图表由 Luna 转录，图片和印章由 Terra 转录。页眉页脚先用原 PDF 文字层核对，再用裁图 OCR 对照。图标、OCR 分歧和不完整的框交给视觉标注。
3. **回收结构化标注**。按任务 ID 合并，每个来源目标都有 `proposed`、`diagnostic` 或 `needs_review`。可判分条目附实际字段和评分范围。无法估读、残缺或超出当前评分类型的内容保留来源和诊断原因。
4. **独立复核**。二次标注先看同一原图。按字段比对文本、图表数值和单位、流程图端点和方向。分歧回到 PDF 放大核实。记录最终决定和对应的源图。按文档和类型抽查一致项，覆盖多系列图表、照片图字、残章及有向关系。
5. **合并和冻结**。合并脚本从任务清单回填来源字段，校验每个计分项和诊断项，生成 `rubric-evaluation-gt.json`、`sources.json` 和 `review-status.json`。用当前 `feature_score_cli` 建空证据并载入校验。记录 GT SHA-256、各专项分母、诊断范围和标注模型版本。

## 专项字段

| 专项 | 标注粒度与规则 | 评分器字段 |
| --- | --- | --- |
| 附录 | 按旧版 MinerU 的标题截断规则确定关闭时删除的物理页，在这些页上记录开启时的原文锚点。截断起点之前的受保护内容和独立附件另登记原文锚点。 | `anchors`。保护项另填 `protected: true`、`source_id`。 |
| 页眉页脚 | 从源框核对印刷原文、印刷页码和标志。逐页合并，保留每块的 ID 和位置。 | `blocks` 对象数组，含 `id`、`type`、`text`、`bbox`。标志使用 `header_image` 或 `footer_image`。 |
| 图片、印章 | 图片分文字图、流程图、有字照片和无字照片。逐项转录清晰字段。流程图只标端点和方向都确认的边。印章仅录可核机构、用途、编号或可辨残片。 | `sub_type`、`fields: [{"key", "text"}]`，可选 `relations: [{"from", "to"}]`。无字照片用 `natural_image` 和空 `fields`。 |
| 图表 | 录图内明示数据和所属系列、类别、单位。直接沿用图例的系列名。轴刻度、趋势线和需要估读的数据记诊断。 | `values: [{"series", "category", "value", "unit"}]`。四个字段都是字符串，无单位用 `""`。部分可评分时用 `unscored` 对象登记可定位的排除槽位。 |

`needs_review` 保留待裁决的条目。`diagnostic` 附原图和原因。导入评分清单时，诊断图表用空 `values`，诊断图片用 `sub_type: "other"`，原类型留在审计记录里。相同显式值在不同系列或类别保留各自身份，重复的 `(series, category, unit)` 槽位须定位到不同源块或在复核时合并。

## API 批处理

在本地生成任务清单，用视觉模型 API 提交裁图。每个任务对应一个视觉源块、一个边缘页或一个附录页。首次导入沿用这次的字段规则和复核样例。

| 数据 | 内容 |
| --- | --- |
| 任务输入 | `task_id`、`document_id`、`page`、`source_id`、`feature`、`bbox`、`pdf_sha256`、`crop_sha256`、裁图、可选原页、`prompt_version` 和字段 schema 版本。 |
| 模型响应 | `task_id`、`status`、`scope_note` 和专项字段。模型按严格 JSON schema 返回字段值，合并程序按任务清单补来源字段。 |
| 执行记录 | 每次请求的模型标识、请求 ID、尝试次数、结果状态、用时和用量。原始响应及其哈希保留在批次内。 |
| 复核记录 | 首轮标注、复核模型标注、差异的字段和最终决定。裁决引用同一原 PDF、页号和源框。 |

- 用输入哈希、源块身份和提示词版本确定 `task_id`。首轮和复核各自按 `(task_id, model, prompt_version)` 缓存。批处理中断后重试超时、请求失败和格式错误的任务，复用成功响应。
- 每条响应立即跑 JSON schema 和来源校验。字段类型错误、重复源 ID、缺字段、非法图表数值和无效流程图端点送复核队列。OCR 文字可作对照，高分辨率原图用于裁决。
- 首轮和复核用独立请求。无字照片、残章、带方向的流程图和覆盖多个系列的图表优先复核。质量统计保存每类一致率、复核后的修订数、可计分覆盖及诊断原因。吞吐统计保存每类任务的用量、耗时和重试次数。
- 以 PDF 哈希和任务 ID 将结果并回 v3。汇总时检查来源完整性、主分和诊断数量、页码和边界。新数据集沿用同一批处理规则，并记录各自的版本和分母。

## 验收命令

`template` 产出空预测证据，用于检查对应关系。`score` 加载 GT 并验证约定字段。空预测的总分为 `null`。收到真实的 FT 和 8010 成品证据后，分别调用同一套评分器。见 [正式评测材料](legacy129-next-evaluation-inputs.md#下次必须交付的原始材料)。

```sh
.venv/bin/python -m doc_parse_bench.feature_score_cli template \
  --gt artifacts/legacy-features-20261125/rubric-evaluation-gt.json \
  --model 3.1-ft --stage final \
  --output /tmp/legacy129-ft-blank-evidence.json

.venv/bin/python -m doc_parse_bench.feature_score_cli score \
  --gt artifacts/legacy-features-20261125/rubric-evaluation-gt.json \
  --pred /tmp/legacy129-ft-blank-evidence.json \
  --output /tmp/legacy129-gt-format-check
```

## 本次评测清单

本地清单以 129 篇、372 页为源范围，共 548 条 GT。计分范围为附录截断 48 页、页眉页脚 800 块、图片和印章 89 个目标、图表 47 张及 312 个明示值。另有 20 个保护项、29 个图片或印章诊断目标和 26 张诊断图表。两张五环图的圈位含义无法从原页唯一确认，保留部分转录作诊断。

附录沿用 `8b747ca` 的 MinerU3 规则。只查看 `title`、`doc_title` 和 `paragraph_title`，从后半段首个以「附录」或 `Appendix` 开头的标题所在页截到文末。半段阈值使用从零开始的 `page_idx >= int(total_pages * 0.5)`。根据 v3 标题，关闭时的物理页范围是 `bc_003` 第 20–35 页、`bc_010` 第 13–25 页、`bc_016` 第 26–31 页、`bc_017` 第 26–38 页。`bc_003` 第 15–19 页列为保留项，`bc_003` 第 35 页参考文献和 `bc_017` 第 38 页简介随尾段截除。标题为「附件」的独立文档照常保留。

用最终交付的源页映射填写附录 `off_residual`。截断范围内的物理页仍在关闭态交付时记为 `true`，确认整页截除时记为 `false`。

正式评测使用 `artifacts/legacy-features-20261125/` 下的 `rubric-evaluation-gt.json` 和 `rubric-evaluation-sources.json`，结构来源登记在 `artifacts/legacy-features-20261119/`。本地复核目录 `artifacts/legacy129-formal-gt-review-20261125/` 中的 `review-status.json` 记录每个目标的标注决定，`annotations/` 保留子代理批次及复核结果。
