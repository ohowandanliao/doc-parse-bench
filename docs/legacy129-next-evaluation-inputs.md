# Legacy 129：下次评测材料要求

本轮按用户要求收口：停止补取历史响应、补推父图／子图、补 GT 和继续补齐图片／印章分数。保留现有校准结果与缺项；图片／印章专项及四项总分仍为 `null`。本文是下次独立评测的数据交付契约，不是本轮的补采任务。

## 已提交的实现

评分实现版本为 `legacy129-content-v1`，相关提交：`d6251ad`（评分及交接代码）、`79d8eed`（固定 v3 GT 和回放前置材料）、`c2b7a51`（复现结果及 session 边界）。

| 文件／入口 | 用途 |
| --- | --- |
| `src/doc_parse_bench/feature_rubric.py` | 附录、页眉页脚、图片／印章、图表的内容主分、分层汇总及误删门槛 |
| `src/doc_parse_bench/feature_contract.py` | 专项名称、GT 版本、历史过滤配对名称 |
| `src/doc_parse_bench/feature_score_cli.py` | 仅用 Python 标准库的 `score` 和空证据 `template` 命令 |
| `docbench evaluate-feature-rubric` | 同一内容评分实现的仓库入口 |
| `feature_eval.py` / `feature_matrix.py` | 原有结构、定位、非空及开关诊断；不替代内容分 |
| `mineru_middle.py` | 129 专项 IR 中保留实际 subtype 及子图来源 metadata |

四项公式、精确匹配与空值语义见 [评分交付口径](legacy129-scoring-contract.md)，完整证据字段见 [评分实现说明](feature-evaluation-129-rubric.md)。下次沿用同一公式；更改 GT、内容范围或归一化规则时必须单独标版本并对两版统一重评。

## 下次必须交付的原始材料

以下内容按 FT、Origin 分别保存，不能用 Origin 补 FT 的答案，也不新增 2605 base 任务。

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

原始材料齐全后，由评测适配层按源页／源块审核归属，生成每版一个 evidence JSON。它不是任意 Markdown 的自动打分入口，不能只提交最终分数或 TP/FP/FN。

| 范围 | evidence 字段 |
| --- | --- |
| 全局 | `schema_version`、`model`、`gt_sha256`、`config`、`stage`、实际 `relevel_applied`、`captures`、`cases` |
| 附录 | `on_anchors`、`off_residual` |
| 页眉页脚 | `on_blocks` 的实际片段／图像可访问性、`off_residual_ids` |
| 图片／印章 | `fields` 的实际文本、字段 key 和独立输出 ID；图片另有实际 `sub_type/subtype_id`；无字照片另有 `image_available` |
| 已冻结关系的流程图 | `relations` 的独立输出 ID、`from/to`；分支绑定原始证据另保留，当前实现不会自行扩展 GT 的关系范围 |
| 图表 | `table_status` 及已解析 `values`：每项独立 ID、series、category、字符串 value、unit |
| 保护项 | 同次开关对照的 `on_state/off_state`：complete、partial 或 missing |

完整成品确认没有字段写 `fields: []`；确认缺图片标签写 `sub_type: null`；字段没有采到则省略。上述两种缺失不能互换。超时或未调用先保留工程状态，不自动解释成模型识别失败；确认最终交付缺失时可以按交付口径判失败，模型归因另报。

建议目录：

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

先生成空模板（这里是下次操作说明，本轮不执行）：

```sh
.venv/bin/python -m doc_parse_bench.feature_score_cli template \
  --gt /path/to/frozen-gt.json --model 3.1-ft --stage final \
  --output /path/to/ft/evidence-blank.json
```

填入经来源核对的证据后评分：

```sh
.venv/bin/python -m doc_parse_bench.feature_score_cli score \
  --gt /path/to/frozen-gt.json --pred /path/to/ft/evidence.json \
  --output /path/to/new-empty-score-directory
```

输出 metrics、逐例分数、缺证据清单、可读 report 和 provenance。输出目录使用新目录；不覆盖历史评分。打分入口不发起模型推理。

## 下次什么条件下才能出总分

当前结构 GT 为 129 篇／372 页、118 个图片与印章、73 个 chart；内容 pilot 为 17 个图片／印章主分目标及 11 图／78 明示值等校准范围。采集 129 篇不等于已有 129 全量内容 GT。

下次若沿用 `split=calibration`，仍只发布该范围内的分项及诊断。正式总分需要预先审核并冻结声明范围的 `evaluation` GT、两版对应的真实 `final` 成品和四项完整证据；不可只改 split 名称或用缺项的平均值凑总分。确认误删仍独立否决。没有新增上线质量阈值。

## 与 AgentBuilder 的关系

本次四功能评分是独立入口。AgentBuilder-v2 仍为 `30% 文本 + 30% 表格 + 30% 阅读顺序 + 10% TitleTree-v2`，不使用本专项的四项 25% 权重。

AgentBuilder 的计分、标题、预测适配、GT 导出及原生后端代码与本轮评分改动前一致；已有 AgentBuilder 数据、GT 和报告不改写。本次发布的 feature-v3 是四功能专用快照，不切换 AgentBuilder 的活动 GT。共享 CLI 的变更限于 feature 子命令；`mineru_middle` 的新增字段保留用于专项回放，AgentBuilder 的现有预测导入与历史重评分路径不经过该模块。

2026-11-24 影响核查：相关 59 项测试通过，保存的 15 个配置之历史 AgentBuilder 和 AgentBuilder-v2 聚合分逐项复算一致；核心源码也与保存报告的哈希匹配。结果目录 64 个文件在本次核验前后哈希不变。未重新跑完整原生后端；记录在仓库的 `experiments/legacy129-subimage-20261123/agentbuilder-impact-check-20261124.json`，离线评分包中位于 `docs/agentbuilder-impact-check-20261124.json`。
