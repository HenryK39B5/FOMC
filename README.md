# FOMC Studio（联邦公开市场委员会 · 学习/模拟/工具）

[![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?style=flat-square&logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.110-009688?style=flat-square&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![Uvicorn](https://img.shields.io/badge/Uvicorn-0.27-222222?style=flat-square)](https://www.uvicorn.org/)
[![SQLAlchemy](https://img.shields.io/badge/SQLAlchemy-2.0-d71f00?style=flat-square&logo=sqlalchemy&logoColor=white)](https://www.sqlalchemy.org/)
[![SQLite](https://img.shields.io/badge/SQLite-003B57?style=flat-square&logo=sqlite&logoColor=white)](https://www.sqlite.org/)
[![Playwright](https://img.shields.io/badge/Playwright-1.49-45ba4b?style=flat-square&logo=playwright&logoColor=white)](https://playwright.dev/python/)

这个项目用同一套底层能力，提供三种入口，帮助用户理解并复现 FOMC 的决策骨架：

- **FOMC101（学习）**：文档式学习 + 可运行小组件（`/fed101`）
- **历史会议模拟（流程）**：按 `meeting_id` 重放会议窗口，生成并缓存材料（`/history`）
- **工具箱（工具）**：把研报、模型、数据浏览拆成独立工具随时调用（`/toolbox`）

愿景、体验骨架与路线图：`docs/PROJECT_COMPASS.md`  
技术实现说明（TechDocs）：`/techdocs`（内容在 `content/techdocs/`）

## 页面示例图（Screenshots）

### 主页
<img src="docs/assets/screenshots/homepage.png" alt="主页" width="900" />

### FOMC101
<img src="docs/assets/screenshots/fed101.png" alt="FOMC101" width="900" />

### 历史会议模拟
<img src="docs/assets/screenshots/history.png" alt="历史会议模拟" width="900" />

### 宏观事件数据（部分）
<img src="docs/assets/screenshots/macro_events.png" alt="宏观事件数据" width="900" />

### 宏观经济指标浏览器（部分）
<img src="docs/assets/screenshots/indicators.png" alt="宏观经济指标浏览器" width="900" />

### 非农就业研报（部分）
<img src="docs/assets/screenshots/nfp.png" alt="非农研报" width="900" />

### CPI 研报（部分）
<img src="docs/assets/screenshots/cpi.png" alt="CPI 研报" width="900" />

### 规则模型
<img src="docs/assets/screenshots/rules.png" alt="规则模型" width="900" />

## 你能做什么

- **FOMC101**：按“研究方法论”读懂数据/研报/规则/沟通，并能在同一页跑小组件验证
- **历史会议模拟**：生成/缓存会议材料（宏观事件、NFP、CPI、规则模型、讨论、决议/沟通）并复盘
- **工具箱**：指标库同步与浏览、宏观事件月报、NFP/CPI 研报生成、Taylor 规则建模

## 快速开始

```bash
# 1) 安装依赖（建议虚拟环境）
pip install -r requirements.txt

# 2) 以可编辑方式安装包（让 src/fomc 可被导入）
pip install -e .

# 3) 初始化指标数据库（首次运行）
python -m fomc.apps.cli.init_database

# 4) 同步指标数据（需要 FRED_API_KEY）
python -m fomc.apps.cli.process_all_indicators --start-date 2010-01-01

# 5) 启动 Web 门户（http://127.0.0.1:9000）
uvicorn fomc.apps.web.main:app --app-dir src --reload --port 9000
```

## 环境变量（.env）

在仓库根目录创建 `.env`：

- `FRED_API_KEY`：同步经济指标所需（没有它也能启动门户，但图表/模型可能无数据）
- `DEEPSEEK_API_KEY`：使用 LLM 能力所需（宏观事件摘要、会议讨论/投票、Statement/Minutes 生成等）

LLM 相关可选配置：`DEEPSEEK_BASE_URL`、`DEEPSEEK_MODEL`、`DEEPSEEK_TIMEOUT`、`DEEPSEEK_RETRIES`（见 `src/fomc/infra/llm.py`）。

## 数据与缓存落点

- 指标数据库：`data/fomc_data.db`（见 `src/fomc/config/paths.py`）
- 宏观事件库：`data/macro_events.db`
- 历史会议产物缓存：`data/meeting_runs/<meeting_id>/`
  - 读写封装：`src/fomc/data/meetings/run_store.py`
  - 典型产物：宏观摘要、NFP/CPI 研报、规则模型结果、讨论过程、Statement/Minutes 生成稿等

## 仓库结构（当前实现）

- `src/fomc/apps/web/`：FastAPI + Jinja 门户（页面路由、模板、静态资源）
- `src/fomc/apps/web/backend.py`：门户集成层（把数据/研报/模型/LLM 串起来）
- `src/fomc/data/`：指标库、宏观事件、会议日历与落盘缓存
- `src/fomc/reports/`：研报生成（NFP/CPI）
- `src/fomc/rules/`、`src/fomc/data/modeling/`：规则模型（Taylor 系列）
- `content/fed101/`：FOMC101 内容（Markdown + `fomc-cell`）
- `content/techdocs/`：技术文档内容（Markdown）
- `docs/`：项目指南针与开发蓝图（含目标架构：`docs/development.md`）

## 导航入口（启动后）

- 主页：`http://127.0.0.1:9000/`
- FOMC101：`http://127.0.0.1:9000/fed101`
- 历史会议模拟：`http://127.0.0.1:9000/history`
- 工具箱：`http://127.0.0.1:9000/toolbox`
- 技术文档：`http://127.0.0.1:9000/techdocs`

---

## 后续优化计划（聚焦功能调优，暂不做框架迁移）

当前版本的主要功能链路已跑通。后续迭代将优先聚焦“LLM 可控性/可调参性、宏观事件检索质量、研报 prompt 可维护性”，并**暂不推进 Flask → FastAPI 迁移**（迁移属于结构统一工作，短期对输出质量提升有限且引入回归风险）。

当前进度（滚动更新）：
- 宏观事件模块：已完成优化。
- FOMC101 内容优化：进行中。
- LLM 模块与研报撰写模块优化：已完成阶段性调整（Prompt 外置与可观测、宏观月报接入、工具箱刷新、研报多智能体流水线）。


### 1) Macro Events Module（检索质量）

目标：提升事件召回的相关性与信噪比，减少重复事件，提升“月报/会议窗口摘要”的可靠性。

- **Query 扩展**：按 `report_type` 定制查询集合；对同主题使用多种等价表述（inflation/jobs/financial conditions 等）。
- **Source 策略**：
  - 引入**硬白名单**（如 Reuters/FT/WSJ/Bloomberg 等）作为高权重来源；
  - 同时保留非白名单来源作为补充召回，但在打分/排序中显式降权。
- **二阶段检索**：先宽召回（固定 query 多轮次检索）→ LLM 汇总当月关键事件并产出关键词/同义词 → 事件级精搜，提升定向召回。
- **排序与过滤**：将“来源可信度 + 多源交叉验证 + 内容相关性 + 事件冲击类型”纳入重要度评分，并与现有 LLM 二次重排结合；无日期结果直接剔除，确保月份切片严格。
- **聚类优化**：升级为 LLM 驱动的“标题/摘要相似度聚类”，不再按日期聚类；先做轻量候选分桶，再由 LLM 合并事件簇，设置输入上限与二次合并护栏。

### 2) LLM Module（已完成的调优）

目标：让 prompt/参数/输出更可控、更稳定、更便于对比迭代。

- **Prompt 轻量标记与可追溯**：关键 prompt 采用 frontmatter 标记 `prompt_id/prompt_version`，并随产物记录模型与参数。
- **Prompt 可观测性**：生成时落盘 `data/prompt_runs/`，记录 system/user prompt 与多智能体输出，便于对比与复盘。


### 3) Report Module（已完成的调优）

目标：让你可以快速调整研报 prompt（学习券商研究报告写法后自行迭代），同时保持输出格式稳定。

- **券商研报风格基准**：以“结论先行、驱动拆解、风险提示”作为统一写作框架，输出 Markdown 但保持券商语气。
- **Prompt 外置与热更新**：NFP/CPI/宏观月报的 prompt 模板统一放在 `content/prompts/reports/`，代码只负责加载与注入结构化数据。
- **输入数据块标准化**：继续使用结构化指标摘要（如 `IndicatorSummary`）与贡献拆分文本，确保“缺失就声明缺失、禁止编造”。
- **多智能体（Multi-Agent）研报流程**：已落地 Draft → Consistency → Completeness → Logic → Editor，并将每步输出落盘到 `data/prompt_runs/`。

### 4) FOMC101 内容优化（学习路径与可交互性）

目标：让 FOMC101 成为可学习、可参考、可复盘的内容体系，可执行 cell 作为加分项用于验证与延展。

- **架构重排**：按“制度底座 → 会议机制 → 研究流程 → 数据阅读 → Studio 搭建思路 → 案例复盘 → 资料引用”重组。
- **语气改为研究笔记式**：去掉命令式/教育式表述，强调观察、假设、方法与复盘。
- **多章短文档**：每章控制在 2–6 屏阅读量，便于维护与迭代。

### 5) 数据管理与可维护性（会议材料与全局数据）

目标：让“某次会议（meeting_id）的材料/产物”以及全局数据库的**增删查改**更顺畅、更可追溯、更易维护；减少“缓存混乱/重复生成/难以清理”的成本。

- **会议材料（meeting_runs）CRUD 与一致性**：
  - 为每个 `meeting_id` 明确支持：创建/读取/刷新（rebuild）/删除（清理）/导出（打包下载）的完整闭环。
  - 强化 `manifest.json`：记录每个 artifact 的 `kind/path/updated_at/meta`，并补充 `source_hash`（输入数据与 prompt/参数的哈希），便于判断“是否需要重跑”。
  - 统一命名与状态：为每类材料定义固定 `kind` 集合与生成状态（missing/cached/stale/running/failed），页面与 API 以同一套状态展示。
- **全局数据库（指标库/宏观事件库）治理**：
  - 引入 schema 迁移工具（如 Alembic）与版本号，避免“本地 DB 结构漂移”导致不可复现。
  - 为关键查询补索引与健康检查（数据缺口、最近更新时间、异常值），并在工具箱提供可视化诊断。
  - 明确数据生命周期：缓存保留策略、定期清理策略、备份/恢复流程（尤其是 `data/` 下的多个 SQLite 文件）。
- **可追溯与可审计**：
  - 对 LLM 生成产物保存最小必要的“生成证据”：使用的 prompt 版本/参数、引用的输入块、缺失声明与错误信息（避免仅保存最终文本）。
  - （可选）提供 `run_id` 概念：允许同一 `meeting_id` 下保存多次运行结果用于对比，而不是覆盖写入。

### 非目标（本阶段不做）

- 不做 Electron/Flutter 桌面化与多端重写。
- 不做后端高并发/分布式架构。
- 暂不做 Flask → FastAPI 迁移（除非后续确有统一入口/维护成本需要）。
