# 评测输入与推理配置

各模型使用相同的 PDF 和冻结清单，以实际 P2T 成品评分。[评分口径](scoring.md)

## 推理路由

- 2604 系列沿用原推理路径。
- 2605 系列使用此前内网 P2T `68624-subimage-expand` 的 `sub_images` 改造。开启图片或图表分析时，根据复合图的实际结构选择整图或子图分析，沿用现有 MinerU 接口补请求。策略由 P2T 内部 `mineru_subimages.py` 执行。

同一 GT 和评分规则适用于两条推理路由。记录 checkpoint、P2T 代码指纹和实际补偿策略。评估切分策略带来的变化时，在同一个 2605 checkpoint 和相同开关配置下比较两次成品。

## 采集材料

按模型分别保存下列评测证据，保留实际产出与对应的源块。

| 材料 | 必须保留的内容 | 用途 |
| --- | --- | --- |
| 输入清单 | 稳定 document ID、PDF 文件名、PDF SHA-256、物理页数、页码映射；PDF 本身或可访问的固定版本 | 证明两版使用相同输入，避免物理页与印刷页码混淆 |
| 版本与配置 | 模型标识／checkpoint、MinerU 与 utils 实际版本、P2T commit／patch hash、上游 backend、实际请求参数、开关、标题配置 | 不将不同版本的采集、回放和最终成品混为一谈 |
| 原始服务响应 | 完整 HTTP 响应及其 SHA-256，保留原样 `middle_json`，不得先裁掉字段 | 查实际 `type/sub_type`、页号、bbox、父子关系、body 内容、图表及过滤责任 |
| 图片资产 | 响应 images、父图与实际分析子图，或可访问文件；资产哈希与响应关联 | 核对无字照片的交付、原图保留、裁图范围及来源 |
| 最终 P2T 成品 | 同次请求交付的 Markdown、pages 和全部可访问图片；请求 ID 与上游响应关联 | 内容主分评最终交付，原始响应不能代替被过滤或未渲染的成品 |
| 内部追踪快照 | 分析前、补偿后、过滤／渲染阶段的源块映射，或足够复现的中间快照 | 区分模型回包问题、拆保／回填问题和渲染／过滤丢失 |
| 实际执行日志 | 请求 ID、父／子分析单位、route、各补偿请求和响应哈希、状态、耗时、最终使用／弃用情况 | 区分 success、empty、not_called、timeout、request_error、unresolved |
| GT 与内容范围 | 本次冻结 GT 文件、SHA-256、split、纳入／诊断范围及保护项 | 保持分母稳定，避免按预测结果挑选可评分样本 |

这里的“原始响应”指 MinerU 服务可保存的结构化回包，不要求取得模型内部回答或思考过程。P2T 对外仍可只返回 Markdown 和 pages；`middle_json` 与追踪信息由内部采集旁路另存，不需要因此改变正常公开接口。

正式目标配置为 `mineru_provider=mineru3`、`relevel_titles=true`、`title_rules=false`。另存 `relevel_applied` 的真实值；只设置目标参数而未实际执行标题重排的回放，不能写成已完成的 final 成品。

## 开关组合与配对

视觉分析至少独立保存四组：

| 组名 | image_analysis | chart_analysis | 需核对的行为 |
| --- | --- | --- | --- |
| `both_off` | false | false | 原路径、零新增裁图／补请求，原图与图注按原版交付 |
| `image_only` | true | false | 图片分析交付，图表内容按关闭行为处理 |
| `chart_only` | false | true | 独立验证图表候选、表格交付与普通图片内容过滤 |
| `both_on` | true | true | 同一分析单位不因两个开关重复请求，按实际类型交付 |

附录与页眉页脚分别提供只切换该功能的开启／关闭结果，其余配置固定，并保留应留正文、独立参考文献、签署提示、原图及印刷图注等保护项。

原评分契约的配对名称为：附录 `appendix/off`，边缘 `header_footer/off`，图片 `image/controls/image_off`，图表 `chart/image`。历史 `chart` 表示图片／图表双开，不等于独立 `chart_only`。

