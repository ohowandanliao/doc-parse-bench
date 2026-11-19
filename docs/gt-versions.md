# 129 GT 版本登记

129 份文档有三套不同用途的 GT。它们不是三份可以互换的同义副本；评测命令必须按用途选择。当前默认 `docbench run` 仍使用活动的 81 份 `annotated-20261111`，不会自动切换到下面任何一套 129 GT。

| 版本名 | 来源和路径 | 主要内容 | 用途 | 不用于 |
| --- | --- | --- | --- | --- |
| `legacy-129-markdown-v1` | `data/legacy/groundtruth/` | 129 个旧 Markdown；包含历史正文、旧标题、普通表格，以及部分图片/图表转录 | 历史 `legacy_compat` 复现；为图表候选内容提供来源证据 | 新版 TreeTitle-v2/AgentBuilder 主 GT；四功能结构分 |
| `legacy-129-annotated-v2` | 原包 `legacy_129_pack_20261118.tar.gz`；解压后是 `runs/`、`annotations/`、`sources/` | 129 份、372 页的结构化 GT；机器标注结果叠加人工页面修订，标题、页码、块类型、层级、bbox 和阅读顺序更可靠 | 显式运行 129 份 AgentBuilder/TreeTitle-v2 的标题主 GT；也是四功能 GT 的结构来源 | 直接当作旧 Markdown 历史分；直接当作 chart 内容数值 GT |
| `legacy-129-feature-v3` | 由 v1＋v2 生成到 `artifacts/legacy-features-20261118/` | 轻量包中的 129 条 `records.json`，把 v2 的结构位置与 v1 的旧内容候选对齐，并记录每个功能的有效分母和覆盖状态 | 只用于 `keep_appendix`、`keep_header_footer`、`image_analysis`、`chart_analysis` 四功能专项 | AgentBuilder、TreeTitle-v2、OmniDocBench、MPDocBench 三个基础榜 |

## 版本关系

```text
legacy-129-markdown-v1  ──历史内容/图表候选──┐
                                             ├──> legacy-129-feature-v3
legacy-129-annotated-v2 ──结构/标题主 GT──────┘
          │
          └──显式 129 AgentBuilder/TreeTitle-v2 评测
```

v2 是“新标注终态”，不是 v3。v3 是为了四个 PDF2Text 开关额外生成的评测视图：附录和边缘块使用 v2；旧 Markdown 的图片/图表转录只作为内容候选审计。v3 的 `chart_content_*` 不能反过来定义 v2 的标题或正文 GT。

## 怎么选

- 复现历史 129 分数：选择 `legacy-129-markdown-v1` 和 `legacy_compat`。
- 重新评估 129 的标题/AgentBuilder：选择 `legacy-129-annotated-v2`，显式准备对应的 pages/documents 和预测，运行 TreeTitle-v2/AgentBuilder；不要读取 v1 的 Markdown 作为标题 GT。
- 测四个 PDF2Text 功能：先用 v1＋v2 生成 `legacy-129-feature-v3`，再运行 `docbench evaluate-features`；不要把四功能分并入 AgentBuilder。

生成 v3：

```bash
.venv/bin/docbench build-feature-gt \
  legacy_129_pack_20261118.tar.gz \
  data/legacy/groundtruth \
  artifacts/legacy-features-20261118 \
  --old-pdf-dir data/legacy/dataset/pdf/source
```

`build-feature-gt` 默认只输出 `manifest.json`、`records.json` 和 `comparison.md`，因为 v2 原包已经保存完整结构来源；需要本地调试展开 JSON 时才加 `--include-structured`。输出 `manifest.json` 会记录 `gt_lineage`，说明 v1 是旧内容来源、v2 是结构主来源、v3 是专项派生版本。任何报告都应同时保存所选版本名和来源哈希，不能只写“129 GT”。

四功能的 smoke 子集清单是一次性实验文件，不属于 v3 正式 GT；放在 `/tmp` 或本地实验目录即可。评分器通过 `--subset-manifest` 和 `--subset-name` 读取它，不会把未运行的 129 文档错误记成 0。
