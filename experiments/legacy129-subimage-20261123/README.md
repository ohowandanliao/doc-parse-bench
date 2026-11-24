# 129 子图补偿复评

2026-11-24 新增[父图／子图分析审阅 HTML](../../artifacts/legacy129-subimage-20261123/analysis-units-review-20261124/review.html)：覆盖全部 10 父框、27 份子裁图响应，比较整图／子图建议与全拆后果，附 3.3.1 原生、原始 P2T 和原包源码。建议清单尚未冻结为线上规则；其余本页 V1、V2 数字保留为历史回归。

当前范围、顺序和进度见 [任务清单](TASKS.md)，本轮先做[只读复核](readonly-review-20261124.md)。[P2T 前置拆分规则与复评](split-policy.md)保留为历史候选，其父图分析和双关兼容尚待修正。本页保留 V1 历史；V2 的内容计分和补丁见 [内容分数及差距](content-scorecard.md)。本目录的回放脚本已更新为前置候选，不能再用现版脚本复现旧 V1。

冻结使用仓库的修订 v3，129 篇、372 个物理页，图片含印章 118 块、图表 73 块。`records.json` 的 SHA-256 是 `a1384023b6bc67aba52b312091f7bd729c2fc0eba7940e745d422e56fd0c9b29`，不是推理包中同名的旧 v3。原 PDF 是内容真值，Origin 仅作对照。

## 历史过滤器复跑

`1806ec1fc3b7b5268f76df8571263c48d8d4d5a8` 的 `mineru_filters.py` SHA-256 为 `a21c6948111b842a9426cfe58f98e0b99c9bcf09e2a68a3d3ecd63f03d775405`；旧源码 ZIP SHA-256 为 `cfd0415069c6b9365e71aa2288452764446841ec47a59181409eb7488a9be450`。复跑使用 `build-feature-ir --visual-only` 和 `evaluate-feature-matrix`，配置与旧 IR 一致：`MinerU3`、目标 `relevel_titles=true`、`title_rules=false`；实际比较的是内容过滤后、标题重排和 Markdown 渲染前。

FT 拆前的 129 个 B 原始响应和 PDF 哈希均与旧 IR 清单相符，与旧 IR 用新 GT 重评的逐文档图像、图表和合并诊断也完全一致。FT 展开包只修改 6 篇（10 个父块、27 张重推裁图，拆 9 保留 1），其余 123 篇复用原 B。Origin 随包的 6 份原始响应哈希均对上旧清单，实际重放的逐文档分也与旧 IR 对齐。Origin 全量栏仍来自旧 IR 的重评，不声称重新处理了 129 份 Origin 原始响应。

| 诊断指标 | FT 拆前 | FT 包内拆后 | Origin 旧 IR 重评 |
| --- | ---: | ---: | ---: |
| 图片/印章定位召回 | 72/118 | 80/118 | 80/118 |
| 图片/印章定位精确率 | 72/79 | 80/88 | 80/96 |
| 图片/印章匹配且内容非空 | 55/118 | 67/118 | 70/118 |
| 图表定位且内容非空 | 71/73 | 73/73 | 73/73 |
| 图表定位精确率 | 71/77 | 73/79 | 73/79 |

非空差距由 15 张降到 3 张，即这一轮裁图重推与回填净补 12 张；11 张是非空的视觉分析，1 张是 `bc_059` 的 OCR 回退「音量调节」。这不是“12 张内容均正确”，也不能推出两种基础模型的能力差只来自版本。图表增益来自 `5-1双栏表格2.pdf` 第 4 页左右柱图；两份表的 10 个明示值可按原图逐项核对。`bc_062` 两组共图注的线路示意被拆成四个半框，原有两个位置命中丢失；`bc_022` 第 2 页的 Fig. 1 也应按同一组图保留，第 5 页的多格图按本包策略保留父块。

逐文档计数、回放清单及源哈希位于 `artifacts/legacy129-subimage-20261123/` 中的 `ft-{original,expanded}-scores/` 和 `origin-{6docs,legacy-ir}-scores/`。原推理包的 case 图和裁图可本地运行 `open archives/129-subimage-inference-full-20261123/review/report.html` 查看。旧 IR 与原始采集未删除。这里的数字不是最终交付准确率或 RSI；本轮不重报附录和页眉页脚。

## MinerU 原生分组与策略

