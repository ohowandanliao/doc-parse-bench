# 评测口径

## 旧版 129 篇中实际有哪些模型

旧包保存了 13 条链路的预测：MinerU 开源 3.1.14／3.4.4、MinerU＋full、三条 POPO truefix 链路，以及七条 P2T／标题规则／renderer 变体。这些主要属于同一个 MinerU 技术家族，不是 13 种独立 OCR 模型。

xlsx 还列了五条共享链路：`mineru_vlm`、`fastgpt_sf`、`sf-1.4.0`、`mineru_vlm_gemini`、`unlimited_ocr`。它们的原始预测不在交付包中，当前只能保留表中历史分数，不能重跑验证。其中 `unlimited_ocr` 也不能当作这次的 Unlimited OCR 2。仅凭这些链路标签，不能进一步确定其全部内部模型和版本。

这次新包包含 OvisOCR2、NaviDC-OCR、MinerU 2.5 Pro、Unlimited OCR 2 在新 81 份文档上的输出；没有它们在旧 129 篇上的对应预测。因此文档中的“其他模型”应明确理解为未来接入同一任务的解析器，不能理解成已经对这些模型跑过旧版 129 篇。

## 旧 GT 的质量与模型偏向

旧 GT 确实带有图表任务偏向。具体例子：`4-1统计图1.md` 在“图 1 2019–2023 年地区生产总值及其增长速度”前，将统计图写成 `年份 / 地区生产总值 / GDP增速` 数据表；图 2、图 3 等也转成数据表。普通表格与图表转录表格进入同一组表格指标，不能区分能力来源。

因此，对于默认只输出图像区域的 OvisOCR2 或其他解析器，原图即使定位正确，仍不能满足旧 GT 的数据表要求；MinerU 开启 chart_analysis 则更贴近这套任务。用旧版混合表格分数直接代表“通用文档解析能力”，会对其他输出约定不友好。换成新评分器并不会消除这层 GT 偏向。

这说明任务定义需要拆分，不能据此断言全部 129 篇文字、公式或表格内容质量差。当前确认的是图表表示方式和任务范围的偏差，尚未对全部内容逐项重新人工验真。旧 Markdown 又缺少区分原表格与图表转录表格的块级来源，不能靠删除所有表格自动变成中立 GT。

建议保留旧集作为历史 chart-table 兼容集；通用比较使用新标注中明确区分 table／chart 的 native 任务。需要继续利用旧 129 篇做通用比较时，应重新建立 table／chart 区分，核对数字、表头和图表数据来源，单独发布新版 GT，保留原版。

## 旧逻辑如何与新版融合

融合统一的数据入口、预测适配、title 扩展、报告和运行管理。standard 模式使用固定版本的官方 OmniDocBench／MPDocBench；legacy 模式使用本工程吸收的历史 md2md 匹配和清洗逻辑，以便复现历史 xlsx。这样可以在同一项目操作，但分数仍带有明确的评测器版本和任务口径。原服务、标注 agent、一次性脚本不作为运行依赖保留。

不应把旧代码直接覆盖到官方子模块。旧版还有具体的计分差异：整个文档的预测表格为空或格式不匹配时，`Md2MdDataset` 只打印提示，不创建缺失表格样本；新版结构化 GT 路径会为漏掉的 GT 表格构造匹配并扣分。旧总分在 title 加入前聚合的问题也单独兼容。将这些行为“合并成一个算法”会破坏历史可比性，也会把旧缺陷带入新评测。

## 三条图表路径

| 口径 | GT | 预测 | 用途 |
| --- | --- | --- | --- |
| native | chart 作为 figure，真正 table 才参与表格指标 | 所有模型的视觉块统一渲染为图片引用 | 新标注的默认公平比较 |
| chart-table | chart 需要人工确认的数据表 | 使用模型已识别的数据表，缺少的仍是视觉块 | 保留图表数据提取任务 |
| 统一图表增强 | GT 数据表必须审核，预测走同一个外部 provider | 每个模型用相同 provider 对自己的视觉区域识别图表 | 单列为模型＋增强链路，不与原始模型混排 |

旧版 Markdown GT 已经把统计图变成了表格，因此 `--backend legacy` 保持这一口径。打开 MinerU `chart_analysis` 是推理参数，不能靠后处理给其他模型虚构等价输出；模型本来已输出 Markdown／HTML 图表数据时才可无损转换。

当前新 GT 的 197 个 chart 块全部没有 text/html 数据表，所以不能直接导出 chart-table GT。已有模式应使用旧 GT；新数据要先补充人工确认的图表数据表。

人工 sidecar 的键为 `document/block_id`：

```json
{
  "example/candidate.block.p1.0005": {
    "is_chart": true,
    "reviewed": true,
    "html": "<table><tr><th>类别</th><th>值</th></tr><tr><td>A</td><td>42</td></tr></table>",
    "reviewer": "name"
  }
}
```

```bash
docbench augment-charts artifacts/prepared/baseline/gt_ir/documents \
  artifacts/chart_gt_ir --tables reviewed_chart_tables.json
docbench export-gt artifacts/chart_gt_ir/documents artifacts/chart_gt \
  --chart-policy chart-table
```

预测增强可以用同样的 sidecar，或提供 JSON stdin/stdout 的外部程序：

```bash
docbench augment-charts artifacts/prepared/baseline/pred_ir/OvisOCR2/documents \
  artifacts/chart_pred_ir/OvisOCR2 --pdf-dir data/annotations/sources \
  --provider python /absolute/path/chart_provider.py
```

