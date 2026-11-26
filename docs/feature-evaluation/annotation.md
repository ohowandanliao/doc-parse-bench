# 从标注 Agent v2 补齐专项 GT

新增 PDF 批次从标注 Agent 的 v2 页面终态提取目标。v2 提供物理页、块 ID、类型和位置，原 PDF 提供图内文字、关系和数值。补标结果按源块合并成专项清单，可以单独补图表、图片或印章。

## 建立标注任务

1. 用 `docbench import-gt` 导入新批次。优先用 `annotations/` 的人工页面快照，其余用 `runs/` 的标注 Agent 输出。登记 `document_id`、PDF 哈希、物理页数和结构版本。[标注批次导入](../annotation-workflow.md)
2. 由终态提取候选块。每项保留 `source_id`、从 1 开始的物理页、归一化 `bbox` 以及父子关系。漏框、合框或错类由复核者在原 PDF 上确认修订，保留旧框和处理记录。
3. 从原 PDF 生成清晰裁图，并在需要图注、图例、面板关系或单位时附原页。沿用旧标注的字段和区域时，记录来源并重新核对原图。
4. 标注 Agent 只接收原 PDF、裁图、v2 结构和字段规则。可由 Luna 主标图表、Terra 主标图片和印章。第二位独立标注者从同一源图复核，分歧由复核者按原页裁决。

## 图表内容

- 以一张源图为单位，分别记录原图明示的数值、系列、类别和单位。类别用实际年份、分组或行名，系列用可核实的图例或原图说明。
- 数值用字符串，记录原图显示的数值精度。`97.5%` 记录为 `value: "97.5"`、`unit: "%"`。无单位用 `""`。
- 刻度、趋势线和估读点只作诊断。部分系列缺明示值时，`unscored` 按 `series`、`unit` 和可选的 `category` 登记不评分的位置。每张源图的 `(series, category, unit)` 只录一次，同版面上独立小图按可复核的面板分别记录。

```json
{
  "id": "manual-a:p4:chart01",
  "document_id": "manual-a",
  "page": 4,
  "source_id": "p4.chart01",
  "feature": "chart",
  "values": [
    {"series": "开机率", "category": "2025", "value": "97.5", "unit": "%"}
  ]
}
```

## 图片与印章内容

| 类型 | 标什么 |
| --- | --- |
| `text_image` | 截图、说明牌或文字图里的可读字段。按原图的版面和语义分段，保持图片的源块身份。 |
| `flowchart` | 节点文字及端点、方向都明确的连线。`relations` 用 `from` 和 `to` 引用 `fields` 中稳定且唯一的键。分支标签和归属保存供诊断。 |
| `natural_image` | 有字照片逐项标可读文字，例如设备名、状态或铭牌值。确认无字时用空 `fields`。字迹不清时登记复核原因。 |
| `seal` | 可核实的机构、用途、编号或残章片段。每枚章独立保留源块身份。 |

```json
{
  "id": "manual-a:p5:flow01",
  "document_id": "manual-a",
  "page": 5,
  "source_id": "p5.flow01",
  "feature": "image",
  "sub_type": "flowchart",
  "fields": [{"key": "inspect", "text": "检查"}, {"key": "record", "text": "登记"}],
  "relations": [{"from": "inspect", "to": "record"}]
}
```

图内文字、印刷图注和相邻正文分别登记来源。独立面板可以拆标，共用标签的整图按整体设目标。按目标记录 `proposed`、`needs_review` 或 `diagnostic`。诊断图表以空 `values` 入清单，诊断图片以 `sub_type: "other"` 入清单，保留原始类型和判断理由。

附录和页眉页脚也可沿用同一批次。附录按现行 P2T 策略检查 `title`、`doc_title`、`paragraph_title`，从满足 `page_idx >= int(total_pages * 0.5)` 且以「附录」或 `Appendix` 开头的首个标题所在页截到文末，为截断范围内各页标印刷原文锚点。页眉页脚按物理页记录 `blocks`，每块保留 `id`、`type`、`bbox` 和原文，页眉或页脚标志用 `header_image` 或 `footer_image`。需保留的正文、图注和原图另列保护项。

## 复核与发布

- 批处理任务输入含 `task_id`、PDF 与裁图哈希、源块元数据、提示词版本和字段约定。首标与复核使用独立请求，按 `(task_id, model, prompt_version)` 缓存。模型响应返回 `task_id`、状态、范围说明和专项字段，由合并程序从任务清单回填来源。
- 核对结构和来源、图表系列和单位、流程方向以及残章归属。按类型抽查一致项，裁决分歧并保留响应、复核记录与原图定位。
- 合并后冻结 `rubric-evaluation-gt.json`、来源清单及复核记录。使用该批 `gt_version`、实际文档 ID 和 `doc-parse-bench.feature-rubric-gt.v1` 格式，记录 GT 哈希、计分和仅诊断的数量。
- 生成空证据模板并运行一次评分，校验清单字段和实际分母，此时分数为空。正式比较时，各模型共用冻结 GT。[空证据模板](inputs.md#交给评分器的-evidence) · [评分口径](scoring.md#计分清单)

这些步骤定义可交给子代理或视觉 API 的字段与复核约定。批次编排、响应合并和来源核对按所用标注 Agent 的输入输出实现。
