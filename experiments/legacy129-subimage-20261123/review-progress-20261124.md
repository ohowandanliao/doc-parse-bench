# 父子图审阅后如何完成本轮任务

用户已确认工程分析和后续适配以 MinerU 3.3.1／utils 1.0.5 为参考。采集包仍按实际报告版本 3.1.14 记来源；不再把查清服务精确依赖当作本机工作的前置阻塞。

## 本次实际完成

- [审阅 HTML](../../artifacts/legacy129-subimage-20261123/analysis-units-review-20261124/review.html) 覆盖全部 10 个复合父框、27 张子裁图及真实响应。页面复制原 PDF 页渲染、父图原始素材和所有子图输入；文字、Markdown 表格和 Mermaid 原文均可核对，空输出／未采到明确区分。
- 审阅建议：Fig. 1、Fig. 6 与两组共图注线路图，共 4 个父图分析单位；双柱图、设备照片、两幅独立接线图及三组独立照片，共 6 组、14 张子图分析单位。全部子图原生 type hint 都是 `image`，不能仅按 hint=chart 选择图表单开候选。
- [analysis-plan.json](../../artifacts/legacy129-subimage-20261123/analysis-units-review-20261124/analysis-plan.json) 附图片输入、源页与哈希。它是审阅输入计划，不是按 case 名硬编码的线上策略，不自动发起推理。4 份父图结果未采到；14 份已存子图结果可继续回归。
- 页面区分原生抽取、原 ZIP P2T 和原包补偿三层逻辑，包含真实源码摘录与完整源文件。原 ZIP 只有上传、获取 middle JSON／images、过滤、渲染，没有 sub_images 补请求；原包先分析全部 27 张子图，再按 text_only/empty 比例达到 50% 决定保留父图。
- 已核实原生 `extract_with_layout` 是固定区域抽取入口，能返回实际 `type/sub_type/content`。`content_extract` 仅返回字符串；重传裁图到 `/file_parse` 会再布局，不保证覆盖整图分析。Python 能力存在不等于同一 upstream 已有可用 HTTP 入口。
- 额外只复核已有的 129 内校准流程图 `bc_108`，不改变复合框分母：FT 字段 F1 和关系 F1 均 100，分支标签绑定 2/2；Origin 少“申证”且末边反向，内容诊断 72.50，旧 IR 缺 subtype，主分保持 null。结果来自原页和已有 GT，而非 Mermaid 可渲染性；证据位于 HTML 的 `flowchart-bc108/`。
- 继续修复上一轮双关测试中的旧假设：双关应对照原 ZIP 路径，不应与“图片开启且保留印刷图注”的输出等同。既有测试环境无需安装依赖，相关 45 项测试通过。完整双关原 ZIP／129 成品回归仍是后续验收项。

## 全部拆分的可复用对照

“所有子图都分析，但必要时保留父图”与“所有子图都替换父图交付”是不同策略。前者可保留来源组关系，但子图标签仍不能替父图提供 subtype；后者已有全拆回放，不需要新增模型调用即可核对。

| 历史方案 | 图片／印章定位 | 命中／预测 | 匹配且非空 | 图表定位 | 图表校准 F1 |
| --- | ---: | ---: | ---: | ---: | ---: |
| FT 首轮 | 72/118 | 72/79 | 55/118 | 71/73 | 61.64 |
| FT 原包 | 80/118 | 80/88 | 67/118 | 73/73 | 70.51 |
| FT 全拆交付 | 79/118 | 79/94 | 67/118 | 73/73 | 70.51 |
| FT 前置历史候选 | 82/118 | 82/86 | 66/118 | 73/73 | 70.51 |

图表内容 F1 仍仅为 11 张、78 个明示值。图表组是图片／图表双开；没有据此宣布 chart-only、线上时延或正式成品通过。全拆补回 10 个柱图值，独立照片定位也改善；两组线路父图各变成两个半框，IoU 约 0.463–0.469，Fig. 6 最大子框 IoU 0.447，损失分组定位。subtype 错、OCR 无标签、内容错仍然存在，不能以非空覆盖掩盖。

## 后续推进顺序与完成产物

1. **分析／交付语义收敛**：先通过本页看清待补父图与可复用子图；将理由整理为通用规则，不能将本页人工清单写入线上。图表单开的候选范围单独确认。产物为冻结策略说明、四开关行为表和对应证据缺口清单。
2. **复用响应测准内容**：优先复用已保存的子图响应，4 个缺失父图单位导出给用户安排内网推理。若采用原生固定区域入口，与旧 crop-as-page 结果分开记录。产物为逐源图的 subtype／字段／节点／边／数值证据及 FT–Origin 差距，区分模型错、布局／过滤错、GT 待审和证据不足。
3. **先收齐校准分项，再冻结正式评价**：附录 51 页、边缘 14 校准块与图表 78 个明示值已有回归分；图片／印章按现有冻结范围补证据，关系和 subtype 分开。四项正式证据齐全才算 25% 等权总分，确认误删独立判失败。完整 118／73 结构分母不自动变成内容分母，不能把校准 GT 私自改为 evaluation。
4. **本机 P2T 适配与交接**：只接入确认的规则，保留分析默认不能跳过；没有复合块时不加模型推理；双关严格与原 ZIP 一致。独立回归图片单开、图表单开、双开、双关及普通图、附录、页眉页脚，生成相对原 ZIP 的单一补丁，不叠加历史补丁。内网 AI 负责真实请求中的标题重排、最终 Markdown 和 p50／p95，离线时长不当验收。

## 复现

从仓库根目录运行，输出应是一个新目录，避免覆盖历史产物：

```sh
.venv/bin/python experiments/legacy129-subimage-20261123/analysis_units_review.py \
  --output /tmp/legacy129-analysis-units-new
```

默认读取本机已有的 MinerU 3.3.1、utils 1.0.5 解包缓存和历史 Origin IR；可通过 `--mineru`、`--utils`、`--p2t-zip`、`--legacy-origin` 显式指定。生成器没有网络调用，断言 v3 `records.json` SHA 和 10／27 清单，复制原始输入与真实响应。所有结果按 replay/calibration 标记，不修改 GT。

相关 P2T 检查（复用已存在临时环境）：

```sh
cd archives/pdf2text-develop-1.6.0-8b747ca-20261123
PYTHONPATH=src /private/tmp/feature-subimage-129.WFF6Bk/p2t-venv/bin/python -m pytest \
  -q -o addopts='' \
  tests/unit/core/parse/test_mineru_subimages.py \
  tests/unit/core/parse/test_mineru_title_rules.py \
  tests/unit/core/parse/test_mineru_client_errors.py
```

结果：45 passed，另有原有 Pydantic 配置弃用提示。没有安装依赖、调用新模型或更改内网。