程序接收 `document, block_id, page, bbox, image_png_base64`，返回 `is_chart, html`。裁剪仅使用预测 bbox。provider 命令不经过 shell；本项目没有默认外部 API，也不会自动启动模型服务。没有 bbox 的视觉块记录为 `no_bbox`。GT 禁止直接调用 provider 生成真值，必须先审核 sidecar。

## 指标与聚合

| 输出 | 含义 |
| --- | --- |
| `text_edit` / `text_accuracy` | 上游页面／文档平均编辑距离及 1−距离 |
| `table_edit` / `table_accuracy` | 表格编辑距离及准确度 |
| `table_teds` / `table_teds_s` | 内容＋结构／仅结构的表格树相似度 |
| `reading_order_edit` / `reading_order_accuracy` | 阅读顺序编辑距离及准确度 |
| `formula_edit` / `formula_accuracy` | 公式字符串编辑距离及准确度 |
| `formula_cdm` | 启用 CDM 后的公式渲染 F1；不以编辑距离替代 |
| `title` | 历史 title 指标，所有后端均保留 |
| `head_teds` | MPDocBench 官方标题树指标，与 title 独立 |
| `merged_text_*` / `merged_table_*` | MPDocBench 跨页合并后的内容指标 |
| `figure_f1` | MPDocBench `--figure`，需要预测位置和页码 |
| `text_relation_*` / `table_relation_*` | MPDocBench `--relations`，关系 F1 及同／跨页分项 |
| `agentbuilder_overall` | 0.3 文本＋0.3 TEDS＋0.3 顺序＋0.1 title，可用项权重归一化 |
| `omnidocbench_overall` | 官方 v1.5+ 的 `(文本准确度 + TEDS + FormulaCDM)/3`，0–1 标度 |

阅读顺序、title 不并入官方 Overall；AgentBuilder 总分单独命名。CDM 缺失时 `omnidocbench_overall=null`，不能把上游旧版 `total_score`（它用公式编辑距离）当作官方分数。换百分制展示时统一乘 100。

旧流水线有一个顺序问题：总体 `overall` 在算入 title 前已聚合，实际只使用文本／TEDS／顺序，逐文档 overall 则包含 title。legacy 后端保留原聚合值到 `overall` 和 `legacy_stage_overall`；明确包含 title 的新值用 `agentbuilder_overall`。第 13 行基线分别为 0.9442 与 0.9211，不将二者混为同一指标。

历史 title 完整保留：文本去 Unicode 空白／标点／符号；标题内容相似度降序贪心配对；GT 层级整体平移、预测层级额外压缩空档；层级／内容权重 0.3／0.7；分母 `max(GT 数, 预测数)`；两边都无标题返回 None，不参与均值。OmniDocBench 的 title 按页面平均，MPDocBench 和旧版按文档平均；比较时保留聚合单位，不能混用。

## 版本、产物和缺失

`metrics.json` 保存总体分数，`per_doc_scores.json` 保存逐样本分数（OmniDocBench 为页），`runtime/result/` 保留上游原始结果，`evaluation.log` 保留日志，`provenance.json` 保存版本、覆盖率、哈希及图表／上下文策略。批量命令额外生成 `summary.csv`、`summary.json`、`summary.md`。

默认拒绝缺失预测；明确 `--allow-missing` 才计为空预测。多余预测不计分并记入 provenance。截断文档记录 `incomplete_documents`，不隐藏在“81/81 个文件”的文档覆盖率中。

GT 与预测的导出 manifest 都有 chart_policy 时，不允许混用。原始模型与上下文后处理／图表增强应使用不同目录和实验标签。四模型公平比较使用同一 GT、同一评测器提交、同一指标配置和同一缺失处理方式。

## FormulaCDM

本机未安装完整公式渲染系统依赖，模式默认只计算公式编辑距离。`--cdm` 会先检查对应后端的 `pdflatex`（新 OmniDocBench）或 `xelatex`（MPDocBench／legacy）；其余依赖按官方文档安装。历史公式评分记录保存在本地 `data/legacy/formula_cdm/`；兼容实现已收入 `compatibility/engine/`，不再依赖原代码包。

## 固定模式与开关

只有 standard 与 legacy 两种模式，完整默认值在 `profiles.py` 中确定；入口为 `docbench run configs/standard.yaml` 或 `docbench run configs/legacy.yaml`。图片替换、details 展开、保守跨页推断、缺失处理和 CDM 仍可独立覆盖，最终选项写入 `run.json`。这些覆盖属于同一模式下的显式实验参数，不扩展为一组需要用户自行拼装的评测模式。

standard 的视觉块由统一结构渲染，不默认再执行历史 base64 替换；legacy 默认执行两步 fix 清洗。两者均可显式覆盖，避免把历史文本替换规则自动施加到新的结构化评测。

standard 对大表格默认启用精确 TEDS 加速：HTML 解析、节点构造、插入／删除及文本替换代价仍使用上游定义，距离由编译的 Zhang–Shasha 动态规划精确求解，不做裁剪或近似。小表继续使用上游 APTED；`--no-exact-teds` 可全部恢复 APTED。求解器记录在 provenance，且已对 1590 项真实表格分数逐项验证一致（容差 1e-10）。legacy 默认不启用该加速。

历史 FormulaCDM 只有在当前与基线公式匹配对 `(img_id, gt, pred)` 完全一致、并且同一渲染环境／配置下才可以继承。随包提供的历史分数没有全部原始匹配对，不能只按模型名称或 xlsx 行号自动继承。原表分数原样保留在 `data/legacy/results/`。