- 本机 `OCR-Models/MinerU` 为 4.1.1（`505fcb0`），`mineru/backend/analysis/pdf/visual_containers.py` 对 xhigh 结果补**整图容器**，不是将容器拆成独立交付图。它以本地整图框、至少两个视觉成员和相应覆盖为证据。
- P2T pin 的 `mineru==3.3.1` 在 `mineru/utils/visual_magic_model_utils.py::absorb_image_block_members` 将至少 90% 被容器包含的 image/chart 记为有顺序的 `sub_images`，随后渲染的是父图；`mineru_vl_utils==1.0.5` 的 `prepare_for_extract` 排除 `image_block` 本身和被它覆盖的 image/chart。源码行为与本包的空父图一致；不能证明某份原始请求究竟执行了哪些模型内部调用。
- 候选策略将**分析单位**和**交付单位**拆开。仅对空父图校验坐标和素材，再逐裁图分析。近邻图注横跨各面板时保留父图，逐面板保留可归属内容，不从子图倒填父图 subtype。独立且不重复的可解析图表可以拆成表；重叠／缺证据、文字碎片占多数、裁图请求失败或超时则保留原父图。首尾图注按原顺序只保留一次。
- 这条线上策略不读取文档名、GT、GT IoU 或 Origin。它是在本批已知坏例上校准的，**不是独立泛化结果**。上线前从同一业务口径中按文档留出含组图、独立图、相邻短图注、图内表格和无图注的页，盲评拆／保和成品误删，检查额外延迟。不要用本批 IoU 继续调阈值。

## 8b747ca V1 实际回放

`replay_p2t.py` 按裁图 SHA-256 精确复用全部 27 份响应，没有网络推理。FT 拆前／新版使用同一份 129 B、同一 GT 及过滤开关；Origin 仍以哈希对齐的历史全量 IR 为对照，并实际重放随包 6 篇。子图新策略为 **拆 6、保留并补内容 3、原样保留 1**。指标在真实 `apply_filters` 后的 IR 上计算；实际 `mineru==3.3.1` Markdown 重渲染覆盖受影响的 6 篇，实际跳过内网 PaddleX 标题重排（目标仍为 `relevel_titles=true`、`title_rules=false`）。

| 诊断指标 | FT 拆前 | FT 包内拆后 | FT 新策略 | Origin 旧 IR 重评 |
| --- | ---: | ---: | ---: | ---: |
| 图片/印章定位召回 | 72/118 | 80/118 | 82/118 | 80/118 |
| 图片/印章定位精确率 | 72/79 | 80/88 | 82/85 | 80/96 |
| 图片/印章匹配且内容非空 | 55/118 | 67/118 | 69/118 | 70/118 |
| 图表定位且内容非空 | 71/73 | 73/73 | 73/73 | 73/73 |

新版实际多补 14 个非空块，**含 1 个 OCR 回退**；不计该回退为 68/118。与包内策略相比，`bc_062` 保住两个父块的位置和共用图注，各补回一份可归属面板输出；`bc_022` 第 2 页只交付一张 Fig. 1，内容仍分面板，第 5 页的格图未展开。第 4 页新增的两张图表实际渲染为表，逐项对照原图 GT 的系列、类别、值和单位为 **10/10**，Origin 同为 **10/10**；Fig. 5 在两张表之后只出现一次。关闭生成内容后原图和图注保留。这不是逐块 subtype 或内容全对，也不抵消其他误删。剩余非空净差 1 张，逐文档差异见复核页，不能推断两版只差同一张图。没有补齐的 `raw-A`，不报新的附录、页眉页脚或 RSI 总分。

仓库根目录下运行 `open artifacts/legacy129-subimage-20261123/p2t-replay/review.html` 查看八个受影响页，含当前 GT、原页框、裁图、FT 拆前／新版和 Origin 的实际输出。运行记录在同目录的 `*-scores/`、`crop_replay.json` 和各变体 `manifest.json`。

## V1 补丁与复跑

`artifacts/legacy129-subimage-20261123/pdf2text-8b747ca-subimages.patch` 已在原始 ZIP 的洁净文件上试应用。内网 P2T 仓库执行 `git apply --check -p1 /path/to/pdf2text-8b747ca-subimages.patch` 再 `git apply -p1 /path/to/pdf2text-8b747ca-subimages.patch`。仅在 MinerU3 实例开启 `PDF2TEXT_MINERU_CONFIG__SUBIMAGE_ANALYSIS=true`，默认关闭、MinerU4 路由不变。子图请求复用同一 upstream，默认每篇最多 32 裁图、2 并发、120 秒；图片和图表分析都关时不追加请求。关回该配置即可回退。

使用能导入 bench 与 P2T、含 `mineru==3.3.1` 的 Python 3.11 环境，从仓库根目录复跑：

```bash
pack=archives/129-subimage-inference-full-20261123
gt=artifacts/legacy-features-20261119
p2t=archives/pdf2text-develop-1.6.0-8b747ca-20261123/src
out=/tmp/129-subimage-p2t-replay
PYTHONPATH="$p2t:src" python experiments/legacy129-subimage-20261123/replay_p2t.py \
  --pack "$pack" --gt "$gt" --output "$out"
PYTHONPATH=src python experiments/legacy129-subimage-20261123/review.py \
  --pack "$pack" --gt "$gt" --replay "$out"
open "$out/review.html"
```

内网已装部署用 PaddleX 时，给第一条脚本加 `--relevel-titles` 复核实际线上配置，再验证真实 `/file_parse` 的时延和最终 Markdown。开发环境通过 32 项 bench 专项测试、78 项 P2T MinerU 测试。未触碰内网、其他评测主线或最新版 GT。旧 `1806ec1` 源码和归档已移出工作区至废纸篓。
