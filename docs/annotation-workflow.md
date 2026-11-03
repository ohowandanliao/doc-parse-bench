# 持续新增标注与 GT 版本管理

数据规模由输入目录决定，转换代码不依赖固定的 81 份或 597 页。每批新增文档沿用同一套流程：归档输入、整理文档 ID、导入快照、检查质量、导出两套 GT、冻结版本，再补齐模型预测并评测。

## 1. 保存原始批次，整理当前集合

原始批次存到 `data/annotation_batches/<batch>/`，保留 `runs/`、`annotations/`（也接受 `annotated/`）及 `sources/`，不要覆盖已经用于历史评测的批次。数据目录被 Git 忽略，应在自己的数据存储中备份；源码仓库中的文档和 Git 提交不能代替原始数据备份。

将本次准备发布的完整集合整理到 `data/annotations/`：

```text
data/annotations/
  runs/<document_id>/page_0001/result.json
  annotations/<document_id>/page_0001.json
  annotations/<document_id>/document.json    # 有则保留确认记录
  sources/<document_id>.pdf
```

新文档使用稳定且唯一的 ID；同一文档的 runs、patch、PDF、模型输出必须使用同一个 ID。若两个批次 ID 相同，要先判断是同一文档的修订还是 ID 碰撞，不能用文件覆盖顺序自动选择。当前 CLI 不会自动合并多个批次目录，需要先整理这一完整输入目录。

对同文档的标注修订，保留新的完整页面快照：有 patch 时整页替换，没有 patch 才用 chain；空 patch 仍表示空页。多标注员冲突会报错，需要明确选定快照。若撤销旧 patch、替换 PDF、迁移页码，也要作为数据修订记录，不能静默改变旧版本。

新增时检查 PDF 内容重复，不能只检查文件名。现在旧、新集合已发现两份完全重复 PDF；扫描版或重新排版还可能产生近似重复。把任意两个待比较的 PDF 目录传给 `audit-quality` 的两个参数可做内容指纹检查，详见 [质量说明](quality.md)。

## 2. 导入一个明确版本

在仓库根目录执行，使用尚不存在或为空的输出目录：

```bash
source .venv/bin/activate

docbench import-gt data/annotations data/gt_versions/v1.1/ir \
  --dataset-version v1.1

docbench audit-quality data/gt_versions/v1.1/ir/documents \
  data/gt_versions/v1.1/quality

docbench export-gt data/gt_versions/v1.1/ir/documents \
  data/gt_versions/v1.1/gt
```

这里的 `v1.1` 是示例标签，不表示当前数据已经发布为该版本。可以采用团队约定的版本名称；增加文档、修正文档、改变纳入范围或转换规则时，都生成新目录和新标签。命令不会覆盖非空输出目录，已冻结的 v1.0 不应原位更新为 v1.1。

如果标注目录另有位置，使用 `--annotations <directory>`。如果 PDF 是原书抽样，提供 `--document-map mapping.json` 记录原页码；不要按“抽样部分1/2”的名字猜原文连续性。补充内容见 [数据契约](data-contract.md)。

## 3. 每次自动留下什么

| 记录 | 内容 |
| --- | --- |
| `ir/audit.json` | 数据版本、导入时间、转换代码版本及源码指纹；每页 run／patch 哈希、最终来源、PDF 哈希、文档确认快照；文档／页面／块／关系数量及问题 |
| `ir/audit.json → dataset_sha256` | 由输入内容形成的集合指纹；目录移动不改变它，run／patch／PDF／确认文件／页码映射改变会改变它 |
| `ir/documents/*.json` | 页面终态、原始标注元信息、跨页关系和数据版本 |
| `quality/audit.json` | 结构检查和跨页 PASS 证据；结构通过不等于全文人工验真 |
| `gt/source_audit.json` | 与当前中间文档哈希一致时，复制导入审计，便于随 GT 归档 |
| `gt/manifest.json` | 数据版本、转换代码指纹、中间文件哈希、导入集合指纹、两套 GT 哈希及页面／文档文件名映射 |
| 评测目录的 `provenance.json` | 使用的数据版本、GT 哈希／来源指纹、转换信息、后端版本及预测覆盖率 |

若手动编辑了中间文档，导出器会发现它与旧导入审计的哈希不一致；仍记录实际导出输入的哈希，但不再声称旧 audit 完整证明这些编辑。正式修订应回到标注源修改后重新导入。记录 `git_dirty=true` 的构建可用于草稿检查，正式发布应提交转换代码后重新生成，便于复现。

哈希是内容身份，版本标签是团队给这一集合的名称。两者都保留，不能仅凭“v1.1”或“文档数一样”判断使用了相同数据。

## 4. 审核与冻结

处理完结构报错、无效关系和重复内容；对正文、表格数字、标题树、跨页关系保留人工复核记录。`document.json` 的确认状态会留存，但导入器不会替代团队判断哪些文档已经可以发布。

每个版本在数据存储中留一份 `release.md`，记录以下内容，不需要创建第二份标注文件格式：

```text
版本：v1.1
父版本：v1.0
变更：新增哪些 document_id；修正／移除哪些文档及原因
原始批次：保存位置与批次 ID
确认人／时间：...
审核结论与已知问题：...
dataset_sha256：来自 ir/audit.json
GT SHA-256：来自 gt/manifest.json
转换代码：commit、source_sha256、git_dirty
```

将原始输入快照、页码映射、ir、GT、audit 和 release.md 一起归档。自动哈希记录不会自动复制所有原始 run／patch／PDF，原始批次需要自行保留。

## 5. 数据增加后如何评测

先补齐新增文档的模型输出。标准模式默认将缺失结果按空预测计分并报告；某模型只有旧版本输出时，不宜把新增集得分下降解读为能力退化。公平比较固定同一版本、同一文档／页面集合及同一后处理参数。

使用固定 standard 模式时，在评测 YAML 中加版本标签，调整输入与输出：

```yaml
profile: standard
dataset_version: v1.1
annotations: ../data/annotations
output: ../artifacts/runs/standard-v1.1
jobs: 2
models:
  NaviDC-OCR:
    adapter: NaviDC-OCR
    source: ../data/predictions/results/NaviDC-OCR
```

路径相对 YAML 所在目录。运行 `docbench run <yaml>` 会把版本标签传给导入、导出和两套评测报告。该入口在同次运行中重新构建 GT；评测期间不要修改正在读取的标注目录。

已经冻结的 GT 可以配合分步命令直接评测，避免重新导入：

```bash
docbench evaluate --backend MPDocBench \
  --gt data/gt_versions/v1.1/gt/MPDocBench/gt.json \
  --title-gt data/gt_versions/v1.1/gt/MPDocBench/markdown \
  --pred artifacts/predictions/v1.1/NaviDC-OCR/MPDocBench \
  --output artifacts/reports/v1.1/NaviDC-OCR/MPDocBench \
  --figure --relations --allow-missing
```

OmniDocBench 用对应的 `OmniDocBench` 路径和后端名。两套的单位、关系和指标说明见 [评测口径](evaluation.md)。旧版 129 篇保持独立历史集合（legacy_compat 评测器），统一质量标准、补标和去重之前不直接并入新版本。