成对过滤证据要求复用同一份保存的上游快照，并记录共同 capture ID／hash。真实四组请求也应独立保留；若实际产生不同上游响应，不能把它们的 capture hash 伪填成相同。由快照派生的过滤对照与真实服务双关兼容检查分别报告。

## 图片、印章与图表特别要保留什么

| 类别 | 评分所需内容 |
| --- | --- |
| 普通图片 | 实际 subtype 是否存在、标签所在源块及其 ID，最终交付的图内文字／内容和源图对应关系 |
| 无字照片 | 实际 `natural_image` 标签、原图是否可访问、是否编造文字；不要求靠生成描述证明非空 |
| 有字照片／文字图 | 可读字段的实际文字及其来源，不能拿周边正文替图内文字得分 |
| 流程／线路图 | 节点文字、连线端点、方向、分支标签与绑定、所属图／面板。仅在 GT 已冻结的范围计分，未冻结关系另报诊断 |
| 印章 | 机构名、用途、编号或可辨残章文字的实际输出，字符顺序、来源框、合框后各枚章的归属；只评 GT 预定的可辨范围 |
| 图表 | 最终表格原文及可追溯的数据项；保留实际系列、类别、值、单位，不按 GT 修正错表头／错列 |
| 复合父／子图 | 分析单位与交付单位分别记录；父图、子图 bbox、相对坐标定义、裁图哈希、实际响应及回填来源 |

保留父图不能自动记作分析成功；子图标签不能复制给父图。某一输出字段、连线、数值或标签 ID 不能重复归属给两张源图。父图新分析仍为多碎块或空结果时，记录实际状态，不把 layout 当成完整分析响应。

## 交给评分器的 evidence

由评测适配层按源页和源块审核归属，生成每模型一份 `doc-parse-bench.feature-rubric-evidence.v1` JSON。`cases` 对象以冻结 GT 的 case `id` 为键，提交实际片段和审核范围内的错报。`captures[document_id][group]` 保存实际采集 ID 或哈希，用于检查同源的开关对照。

| 范围 | evidence 字段 |
| --- | --- |
| 全局 | `schema_version`、`model`、`gt_sha256`、`config`、`stage`、实际 `relevel_applied`、`captures`、`cases` |
| 附录 | `on_anchors`、`off_residual` |
| 页眉页脚 | `on_blocks` 的实际片段／图像可访问性、`off_residual_ids` |
| 图片／印章 | `fields` 的实际文本、字段 key 和独立输出 ID；图片另有实际 `sub_type/subtype_id`；无字照片另有 `image_available` |
| 已冻结关系的流程图 | `relations` 的独立输出 ID、`from/to`；分支绑定原始证据另保留，当前实现不会自行扩展 GT 的关系范围 |
| 图表 | `table_status` 及已解析 `values`。每项保留独立 `id`、实际 `column_id`、`series`、`category`、字符串 `value`、`unit` |
| 保护项 | 同次开关对照的 `on_state/off_state`：complete、partial 或 missing |

完整成品确认没有字段写 `fields: []`；确认缺图片标签写 `sub_type: null`；字段没有采到则省略。上述两种缺失不能互换。超时或未调用先保留工程状态，不自动解释成模型识别失败；确认最终交付缺失时可以按交付口径判失败，模型归因另报。

`column_id` 用实际表格标识与列号生成，一个数据列里的所有单元格共用该 ID。两个同名表头也各有列号。`series`、`unit` 记录各列实际声明的内容。旧证据可通过已记录的表格坐标或唯一的表头与单位识别数据列。

一批评测的目录示例。

```text
next-evaluation/
  manifest.json
  gt/                              # 本次固定 GT 与哈希
  ft/
    requests/ raw/ assets/ final/ trace/
    evidence.json
  origin/
    requests/ raw/ assets/ final/ trace/
    evidence.json
```

为每个模型生成空模板。模板包含 case ID、配置和 GT 哈希，待补的预测字段为空。

```sh
.venv/bin/python -m doc_parse_bench.feature_evaluation.feature_score_cli template \
  --gt /path/to/batch/rubric-evaluation-gt.json \
  --model model-under-test --stage final \
  --output /path/to/model/evidence-blank.json
```

填入复核后的证据，再使用[评分命令](scoring.md#可复现入口与输出)。
