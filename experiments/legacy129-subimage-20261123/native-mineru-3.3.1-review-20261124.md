# MinerU 3.3.1 原生 `image_block`／`sub_images` 复核

更新时间：2026-11-24。本文区分采集服务报告版本、P2T 锁定依赖和本机参考代码，不把较新版本直接当作采集服务行为。

用户已确认后续适配以 **3.3.1** 代码逻辑推进。版本来源继续记录，但不再因未确认采集服务 utils 精确版本而停下本机工作。最新[父子图审阅 HTML](../../artifacts/legacy129-subimage-20261123/analysis-units-review-20261124/review.html)展示整父图／子图建议、全拆后果与原代码。

## 采集版本校正

FT／Origin 随包原始响应的顶层 `version` 和 middle JSON 的 `_version_name` 都报告 **3.1.14**；P2T 原 ZIP 锁定的 **3.3.1** 是客户端本地依赖，不能据此认定采集服务也运行 3.3.1。此前据 3.3.1 直接解释 FT 采集行为的表述过强，以下补齐历史版本代码，并保留实际服务依赖待核这一层限制。

- 本机已有 `mineru==3.1.14` 解包源码：`/Users/yixuan/.cache/uv/archive-v0/5J2Zy-qYfcJFFpxZ/mineru/`；其元数据要求 `mineru-vl-utils>=0.2.7,<1`。
- 本机已有 0.2.7 wheel：`/private/tmp/mineru-vl-utils-0.2.7-caption-review.whl`，SHA-256 为 `561da456e438c1431e70523b6767d9e3a7961e1849e8473fae06e3556f5f3746`。只读 ZIP 内源码，没有安装。
- 3.1.14 的 `visual_magic_model_utils.py::absorb_image_block_members` 第 461–516 行同样只保存被吸收成员的 type 与相对 bbox。
- 0.2.7 的 `mineru_client.py::prepare_for_extract` 第 269–346 行同样跳过 `image_block` 本身（第 296 行）和覆盖率达到阈值的 `image/chart` 成员（第 284–288、316–320 行）。`two_step_extract` 第 938–957 行明确先做整页布局，再选区域做内容抽取；整页布局不等于对父图做过内容分析。
- **证据边界**：已核实 3.1.14 与 0.2.7 公开实现，以及 3.3.1/1.0.5 的同类机制；推理包未保存实际服务的 `mineru-vl-utils` 精确版本或源码哈希。因此它们支持空父图的工程解释，尚不能把采集服务实际经过的每个分支视为已验证。

## 待确认方案的准确含义

建议的正常路径是先从首轮布局选择分析单位：判为保留的一组分析整父图一次；判为独立图的只分析子图。没有提议默认把每个父图和它的全部子图都分析一遍。失败后是否改走另一种单位尚未确定，不能把双重分析当作已接受的请求预算。

整父图分析也不能简单等同于将父图再次上传 `/file_parse`：这个入口会再次做布局，可能再次生成 `image_block` 并跳过内容。1.0.5 已有 `extract_with_layout`／`aio_extract_with_layout`：给定 `image` 区域及 `image_analysis=true`，复用原生提示与后处理，返回含实际 `type/sub_type/content` 的结构，避免再布局。`content_extract(type="image")` 只返回字符串，不能作为 subtype 透传的完整接口。已确认 Python 能力存在；同一内网上游是否有可用入口待落地说明，当前父图响应仍然缺失。

## 版本与证据来源

P2T 原 ZIP 的 `pyproject.toml` 和 `uv.lock` 固定了 `mineru==3.3.1`、`mineru-vl-utils==1.0.5`。这两个包已经存在于本机 uv 解包缓存，不需要安装：

- `/Users/yixuan/.cache/uv/archive-v0/s-x4aZ_dPlgGkTri/mineru/version.py`：`__version__ = "3.3.1"`。
- `/Users/yixuan/.cache/uv/archive-v0/xjsu37LbubHSrRXw/mineru_vl_utils/version.py`：`__version__ = "1.0.5"`。
- `mineru/utils/visual_magic_model_utils.py` SHA-256：`ed3bdeed305b657e858a4783030af2e3d416d6d9aa159563d6fdf17044e0bc23`。
- `mineru_vl_utils/mineru_client.py` SHA-256：`2c0b6c433e2e0628cf062d56e4c1552d4a033beba61f54e652bf872b2b5a99ea`。
- `mineru/backend/vlm/vlm_analyze.py` SHA-256：`0fadf7a94ae702861b4a1fa7f42358c6687cfc63fbe322c004fb1d3248658390`。

本机参考仓库 `/Users/yixuan/Documents/OCR-Models/MinerU` 当前是 4.1.1，不能当作采集服务版本。下节详细行号来自上面两个 3.3.1/1.0.5 解包目录；采集版本的对应证据和限制见前文。

## 原生链路实际做了什么

1. `mineru/utils/visual_magic_model_utils.py::absorb_image_block_members`（约 477–532 行）把覆盖率至少 0.9 的 `image_body`／`chart_body` 视为 `image_block` 成员。成员从有效块列表中吸收，只保留相对 `bbox` 和 `type`，写到父块的 `sub_images`。`regroup_visual_blocks`（约 378–474 行）随后把父块整理成一个 `image`，父块保留 `sub_images`，而父体的 `sub_type` 和子块内容不会因为吸收自动生成。

