# Legacy 129 结构回放

本文记录 129 历史结构投影和开关回放入口，输出定位、非空和清除率诊断。正式内容分见[统一评分口径](scoring.md)。

当前 129 份 `3.1-ft` 与 `3.1-origin` 结果、指标解释、image/chart 合并诊断和
image 覆盖率案例见 [11 月 20 日报告](legacy129-20261120.md)。

这条专项只使用 129 份旧 PDF；当前 81 份 `annotated-20261111` GT 不参与。

## 三个 129 GT 版本

| 版本 | 路径 | 数量 | 本专项中的角色 |
| --- | --- | ---: | --- |
| `legacy-129-markdown-v1` | `data/legacy/groundtruth/` | 129 个 Markdown | 旧内容来源；图表转录只作为候选证据 |
| `legacy-129-annotated-v2` | `legacy_129_pack_20261119.tar.gz` | 129 份、372 页 | 当前机器标注＋人工页面修订后的结构主 GT；相对 11-18 版修订 6 篇、12 页的 image/chart 类型，可显式用于 129 的 AgentBuilder/TreeTitle-v2 |
| `legacy-129-feature-v3` | `artifacts/legacy-features-20261119/` | 129 条记录；2026-11-23 人工复核后修订 2 个 image/chart 类型，修订记录见 `manifest.json.manual_review` | 当前 v1＋新 v2 的四功能专项派生 GT，只用于四个 PDF2Text 开关；11-18 版目录是历史基线 |

旧目录另有 `data/legacy/unpaired_groundtruth/Handwriting document.md`，没有对应 PDF，不进入 129 对评测。v3 是由 v1 和 v2 生成的评测视图，不是第三次独立人工标注，也不替代 v2 的 AgentBuilder/TreeTitle-v2 GT。

生成专项 GT：

```bash
.venv/bin/docbench build-feature-gt \
  legacy_129_pack_20261119.tar.gz \
  data/legacy/groundtruth \
  /tmp/legacy-features-rebuild \
  --old-pdf-dir data/legacy/dataset/pdf/source \
  --appendix-overrides configs/legacy-129-appendix-overrides.json \
  --block-overrides configs/legacy-129-block-overrides.json
```

`manifest.json` 保存来源哈希、页数对账和覆盖状态；`comparison.md` 是对账说明；`records.json` 是逐文档输入。v3 默认是轻量包，不重复保存 v2 的完整结构 JSON；新结构化包共有 314 页人工 patch、58 页机器链路终态，完整结构仍在 v2 原包中。需要本地展开副本时，在生成命令后加 `--include-structured`。当前导入审计保留 1 条已知无效关系记录，不影响四功能块统计。

## GT 质量边界

当前 129 专项统计：v3 有 593 个 title、800 个边缘块（页眉页脚 527，含 1 个页眉图片；页码 273）、118 个 image/seal（image 85、seal 33）、73 个 chart；旧 Markdown 有 580 个 heading、104 个图片引用、57 个图片占位符、304 个混合表格，12 个文档含图表内容候选。

- `keep_appendix`：已复核的 4 篇用 `--appendix-overrides` 中的物理页段（从 1 开始，含首尾），展开写入 `new_gt.appendix.pages`。从真实附录标题起默认算到文末，明确例外单列：`bc_003` 第 15–34 页，第 35 页参考文献保留；`bc_010` 第 13–25 页，参考文献随附录；`bc_016` 第 26–31 页；`bc_017` 第 26–37 页，第 38 页发布单位简介保留。未复核的记录仍用原 PDF2Text 截断规则作代理；当前 v3 共 4 篇、51 个附录页。
- `keep_header_footer`：文字与页码按同页、同类型和文本匹配。矩阵评测对页眉页脚图片单列开启召回和关闭残留，按同页、框交并比至少 0.5 匹配；仅有覆盖标志的文字框不算交付图片，开关两组都缺图也不算清除成功。
- `image_analysis`：按你的口径，image 与 seal 一起进入主分母，并拆出两类诊断。匹配块有非空 `generated_spans` 就算“转出了内容”；严格 OCR 字符准确率另行标记为未评。
- `chart_analysis`：新版 GT 提供 73 个 chart 位置；匹配块有非空 Markdown/HTML 表格就算“转出了表格”；严格图表数值准确率另行标记为未评。

严格内容正确率没有 GT 时标为 `unavailable`，但“是否产出非空内容”的
`content_output_recall` 可以计分；`on_output_coverage` 作为兼容别名保留，不能把缺少严格 GT 当成该能力的 0 分。`manifest.json`
的 `summary.coverage` 和评分输出的 `feature_coverage` 记录这个边界。

## 最新 PDF2Text 与 raw middle_json

最新代码的对外入口是：

```text
POST http://<p2t-host>:<port>/v1/pdfparse
```

`pdf2text` 的对外入口是 `/v1/pdfparse`，内部再调用 MinerU `/file_parse`。`/v1/pdfparse` 当前只返回最终 Markdown、页数和错误，不透传 `middle_json`。因此：

- 复核 Markdown 代理时，调用 `/v1/pdfparse` 即可；
- 需要 image/chart/header/footer 的结构化清除率时，在内网直接调用已配置的 MinerU `/file_parse`，保存完整 JSON；
- 本地再加载 PDF2Text 的同一份 `mineru_filters.py`，离线执行过滤，不重新请求模型。

本项目提供的 `tools/collect_mineru_middle_json.py` 只负责第二步。它不会调用 P2T，也不会改变模型输出；它复刻 P2T 内部发送给 MinerU 的字段：`return_middle_json=true`、`return_images=true`、`image_analysis` 和 `backend`。

