# MPDocBench 使用说明

standard 模式会同时运行 OmniDocBench 和 MPDocBench；本页说明 MPDocBench 的文档输入、跨页指标和报告。数据版本流程见 [新增标注与版本管理](annotation-workflow.md)。

## 输入单位与 GT

MPDocBench 按整份文档评测。当前集合有 81 份 PDF、597 页，转换后是 81 个文档级 sample，统一保存在 `gt/MPDocBench/gt.json`。同一次导出还会生成 OmniDocBench 的 597 个页面 sample；两者不能把样本数当成同一个分母。

文档 GT 结构如下，省略具体块内容：

```json
{
  "page_info": {
    "image_path": "example.pdf",
    "width": [595, 595],
    "height": [842, 842],
    "images_list": ["example/page_1.jpg", "example/page_2.jpg"],
    "page_attribute": {"data_source": "custom", "language": "mixed"}
  },
  "layout_dets": [],
  "extra": {
    "relation": [
      {"source_anno_id": "p1.text1", "target_anno_id": "p2.text1", "relation_type": "truncated"},
      {"source_anno_id": "root", "target_anno_id": "p1.title1", "relation_type": "parent_son"}
    ],
    "continuity": "unknown"
  }
}
```

示意中的关系端点需要在真正的 layout_dets 中存在。每个块有文档内唯一 ID、page_id、全局阅读顺序，以及 text／html／latex。GT 的跨页续接来自人工页面快照中的链接；标题树来自标题层级和有效 parent_id。多页表格组带 merged_html，链接按阅读顺序导出。

PDF 可以是连续切片或抽样片段，不要求整本书全量输入。原页码已知时提供 document-map；不会自动把“抽样部分1／2”拼接，也不会把 GT 跨页关系复制给预测。

## 模型预测和合并

每份文档对应一个 `<document_id>.md`，例如 `example.pdf` 对应 `example.md`。模型原始输出先导入统一结构，再按 MPDocBench 文档级规则导出。

- MinerU 根据已有 merge_prev 标记恢复预测关系；没有标记的跨页内容不自动猜测。
- Unlimited OCR 2 从 cross／append／MERGE 标记恢复模型自己的关系。
- NaviDC-OCR 和 OvisOCR2 在现有结果中缺少显式跨页关系，默认按页序组成文档。组成一份文件不代表已经判断并合并了所有续段／续表。
- `--merge-context` 可统一启用额外保守规则，最终值与合并证据留在运行记录中。

默认使用 native 图表任务，chart 与真正 table 分开；历史 129 篇没有同等级别的块和关系标注，不能仅把旧 Markdown 拼起来就声称具备完整 MPDocBench GT。

## 运行

完整流程使用固定 standard 模式：

```bash
docbench run configs/standard.yaml
```

若要只评 MPDocBench，使用已导出的 GT 和预测：

```bash
docbench evaluate --backend MPDocBench \
  --gt artifacts/prepared/baseline/gt/MPDocBench/gt.json \
  --title-gt artifacts/prepared/baseline/gt/MPDocBench/markdown \
  --pred artifacts/prepared/baseline/pred/NaviDC-OCR/MPDocBench \
  --output artifacts/reports/NaviDC-OCR/MPDocBench \
  --figure --relations --allow-missing
```

输出目录需要为空。分步 evaluate 默认使用上游 APTED；standard 模式默认启用已经对账的大表格精确加速。`--cdm` 需要另外安装公式渲染环境；本次已有正式结果未计算 CDM。

## 指标与结果

| 指标 | 检查内容 |
| --- | --- |
| 文本／公式编辑距离、表格 TEDS、阅读顺序 | 文档中的内容和顺序 |
| merged_text、merged_table | 带 GT 续接关系的文本／表格的合并结果 |
| HeadTEDS | 标题文字、顺序和父子树结构 |
| FigureF1 | 图像的页码与位置匹配 |
| text_relation／table_relation F1 | 预测合并是否符合 GT，另列同页和跨页分项 |
| title | 本项目保留的历史标题扩展分，与 HeadTEDS 分别报告 |

每个后端报告包含 `metrics.json`、`per_doc_scores.json`、`provenance.json`、`evaluation.log`；官方原始产物在 `runtime/result/eval/`。已有四模型文档级正式结果位于 `artifacts/benchmark/baseline/<model>/MPDocBench/`，汇总在 `artifacts/benchmark/baseline/summary.md`。数据和这些产物未随源码上传，数值与验证范围可看 [验收记录](validation.md)。

## 当前结果的限制

Unlimited OCR 2 有两份推理被截断，虽然文档文件覆盖是 81/81，但实际上少了 57 页；文档级评分使用返回的残缺内容与完整 GT 对比，provenance 保留 incomplete_documents。不能只看文件覆盖率就称其全部推理成功。

MinerU 和 NaviDC-OCR 旧输出未保留标题 level，适配时使用默认一级，限制 title／HeadTEDS 的解释。Unlimited OCR 2 与 OvisOCR2 还分别有已确认的重复输出异常。详情见 [模型适配](model-adapters.md) 和 [截断重跑](inference.md)。
