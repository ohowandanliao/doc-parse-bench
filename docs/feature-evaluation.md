# 129 四功能专项评测

这是一条独立的评测入口，专门检查 PDF2Text 的 `keep_appendix`、`keep_header_footer`、`image_analysis` 和 `chart_analysis`。它不读取、不修改 TreeTitle-v2、AgentBuilder-v2、OmniDocBench 或 MPDocBench 的分数。

这条专项只使用 129 份旧 PDF；当前 81 份 `annotated-20261111` GT 不参与。

## 三个 129 GT 版本

| 版本 | 路径 | 数量 | 本专项中的角色 |
| --- | --- | ---: | --- |
| `legacy-129-markdown-v1` | `data/legacy/groundtruth/` | 129 个 Markdown | 旧内容来源；图表转录只作为候选证据 |
| `legacy-129-annotated-v2` | `legacy_129_pack_20261118.tar.gz` | 129 份、372 页 | 机器标注＋人工页面修订后的结构主 GT；标题更准确，可显式用于 129 的 AgentBuilder/TreeTitle-v2 |
| `legacy-129-feature-v3` | `artifacts/legacy-features-20261118/` | 129 条记录 | v1＋v2 的四功能专项派生 GT，只用于四个 PDF2Text 开关 |

旧目录另有 `data/legacy/unpaired_groundtruth/Handwriting document.md`，没有对应 PDF，不进入 129 对评测。v3 是由 v1 和 v2 生成的评测视图，不是第三次独立人工标注，也不替代 v2 的 AgentBuilder/TreeTitle-v2 GT。

生成专项 GT：

```bash
.venv/bin/docbench build-feature-gt \
  legacy_129_pack_20261118.tar.gz \
  data/legacy/groundtruth \
  artifacts/legacy-features-20261118 \
  --old-pdf-dir data/legacy/dataset/pdf/source
```

`manifest.json` 保存来源哈希、页数对账和覆盖状态；`comparison.md` 是对账说明；`records.json` 是逐文档输入。v3 默认是轻量包，不重复保存 v2 的完整结构 JSON；新结构化包共有 314 页人工 patch、58 页机器链路终态，完整结构仍在 v2 原包中。需要本地展开副本时，在生成命令后加 `--include-structured`。当前导入审计保留 1 条已知无效关系记录，不影响四功能块统计。

## GT 质量边界

当前 129 专项统计：新结构化 GT 有 593 个 title、801 个边缘块（header/footer 528、页码 273）、135 个 image/seal（image 102、seal 33）、56 个 chart；旧 Markdown 有 580 个 heading、104 个图片引用、57 个图片占位符、304 个混合表格，12 个文档含图表内容候选。

- `keep_appendix`：按最新 PDF2Text 代码的 `_find_appendix_page` 规则计算：标题开头是 `附录`/`Appendix`，且 0-based `page_idx` 位于文档后半段；`附件` 不算。当前新版 GT 命中 4 个文档、48 个附录页；旧 Markdown 只作交叉核对。
- `keep_header_footer`：新版 GT 提供 header/footer、page number 类型。评分是保留/文本代理；旧 Markdown 没有可靠类型，不能宣称严格页眉页脚内容准确率。
- `image_analysis`：按你的口径，image 与 seal 一起进入主分母，并拆出两类诊断。旧 Markdown 证明部分视觉块存在，但没有逐图图内文字准确率 GT，所以只评保留/输出代理。
- `chart_analysis`：新版 GT 提供 56 个 chart 位置；旧 Markdown 的 12 个候选文档确实包含图表相关转录和表格，但普通表格与 chart 没有稳定一对一关系。可以报告候选范围内的内容输出代理，不能把它叫严格图表数值准确率。

没有对应 GT 内容的指标必须是 `unavailable`，不能把缺 GT 当成模型得分 0。`manifest.json` 的 `summary.coverage` 和评分输出的 `feature_coverage` 记录这个边界。

## 最新 PDF2Text 的调用

最新代码的对外入口是：

```text
POST http://<p2t-host>:<port>/v1/pdfparse
```

`pdf2text` 内部再调用已配置的 MinerU `/file_parse`。客户端不要直接调用 MinerU。请求可以用 multipart 字段，也可以用 `parseConfig` JSON；最新代码允许 `mineru_provider` 为 `mineru3` 或 `mineru4`。

本次代码依据的源码快照与原 ZIP 已整理在本机 `archives/pdf2text-feature-20261119/`；ZIP SHA-256 为 `cfd0415069c6b9365e71aa2288452764446841ec47a59181409eb7488a9be450`。该目录是参考材料，不会被评测器作为依赖导入。

本轮标题规则实验和四功能实验都固定：

