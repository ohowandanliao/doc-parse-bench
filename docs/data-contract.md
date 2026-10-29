# 数据契约

## 标注导入

```text
<pack>/runs/<document>/page_0001/result.json
<pack>/annotations/<document>/page_0001.json
<pack>/sources/<document>.pdf                  # 可选，用于真实页尺寸
```

也接受 `annotated/`；目录名不一致时用 `import-gt --annotations <path>` 指定。多个标注员快照同时存在会报错，应显式选择一个标注目录，不能按更新时间任意挑选。

页面终态严格为：

```python
final_blocks = patch["blocks"] if patch_exists else run["revision"]["blocks"]
```

人工快照是整页替换，即使 `blocks=[]` 也应保留为空页。不得把 patch 当增量 diff，不得把人工删除的块从 chain 补回来。文档／页身份、重复块 ID、缺页、孤立 patch、坐标都会检查。`document.json` 是确认元信息，不是页面内容来源。

每次导入生成 `audit.json`，记录来源文件 SHA-256、patch 覆盖页数、chain 页数、块数、关系数和无法解析的关系。块中的人工字段和证据保存到 `metadata`，不会用 chain 元数据覆盖 patch 的字段。

当前数据：81 份、597 页、8355 块；551 页来自 patch、46 页来自 chain；147 条去重后的有效跨页链接。一个图注到下一页正文的人工跨页链接保留为文本家族关系。

## 中间格式

`schema_version = doc-parse-bench.v1`。文档 ID 来自目录／模型 stem，在文档中保留原块 ID。页码从 1 开始，bbox 为归一化 `[x1,y1,x2,y2]`；GT 导出时再乘实际 PDF 宽高，PDF 不存在时采用规范化的 1000×1000 坐标系。

```json
{
  "schema_version": "doc-parse-bench.v1",
  "id": "example",
  "pages": [{
    "number": 1, "width": 595, "height": 842,
    "blocks": [{
      "id": "candidate.block.p1.0001", "type": "title", "text": "方法",
      "html": "", "bbox": [0.1, 0.1, 0.9, 0.2], "level": 1, "metadata": {}
    }],
    "metadata": {"source": "patch"}
  }],
  "relations": [],
  "metadata": {"origin": "annotations", "continuity": "unknown"}
}
```

块顺序就是阅读顺序。GT 使用 `reading_order` 排序；模型使用原生返回顺序，不按几何位置重新排列多栏。

## 两套 GT

OmniDocBench 每页一个 sample；文件名 `<doc>__p0001.md`。`layout_dets` 包含类别、polygon、块 ID、顺序及 text/html/latex，页面信息在 `page_info`，页内关系在 `extra.relation`。

MPDocBench 每份 PDF 一个 sample，预测 `<doc>.md`；`page_info.width/height` 为页尺寸数组，块带 `page_id`，`order` 是文档内全局顺序：

- `cross_page_text`、`cross_page_table` 的前驱／后继转成去重的 `truncated` 关系。
- `title.level` 和有效的 title `parent_id` 转成 `parent_son` 关系，并添加虚拟 `root`。
- 表格关系组先生成 `merged_html`，保留 span，合并时去掉重复表头前缀。
- 跨页边按阅读顺序排列，保证上游的增量分组器能够识别超过两页的链。

## 连续页与抽样

MPDocBench 的评测单位是文档，但并不要求每份输入都是原书全本。多页切片可以评测；“原文连续性未知”和“已知连续”需要区分。不会按文件名前缀把“抽样部分1/2”自动拼成原书。

可对 GT 和预测使用相同 `--document-map mapping.json`：

```json
{
  "example": {
    "source_document": "original.pdf",
    "original_page_numbers": [19, 20, 25]
  }
}
```

显式非连续页不参与自动边界合并。标注中明确保留的人工链接仍会导出，不根据文件名猜测重编号后的 block ID。

## 覆盖率

OmniDocBench 比较页面文件集合，MPDocBench 比较文档文件集合。默认缺失即报错；`--allow-missing` 将缺失文件写为空内容交给评测器，阻止上游静默跳过缺失结果。

部分文档输出有文件但页数不足时，`incomplete_documents` 记录预期页数、返回页数和 `finish`。文档级比较对完整 GT 使用其已返回的内容。OmniDocBench 明确计缺失页为空预测，不复制邻页填充。
