# 新 session：P2T 工程适配

下面整段可以复制到新 session。评分代码及 GT 已提交；该 session 的工作边界是 P2T 适配。

```text
请接手 legacy 129 的 P2T 工程适配，直接推进已明确工作。不要扩大评测范围，也不要将历史候选当成最终实现。

工作目录：/Users/yixuan/Documents/doc-parse-bench

先读：
experiments/legacy129-subimage-20261123/TASKS.md
experiments/legacy129-subimage-20261123/native-mineru-3.3.1-review-20261124.md
experiments/legacy129-subimage-20261123/bug-compensation-plan-20261124.md
artifacts/legacy129-subimage-20261123/p2t-inner-handoff-20261124/README.md
该交接目录下 docs/compensation-design.md、docs/acceptance-checklist.md
docs/legacy129-scoring-contract.md

当前已提交：d6251ad（评分和交接代码），79d8eed（固定 v3 GT 和回放前置材料）。
评分已经收敛为 legacy129-content-v1；四项各 25%，subtype 错单图主分 0，图表只评明示值，缺证据 null，误删独立否决。本次没有修改 GT、运行新模型或输出正式总分。
校准分：附录两版 76.89，页眉页脚两版 81.48，图表 FT 70.51 / Origin 54.22，仅 11 图/78 明示值。图片与总分尚缺证据。不要重新设计公式、改 GT 或把校准 split 改名为 evaluation。
用户最新要求：本轮停止补证据、补取旧回包、补推或继续补齐图片分。不要执行上一轮的历史响应取回清单。下次评测材料按 docs/legacy129-next-evaluation-inputs.md 准备；当前 session 仍只负责 P2T 工程适配与本地测试。

P2T 原 ZIP：
/Users/yixuan/Documents/pdf2text_code_develop-1.6.0-8b747ca_20261123.zip
P2T 工作副本：
archives/pdf2text-develop-1.6.0-8b747ca-20261123/
工作副本已有历史候选修改；先记录文件状态和哈希，对照 ZIP 判断原有行为，补丁不能叠加。

MinerU 参考仓库：/Users/yixuan/Documents/OCR-Models/MinerU
不要安装依赖或切换共享 checkout。用户已确认工程按 MinerU 3.3.1 / mineru-vl-utils 1.0.5 逻辑推进。历史推理包报告 MinerU 3.1.14，要如实区分。

已核实：3.3.1 的 prepare_for_extract 同时跳过 image_block 父容器及覆盖的 image/chart 子块，后续没有父图或子图分析补偿；独立 image/chart 仍可分析。不要说所有 2605 输出都被 skip。
原始 P2T PDF 路径：请求 middle_json 和 images → 内存过滤 → Markdown 渲染 → 对外 Markdown 和 pages。

工程方向：
- 每个复合父框默认只选一种分析单位 parent 或 children，不默认父子双跑。
- 共图注、网格等保留父图，不能把保留自动等同于跳过分析；独立子图分别分析。
- 优先使用同一 MinerU upstream 的固定 layout/bbox 分析入口。原生有 extract_with_layout / aio_extract_with_layout，但内网 HTTP 契约尚未确认，不能虚构 endpoint 和字段。
- crop-as-page 会再次布局，只能作显式过渡路线；返回复合碎块或缺少整图分析证据时记 unresolved。
- 无实际父图响应不能拼父图答案，不复制子图 subtype。

必须满足：
1. image_analysis 和 chart_analysis 双关时完全原路径：零新增裁图、零补偿请求，过滤及成品与干净 ZIP 一致。布局中仍可能有 sub_images。
2. 至少一个分析开关开启才进入新增决策；原有普通图片、图表、附录、页眉页脚及标题功能不能受损。
3. 正式目标 MinerU3、relevel_titles=true、title_rules=false；若本地未实际执行标题重排，写明。
4. 不依赖 GT、文件名、Origin 或这 10 个框的编号决定线上拆保，不为样本硬编码特例。
5. chart-only 单独验证；候选范围尚未冻结，不能让图表单开等同图片单开或对所有普通图片补请求。
6. timeout、request_error、not_called、empty、unresolved 分开。8 张/4 秒不是既定预算，离线时长不能当线上时延验收。
7. 不访问、部署或修改内网，不采集 2605 base，不新增模型评测；由用户安排真实内网推理。

先把现有 keep_shared_caption / keep_multirow 直接跳过分析的候选改为显式分析计划、可替换 analyzer、来源可追溯的结果回填。
fixed-layout HTTP 未确认时可完成接口抽象、注入测试和回填，不把猜测接口接成默认可用。
需要改变尚未确认的交付语义时，结合具体 case 说明影响，一次问一个关键问题；独立工程工作继续做。

优先 case：Fig.1 父图 subtype；Fig.5 双柱图 10 个明示值；Fig.6 网格；消防 _2 共图注线路组图；消防 _5 两个流程/线路图；维修手册有字照片与缺标签；盐湖独立无字照片。
审阅入口：artifacts/legacy129-subimage-20261123/analysis-units-review-20261124/review.html

交付：P2T 代码、有意义的测试、相对干净 ZIP 的独立补丁及试应用结果、四种视觉开关和原功能回归、unresolved 和未定接口/语义清单。
新产物放 artifacts/legacy129-subimage-20261123/p2t-adapter-next-session/，说明写 experiments/legacy129-subimage-20261123/p2t-adapter-next-session.md。
保护当前脏工作区；不要提交整个仓库、清理其他 artifacts，或改 AgentBuilder-v2 / TitleTree-v2。
评分及共享交接目录由原 session 整合；先不要修改主 TASKS.md、p2t-inner-handoff-20261124/ 和它的 ZIP，完成后回传变更清单。
```