2. `mineru_vl_utils/mineru_client.py::prepare_for_extract`（约 286–363 行）先删除被 `image`、`chart` 或 `image_block` 覆盖的内部 `image_caption`。它再计算被 `image_block` 覆盖的 `image`／`chart` 成员（约 301–305 行）。`skip_list` 明确包含 `image_block`（约 313 行）；若 `image_analysis` 关闭，还会把 `image` 和 `chart` 加入跳过列表（约 314–315 行）。实际裁图循环（约 328–336 行）因此不会为 `image_block` 本身，也不会为被它覆盖的子块，发起图片分析请求。只有独立的、尺寸合格的 `image`／`chart` 才进入裁图和分析。

3. `mineru/backend/vlm/vlm_analyze.py::doc_analyze`（约 478–482 行）只是把请求级 `image_analysis` 传给 VLM 客户端；原生代码没有“父图还是 sub_images”的补偿决策，也没有按文字比例、共用图注或网格结构拆／保。

4. `mineru_vl_utils/post_process/__init__.py::simple_process`（约 130–166 行）只对已经得到内容的 `image`／`chart` 结果解析 `class`、`sub_class`、描述和表格。`image_block` 不在图片分析类型集合中，因此不能从原生后处理得到父图 `sub_type`。

这条链路与 FT 回包的形态一致：父块有 `sub_images` 的布局和原图资产，但父体分析内容、父体 subtype 为空。它是已查公开版本对多图容器的显式处理行为；内网实际依赖尚需核验。若交付目标需要父图或子图内容，P2T 需要显式选择可用的分析入口并记录来源。

## 与 129 case 的对应证据

| case | 原始 FT 回包 | 这条原生规则能解释的现象 | 当前能证明什么 |
| --- | --- | --- | --- |
| `5-1双栏表格2.pdf` 第 2 页 Fig. 1（`bc_022`） | 一个空父 `image`，两个 `sub_images` | 父容器和成员均被原生准备阶段跳过 | 只能证明布局有两个子框；不能从原始回包证明父图 subtype 或完整流程关系 |
| 同文件第 4 页双柱图 | 空父图，两个 `sub_images` | 子框没有作为独立图表请求 | 现有真实裁图响应补回 10 个明示值，是“确实需要子图分析”的正例 |
| 同文件第 5 页 Fig. 6 | 空父图，七个 `sub_images` | 多格容器默认只保留父资产和相对框 | 现有 7 份子图响应可证明局部内容，但不能把“保留父图”说成没有分析需求 |
| `依爱消防_电气火灾监控系统_2.pdf` 第 1 页（`bc_062`） | 两个空父图，各有左右成员 | 两组成员随父容器一起跳过 | 原包全拆后 IoU 约 0.463–0.469，说明补偿拆半会损失原父框定位；不能据此说模型无法读线路图 |
| `依爱消防_电气火灾监控系统_5.pdf` 第 1 页（`bc_065`） | 一个空父图，左右两个成员 | 父图没有父体分析标签 | 裁图能读出两组文字，但 FT 与 Origin 的 `text_image` 标签是模型或适配输出问题，需分开记录 |
| `依爱消防_工程维修手册_44.pdf` 第 1 页（`bc_059`） | 四图父块为空 | 子图只有在 P2T 显式补请求后才有机会分析 | FT 补回“音量调节”文字，但该响应没有 `natural_image` subtype，属于 OCR／标签缺失组合问题 |
| `广东城规院_惠玩甘青_7.pdf` 第 1 页（`bc_078`） | 两组照片父块为空 | 原生只给容器与子框 | 四个裁图均为 `natural_image`，是独立无字照片保留的正例；描述不代替 subtype 证据 |

## 对保留父图的含义

“保留父图”只决定最后交付的资产和 bbox，不能自动等同于“跳过分析”。在 3.3.1 原生链路里，父图和被吸收成员默认都不分析；P2T 若只保留原父块，会保住图和印刷图注，但对父图能力没有内容证据。

因此需要区分两件事：

- **交付单位**：最终保留一个父图，还是拆成若干可归属子图。
- **分析单位**：分析父图、分析子图，或在没有请求的情况下记为证据不足。

若保留一个父图仍要验证 FT 能力，最少要让内网 P2T 对父图做一次明确的整图分析，并把 `parent_analysis` 与 `subimage_analysis` 分开记录；不能把某个面板的 `flowchart`／`text_image` 复制到父图。若决定只保留资产而不补请求，应在评分中记为“保留交付、分析证据缺失”，不能把空输出判成模型识别失败。

图表单开也遵循同一分离：P2T 上游请求可能仍带 `image_analysis=true`，但只有可确认的图表候选才可补推；未标明为图表的普通图片不能因图表开关获得图片描述。图表结果还必须经过 `chart_analysis` 过滤，不能把普通图片分析泄漏到图表成品。

## 当前结论与待确认项

- 已确认：已查 3.1.14/0.2.7 和 3.3.1/1.0.5 代码均包含多图容器跳过和成员吸收；没有补分析父／子图的自动选择策略。采集服务的实际 utils 版本及运行分支待核验。
- 已确认：P2T 的补偿缺口是分析单位和交付单位没有分开，原包“先全量裁图再按结果保留”的规则只能作为离线基线。
- 已确认：两个分析开关都关闭时，P2T 不应新增裁图、分析请求或改变原图片文字过滤；本机适配已把保留打印文字的参数限制在至少一个分析开关开启的路径。
- 尚未确定：判为“保留”的父图是否继续请求整图分析，还是只保留资产并把内容记为证据不足。这个选择会改变请求量、父图 subtype 证据和正式评分，需先由产品口径确认。

