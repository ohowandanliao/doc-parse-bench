# 已有校准证据快照

两份 evidence 对应同一个未修改的 `artifacts/legacy-features-20261119/rubric-pilot-gt.json`，GT SHA-256 为 `6d98b54495edc5f61422103a3a032a64ed93c72383a3df068e3c22238f610b72`。

每份文件合并四类已有证据：附录／页眉页脚开关回放、11 图的明示值、V2 六个图片控制 case、`bc_108` 流程图节点与关系。合并前逐条验证来源 GT 是当前 pilot 的原样子集，且来源 evidence 的 GT 哈希正确。`source_evidence` 记录每份来源路径与哈希；来源及复核页面留在本机 archives/artifacts，未嵌入这份轻量证据文件。

`stage=replay`、实际未执行标题重排；FT 部分视觉交付来自历史 V2 候选，Origin 部分沿用历史 IR。它们不是新父图补偿后的最终成品。未覆盖的 case 仍由完整 GT 留在分母中，不能剔除以生成总分。

使用方法见 [固定评分口径](../../../docs/legacy129-scoring-contract.md)。复算不需要重新访问模型，也不需要其它 artifacts；只需本目录 evidence、已记录的 pilot GT 和仓库评分模块。