```json
{
  "mineru_provider": "mineru3",
  "relevel_titles": true
}
```

`3.1-ft` 与 `3.1-origin` 是两个不同的 MinerU3 上游服务。若比较它们，应分别完整跑一批，不要在同一批结果中混用。当前 P2T 服务如果切换上游需要按内网部署方式重启；provider、上游地址和模型版本都写入本次运行清单。

## 四功能运行组

四功能先固定 `title_rules=false`，以便每个差异只归因于目标开关。每组使用完全相同的 129 个 PDF、相同的 MinerU3 上游和相同的 `relevel_titles=true`：

| 组 | `keep_appendix` | `keep_header_footer` | `image_analysis` | `seal_rec` | `chart_analysis` |
| --- | ---: | ---: | ---: | ---: | ---: |
| `off` | false | false | false | false | false |
| `appendix` | true | false | false | false | false |
| `header_footer` | false | true | false | false | false |
| `image` | false | false | true | true | false |
| `chart` | false | false | true | true | true |

`seal_rec` 在 image/chart 组中和 `image_analysis` 一起固定打开，只是为了按本项目口径把 seal 纳入 image 分支；它不是第五个独立分数。`chart_analysis=true` 组同时保留 image 分支，因为最新代码对 chart 上游请求会开启 image analysis。

每个 PDF 保存 `/v1/pdfparse` 的完整 JSON 响应，文件名用旧 PDF stem，例如 `1-3单元格内换行1.json`。至少保留 `pages`、`markdown`、`error`；不要只保存 Markdown。最新服务默认返回这三个字段，没有逐块预测 JSON。

请求示例：

```bash
curl -X POST "http://<p2t-host>:<port>/v1/pdfparse" \
  -H "Authorization: Bearer <token>" \
  -F "file=@/data/legacy/source/<source_name>.pdf" \
  -F 'parseConfig={"mineru_provider":"mineru3","relevel_titles":true,"title_rules":false,"keep_appendix":true,"keep_header_footer":false,"image_analysis":false,"seal_rec":false,"chart_analysis":false}' \
  > predictions/appendix/<source_name>.json
```

本地评分：

```bash
.venv/bin/docbench evaluate-features \
  --gt artifacts/legacy-features-20261118 \
  --pred predictions/appendix \
  --output artifacts/feature-scores/appendix
```

对 `off`、`appendix`、`header_footer`、`image`、`chart` 各运行一次，再看每组 `report.md`、`metrics.json` 和 `per_document.json`。四功能专项不需要模型额外生成答案文件；模型只需返回 PDF2Text 的最终 JSON。

不必每次跑满 129 份。可以在本地临时写一个子集清单 JSON，把 `union` 用作所有开关关闭的 base 子集，再为 `appendix`、`header_footer`、`image`、`chart` 分别列出自己的文档 ID：

```json
{
  "schema_version": "doc-parse-bench.feature-subset.v1",
  "gt_version": "legacy-129-feature-v3",
  "subsets": {
    "union": ["bc_003", "bc_010"],
    "appendix": ["bc_003", "bc_010"],
    "header_footer": ["bc_003"],
    "image": ["bc_018"],
    "chart": ["bc_014"]
  }
}
```

用 `union` 跑一次 all-off base，再用各功能名跑对应开启组：

```bash
.venv/bin/docbench evaluate-features \
  --gt artifacts/legacy-features-20261118 \
  --pred predictions/base \
  --subset-manifest /tmp/feature-subset.json \
  --subset-name union \
  --output /tmp/feature-scores/base

.venv/bin/docbench evaluate-features \
  --gt artifacts/legacy-features-20261118 \
  --pred predictions/appendix \
  --subset-manifest /tmp/feature-subset.json \
  --subset-name appendix \
  --output /tmp/feature-scores/appendix
```

子集清单和预测结果属于一次性实验材料，不需要提交到仓库。评分器会把子集名称、清单哈希和实际分母写入 `provenance.json`；不要用 `--allow-missing` 代替子集选择，因为那会把未运行的文档当成空预测。

由于 `/v1/pdfparse` 只返回最终 Markdown，header/footer、image 和 chart 的部分指标是内容/页数代理；严格逐块 chart 定位需要另存结构化 blocks，当前不把 Markdown 代理升级成严格内容准确率。

## 标题规则实验（单独一条）

标题规则不和四功能组混跑。对同一批 129 PDF、同一 MinerU3 上游、`relevel_titles=true`，只切：

```text
title_rules=false
title_rules=true
```

两组分别进入原有 TreeTitle-v2/AgentBuilder-v2 评测输入，输出目录和 provenance 分开。该对照可以回答 B1-B14 规则对标题树的影响，但不会改变四功能专项的分数，也不会覆盖旧的历史分数。