历史回放使用 `1806ec1`。版本、校验和及重评证据见 [129 子图补偿复评](../../experiments/legacy129-subimage-20261123/README.md)。

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

| 组 | `keep_appendix` | `keep_header_footer` | `image_analysis` | `chart_analysis` |
| --- | ---: | ---: | ---: | ---: |
| `off` | false | false | false | false |
| `appendix` | true | false | false | false |
| `header_footer` | false | true | false | false |
| `image` | false | false | true | false |
| `chart` | false | false | true | true |

seal 是 image 的视觉子类型，不再有 `seal_rec` 实验开关。`chart_analysis=true` 组同时保留 image 分支，因为 P2T 会先向 MinerU 请求 `image_analysis=true`。

### 内网采集 raw

同一批 PDF 只采集两遍。`A` 关闭 image analysis，`B` 开启 image analysis；两次使用同一个 MinerU3 provider、backend 和 PDF 集合：

```bash
python3 tools/collect_mineru_middle_json.py \
  --url http://<mineru-host>:<port>/file_parse \
  --pdf-dir /data/legacy/source \
  --output /data/feature-raw/A \
  --image-analysis false \
  --backend vlm-vllm-async-engine \
  --model mineru3 \
  --token <token> \
  --jobs 2

python3 tools/collect_mineru_middle_json.py \
  --url http://<mineru-host>:<port>/file_parse \
  --pdf-dir /data/legacy/source \
  --output /data/feature-raw/B \
  --image-analysis true \
  --backend vlm-vllm-async-engine \
  --model mineru3 \
  --token <token> \
  --jobs 2
```

每个目录会保存每份 PDF 的完整 MinerU JSON 和 `manifest.json`。一个 provider 的全量成本是 `129 × 2 = 258` 个 MinerU 解析任务；P2T 的最终 Markdown 不会被当作 middle_json 使用。

### 本地离线回放

把 raw 目录和对应的 PDF2Text 内容过滤源码拿回本地；`--pdf2text-source` 指向提供 `apply_content_filters` 的快照：

```bash
.venv/bin/docbench build-feature-ir \
  --gt artifacts/legacy-features-20261119 \
  --raw-off /data/feature-raw/A \
  --raw-on /data/feature-raw/B \
  --pdf2text-source /path/to/pdf2text/source \
  --model mineru3 \
  --output /tmp/feature-ir

.venv/bin/docbench evaluate-feature-matrix \
  --gt artifacts/legacy-features-20261119 \
  --pred /tmp/feature-ir \
  --output /tmp/feature-scores
```

如果只有已保存的 IR、没有 raw middle_json，而 v2/v3 只是经过审阅的 GT 修订，
可以显式使用 `--allow-gt-revision` 重评；评分 provenance 会同时保存 IR 原始 GT
哈希和本次使用的 GT 哈希。没有这个开关时，哈希不一致会拒绝评分，避免误把不同
数据集混在一起。重新生成 IR 时不需要这个开关。

`build-feature-ir` 会生成五组公开结果：`off`、`appendix`、`header_footer`、`image`、`chart`，以及一个内部的 `controls/image_off`。后者使用 B 的同一份识别结果但关闭 image/chart 内容，用来计算 image 的成对清除率，不增加推理次数。

只有 B 时可传 `--visual-only` 并省略 `--raw-off`，只生成后三个视觉组；附录和页眉页脚不出分。非空率是回归诊断，不代表 subtype、文字或数据正确率。

每组都是一份 PDF 一个 IR 文档。全量时是五组各 129 份；使用 smoke 子集时，先对 union 中的 PDF 生成 IR，再由评分器按各功能子集聚合。

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
  --gt artifacts/legacy-features-20261119 \
  --pred predictions/base \
  --subset-manifest /tmp/feature-subset.json \
  --subset-name union \
  --output /tmp/feature-scores/base

.venv/bin/docbench evaluate-features \
  --gt artifacts/legacy-features-20261119 \
  --pred predictions/appendix \
  --subset-manifest /tmp/feature-subset.json \
  --subset-name appendix \
  --output /tmp/feature-scores/appendix
```

子集清单和预测结果属于一次性实验材料，不需要提交到仓库。评分器会把子集名称、清单哈希和实际分母写入 `provenance.json`；不要用 `--allow-missing` 代替子集选择，因为那会把未运行的文档当成空预测。

矩阵主指标是开关清除率：附录页、边缘块、生成 image span、chart body 分别按过滤前单元统计。
按本次能力口径，image/chart 的 `content_output_recall` 同时作为“能否转出内容”的分数；
`on_output_coverage` 是兼容字段；
它不包含图内文字或图表数值的严格正确性判断。

评分器还会在 `metrics.json` 中写入独立的 `combined_visual` 诊断：以
`chart_analysis=true` 的视觉输出为唯一预测集合，分别给出类型严格和只看视觉
位置两种 image+chart 口径；它不替换四个功能的主分数。

已有的 `5 × 129` `/v1/pdfparse` 最终 JSON 可以继续用于旧 Markdown 代理复核，但不能替代上述 raw middle_json。它没有逐块类型、嵌套 chart body 或生成 span。

## 标题规则实验（单独一条）

标题规则不和四功能组混跑。对同一批 129 PDF、同一 MinerU3 上游、`relevel_titles=true`，只切：

```text
title_rules=false
title_rules=true
```

两组分别进入原有 TreeTitle-v2/AgentBuilder-v2 评测输入，输出目录和 provenance 分开。该对照可以回答 B1-B14 规则对标题树的影响，但不会改变四功能专项的分数，也不会覆盖旧的历史分数。
