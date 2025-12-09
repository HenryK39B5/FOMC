# FOMC 代码架构蓝图（基于 `src/` 的最终形态）

> 本文档定义 **联邦货币 LLM 委员会** 项目的最终代码架构，用于后续系统性重构与新功能开发。
>  目标是用统一骨架支撑三种模式：**美联储 101（学习）** / **历史会议模拟（流程）** / **工具箱（工具）**，并贯穿完整链路：
>  **数据 → 研报 → 规则模型 → 讨论 → 决议/纪要 → 复盘**。

------

## 1. 顶层设计：一个领域、一套骨架、三种入口

### 1.1 单一领域骨架

围绕「**FOMC 会议及其上下文**」构建单一领域骨架：

- **数据层（Data Layer）**
  - FRED / ALFRED 宏观时间序列
  - 月度宏观事件（macro events：新闻 → 事件 → 月报）
  - 会议数据快照（meeting snapshots）
- **建模 & 分析层（Models & Reports）**
  - 指标研报：NFP / CPI / PCE / 金融条件等
  - 规则模型：Taylor / Balanced / First-Difference 等
  - 场景与情景假设（不同路径的利率、通胀轨迹）
- **智能讨论层（Agents Layer）**
  - 多角色 Agent：鹰派、鸽派、中性、市场、学术等
  - 使用 RAG 管线 + 模板提示词 + 数据摘要作为上下文
- **体验编排层（Modes & Pipelines）**
  - 单一会议流程管线：
     `数据快照 → 研报 → 规则模型 → Agent 讨论 → Statement/Minutes 摘要 → 复盘`
  - 三种模式只是**同一骨架的不同入口和 UI 展示方式**：
    - 美联储 101：重点展示解释层和小组件
    - 历史会议模拟：完整跑一遍流程
    - 工具箱：在任意上下文中调用流程中的某一步（或若干步）

### 1.2 三种模式如何共享同一基础设施

- **美联储 101（学习模式）**
  - 使用真实数据和历史会议作为示例，但**只跑到“解释 +演示”层**。
  - 每个 101 章节对应若干「可执行小组件」，本质上是对 Data/Models/Reports 层某个函数的「包装视图」。
- **历史会议模拟（流程模式）**
  - 固定在某个 `meeting_id` 和 `snapshot_id` 上，将整个骨架串联跑完。
  - 每一步都可在右侧显示对应的 101 解释卡片。
- **工具箱（工具模式）**
  - 所有 Data/Reports/Models/Agents 的函数都可以被「工具模式」直接调用。
  - 若存在当前会议上下文，则默认继承 `meeting_id + snapshot_id`；否则在「无会议模式」下工作。

------

## 2. 仓库与目录规划（最终目标）

### 2.1 仓库根目录

```text
FOMC/
  pyproject.toml         # 或 setup.cfg，统一依赖与打包配置
  README.md
  .env.example           # 环境变量示例（DB / LLM / API KEY 等）
  .gitignore
  docs/
    PROJECT_COMPASS.md   # 项目指南针（现有）
    ARCHITECTURE.md      # 本文档
    API_DESIGN.md        # （后续由代码生成为主）
    DATA_MODEL.md        # 主要表结构与领域模型说明
  src/
    fomc/                # 项目唯一 Python 顶级包
      ...
  tests/
    ...
```

**强约束：所有 Python 代码统一放在 `src/` 下，由单一包 `fomc` 管理。**
 不再在仓库根或 `packages/` 下散落多个顶级包。

------

## 3. `src/fomc` 包整体结构

```text
src/
  fomc/
    __init__.py

    config/              # 配置与常量
      __init__.py
      settings.py        # 读取 .env / 默认路径 / 模式开关
      paths.py           # data/、cache/ 等路径集中管理

    infra/               # 外部基础设施 & 低层依赖
      __init__.py
      db.py              # SQLite 连接、会话管理
      migrations/        # 简单迁移脚本（可选手写）
      llm_client.py      # 与 OpenAI / DeepSeek 等 LLM 的统一封装
      http_client.py     # requests 封装
      logging.py         # 日志配置
      cache.py           # 轻量缓存（内存/文件）

    domain/              # 纯领域模型（无 IO）
      __init__.py
      types.py           # 通用类型定义（Alias / Enums / TypedDict）
      meetings.py        # Meeting, MeetingSnapshot, FomcDecision 等
      series.py          # IndicatorSeries, DataPoint, Vintage 等
      macro_events.py    # MacroEvent, MacroMonthSummary 等
      rules.py           # RuleInput, RuleResult（公共结构）
      discussion.py      # AgentMessage, DiscussionSummary 等

    data/                # 数据源、抓取、存储与统一查询 API
      __init__.py
      fred/              # FRED & ALFRED
        __init__.py
        client.py        # 调用 FRED API / 下载 CSV 等
        repository.py    # 读写 SQLite 表：series, observations, vintages
        snapshots.py     # 按 as-of 生成时间点数据快照
      macro_events/
        __init__.py
        pipeline.py      # DDGS + LLM：新闻→事件→月报
        repository.py    # months / events / raw_articles 表
        cli.py           # （内部）月度刷新脚本可调用入口
      snapshots/
        __init__.py
        repository.py    # MeetingSnapshotRepository：meeting_id→snapshot_id
        services.py      # 构建 / 更新 / 查询快照
      queries.py         # 提供统一查询接口（对外暴露）

    reports/             # 研报生成（纯业务逻辑 + 模板）
      __init__.py
      templates/         # Markdown / HTML 模板
        nfp.md.j2
        cpi.md.j2
        meeting_summary.md.j2
      indicators.py      # NFP / CPI / PCE / 金融条件研报
      macro_background.py# 调用 macro_events，生成“本月宏观背景”段落
      meeting_report.py  # 汇总：多个指标 + 规则 + 宏观事件 → 会议研报

    models/              # 规则模型与情景假设（无 IO）
      __init__.py
      taylor.py          # Taylor rule 及变体
      balanced.py        # Balanced approach
      first_difference.py# First-difference 规则
      scenarios.py       # 情景生成：不同路径假设

    agents/              # 多 Agent 讨论与 RAG
      __init__.py
      prompts/           # 模板文本（可拆文件或 JSON）
        base.md
        hawk.md
        dove.md
        market.md
        academic.md
      retrieval.py       # RAG 管线（从数据/报告中取材料）
      roles.py           # 预设角色定义与配置
      runner.py          # AgentRunner：驱动多个角色轮流发言
      summarizer.py      # DiscussionSummary 生成

    pipelines/           # 把 Data + Reports + Models + Agents 串成完整流程
      __init__.py
      meeting_pipeline.py# 历史会议模拟主流程
      toolbox_pipeline.py# 工具箱内部调用流程
      learning_pipeline.py# 美联储 101 中可执行小组件使用的简化流程

    modes/               # 面向「模式」的编排层（轻 UI 逻辑）
      __init__.py
      learning_101.py    # 管理章节结构、与 pipelines 的映射
      history_sim.py     # 管理会议日历、进度、状态
      toolbox_mode.py    # 管理工具箱入口与当前上下文

    apps/                # 对外接口层：CLI / API / Web
      __init__.py
      cli/
        __init__.py
        main.py          # `python -m fomc.apps.cli ...`
      api/
        __init__.py
        main.py          # FastAPI 应用，供前端/其他服务调用
        routers/
          meetings.py    # /meetings/...
          reports.py     # /reports/...
          toolbox.py     # /tools/...
      web/
        __init__.py
        server.py        # 简单 web 入口（可基于 FastAPI + Jinja）
        pages/
          home.py        # 主页：三模式入口
          meeting_flow.py# 历史会议模拟页面
          learning_101.py# 101 章节总览/详细
          toolbox.py     # 工具箱界面
        components/
          charts.py      # 通用图表封装
          layout.py      # 布局组件（Tabs, Sidebar 等）

    toolbox/             # 方便复用的工具级功能（对内 API，模式与 Web 调用）
      __init__.py
      data_browser.py    # 指标浏览、时序图
      report_generator.py# 指标/会议研报生成工具
      rule_runner.py     # 规则模型计算工具
      revision_compare.py# 修订对比（latest vs as-of）

    # 可选：局部工具（仅开发服务）
    devtools/
      __init__.py
      seed_data.py       # 初始化/模拟数据
      profiling.py       # 性能分析脚本
```

------

## 4. 关键领域模型（`fomc.domain`）

> 领域模型要尽量「干净」：只负责结构和基本校验，不做 IO，不直接调用 LLM 或数据库。

### 4.1 会议与快照

- `Meeting`
  - 字段：`id`, `meeting_date`, `label`, `notes` 等
- `MeetingSnapshot`
  - 字段：`id`, `meeting_id`, `as_of_date`, `fred_vintage_date`, `macro_month_key` 等
  - 保证「**当时可见数据**」版本通过这个对象固定下来。

### 4.2 时间序列与版本

- `IndicatorSeries`
  - 字段：`series_id`, `name`, `units`, `seasonal_adjustment`, `frequency` …
- `DataPoint`
  - 字段：`series_id`, `date`, `value`, `vintage_date`

### 4.3 宏观事件（macro events）

- `MacroEvent`
  - 字段：`id`, `event_date`, `title`, `shock_type`, `importance_score`, `summary`, `sources`（URL 列表或文本）
- `MacroMonthSummary`
  - 字段：`month_key (YYYY-MM)`, `events: List[MacroEvent]`, `monthly_summary_md`

### 4.4 规则模型与结果

- `RuleInput`
  - 包含：核心输入指标（通胀、产出缺口、政策利率等）
- `RuleResult`
  - 字段：`rule_name`, `recommended_rate`, `comment`, `assumptions`

### 4.5 讨论与决议

- `AgentMessage`
  - 字段：`role_name`, `content`, `turn_index`, `references`（引用哪些数据/图表/文档）
- `DiscussionSummary`
  - 字段：`key_points`, `areas_of_agreement`, `areas_of_disagreement`, `risk_factors`
- `FomcDecision`
  - 字段：`target_range`, `vote_result`, `rationale`, `link_to_statement`

------

## 5. 数据层设计（`fomc.data`）

### 5.1 SQLite 单库，多表

- 使用 **单一 SQLite 数据库文件**（例如 `data/fomc.db`），由 `infra.db` 提供连接与迁移工具。
- 表大类：
  - `fred_series`, `fred_observations`, `fred_vintages`
  - `macro_months`, `macro_events`, `macro_raw_articles`
  - `meetings`, `meeting_snapshots`

### 5.2 FRED & ALFRED（`fomc.data.fred`）

- `client.py`
  - 和 FRED API / 数据源交互，负责下载与缓存。
- `repository.py`
  - 写入/读取 `fred_series`, `fred_observations`, `fred_vintages`。
  - 暴露接口：
    - `get_series(series_id, *, as_of: date | None)`
    - `compare_vintages(series_id, asof_date1, asof_date2)`
- `snapshots.py`
  - 为给定 `meeting_id` / `as_of_date` 构建「可见数据快照」，生成 `snapshot_id` 并写入 `meeting_snapshots`。

### 5.3 宏观事件（`fomc.data.macro_events`）

- `pipeline.py`
  - 核心职责：
    - 使用 DDGS 或其他搜索源抓取当月高信号宏观新闻。([GitHub](https://github.com/HenryK39B5/macro_events))
    - 调用 `infra.llm_client` 进行甄别、聚合成事件，并生成月度 Markdown 月报。([GitHub](https://github.com/HenryK39B5/macro_events))
    - 写入 `macro_months`（包含 `monthly_summary_md`）与 `macro_events` 表。
  - 暴露函数：
    - `refresh_month(month_key: str, *, force: bool = False) -> MacroMonthSummary`
    - `get_month_summary(month_key: str) -> MacroMonthSummary | None`
- `repository.py`
  - 独立的 DB 读写逻辑，返回 `MacroEvent` / `MacroMonthSummary` 领域对象。

> 规则：**所有 NFP/CPI/会议研报，在生成前必须确保对应月份的宏观事件月报存在；若不存在则自动调用 `refresh_month`。**

### 5.4 会议快照（`fomc.data.snapshots`）

- `repository.py`：
  - 管理 `meeting_snapshots` 表：创建、更新、查询。
- `services.py`：
  - `build_snapshot_for_meeting(meeting_id: str, as_of: date)`：
     联合 FRED/ALFRED 与 macro_events 构建完整数据快照。
  - `get_snapshot(meeting_id: str, snapshot_id: str)`：
     返回结构化对象，供 pipelines 使用。

### 5.5 对外统一查询层（`fomc.data.queries`）

- 提供面向业务的高层 API，如：
  - `get_indicator_timeseries(series_id, *, snapshot: MeetingSnapshot | None)`
  - `get_macro_background_for_month(month_key)`

------

## 6. 研报生成层（`fomc.reports`）

### 6.1 模板管理

- `templates/` 使用 Jinja2 或简单字符串模板（Markdown 为主）。
- 模板分为：
  - 指标研报模板（NFP / CPI 等）
  - 「本月宏观背景」模板
  - 「会议整体研报」模板（组装多个部分）

### 6.2 指标研报（`indicators.py`）

- 典型接口：

```python
def generate_nfp_report(snapshot: MeetingSnapshot) -> str: ...
def generate_cpi_report(snapshot: MeetingSnapshot) -> str: ...
```

- 使用 `fomc.data.queries` 获取对应 series 在 snapshot 上的切片，生成 Markdown 文本。

### 6.3 宏观背景段落（`macro_background.py`）

- 强制依赖 `macro_events` 数据层：

```python
def generate_macro_background(month_key: str) -> str:
    """
    读取 MacroMonthSummary，渲染“本月宏观背景”章节。
    若数据缺失，由调用方确保预先 refresh。
    """
```

### 6.4 会议研报（`meeting_report.py`）

- 汇总接口：

```python
def generate_meeting_report(
    meeting: Meeting,
    snapshot: MeetingSnapshot,
    *,
    include_macro_background: bool = True,
) -> str:
    """
    将：
      - 核心指标研报（NFP/CPI/PCE/金融条件）
      - 宏观事件月报（macro background）
      - 规则模型输出（来自 models）
      - 若已有：Agent 讨论摘要
    拼装成一份完整会议研报（Markdown）。
    """
```

------

## 7. 规则模型层（`fomc.models`）

- 各规则模型（Taylor / Balanced / First-difference）应为**纯函数**，只依赖传入的 `RuleInput`，不直接访问数据库。

示例接口：

```python
def taylor_rule(input: RuleInput) -> RuleResult: ...
def balanced_approach(input: RuleInput) -> RuleResult: ...
def first_difference_rule(input: RuleInput) -> RuleResult: ...
```

- `scenarios.py` 提供：
  - 生成不同利率/通胀路径的情景；
  - 为工具箱和 Agent 提供情景分析。

------

## 8. Agent 层（`fomc.agents`）

- `prompts/`：存放模板文本（Markdown 或类似），根据不同角色加载。
- `roles.py`：预设角色配置（鹰派、鸽派、中性、市场、学术、主持人）。
- `retrieval.py`：
  - 将数据快照、研报、规则模型输出等转换成可检索文档；
  - 提供「会议上下文 → 上下文片段列表」的函数。
- `runner.py`：
  - 输入：`Meeting`, `MeetingSnapshot`, `MeetingReport`, `RuleResults`；
  - 驱动多个角色轮流发言，记录 `AgentMessage` 序列；
  - 输出：`DiscussionSummary` 与原始对话记录。
- `summarizer.py`：
  - 从 `AgentMessage` 序列中提取关键观点、分歧和风险，形成「讨论摘要」，供 `meeting_report.py` 收录。

------

## 9. 流程编排层（`fomc.pipelines`）

> 这里是「整体性」的核心：将所有模块在代码层串成清晰的流程。

### 9.1 历史会议流程（`meeting_pipeline.py`）

核心函数示例：

```python
def run_historical_meeting(meeting_id: str) -> dict:
    """
    完整跑通一次历史会议重放流程：
      1. 取得 Meeting 和最新/指定 snapshot；
      2. 确保 macro_events month 已刷新；
      3. 生成指标级研报 + 宏观背景；
      4. 调用规则模型输出政策建议区间；
      5. 运行多 Agent 讨论，得到讨论记录与摘要；
      6. 生成最终会议研报文本（含 101 侧栏引用位）；
      7. 返回结构化结果（供 API/Web 渲染）。
    """
```

输出可以包含：

- `meeting_report_md`
- `rule_results`
- `discussion_summary`
- `macro_month_summary`

### 9.2 工具箱流程（`toolbox_pipeline.py`）

- 为工具箱提供更细粒度的流水线，如：

```python
def run_indicator_report_tool(series_id: str, *, snapshot: MeetingSnapshot | None) -> dict: ...
def run_rule_model_tool(rule_name: str, *, snapshot: MeetingSnapshot | None) -> dict: ...
def run_revision_compare_tool(series_id: str, date1, date2) -> dict: ...
```

### 9.3 学习模式流程（`learning_pipeline.py`）

- 为 101 章节提供小组件接口，例如：

```python
def demo_taylor_rule_for_example_meeting() -> dict: ...
```

------

## 10. 模式编排层（`fomc.modes`）

> 这是「业务体验」层，保持轻逻辑，只调用 pipelines 与 toolbox。

- `learning_101.py`
  - 管理章节树（数据篇 / 规则篇 / 沟通篇）。
  - 每个章节映射到一个或多个 `learning_pipeline` 函数和 UI 组件。
- `history_sim.py`
  - 管理会议日历（按时间线列出会议，最新历史会议标记 NEW）。
  - 长期维护当前会话的 `meeting_id + snapshot_id`，并调用 `run_historical_meeting`。
- `toolbox_mode.py`
  - 维护当前上下文（可能有也可能没有会议）。
  - 提供给 Web/API 的统一入口来调用 toolbox 流程。

------

## 11. 应用层（`fomc.apps`）

### 11.1 CLI（`fomc.apps.cli`）

- 典型子命令：

```bash
python -m fomc.apps.cli init-db
python -m fomc.apps.cli refresh-macro 2024-08
python -m fomc.apps.cli run-meeting 2023-06-14
python -m fomc.apps.cli export-meeting-report 2023-06-14 --format pdf
```

- CLI 实际只是对 `data.*` 和 `pipelines.*` 的薄封装。

### 11.2 API（`fomc.apps.api`）

- 使用 FastAPI 构建：
  - `GET /meetings`：会议日历
  - `GET /meetings/{meeting_id}`：单次会议详情（含数据快照信息）
  - `POST /meetings/{meeting_id}/run`：触发历史会议流程
  - `GET /toolbox/indicator-report`、`GET /toolbox/revision-compare` 等工具接口

### 11.3 Web（`fomc.apps.web`）

- 前端可以先用简单的 Jinja 页面或前后端一体化框架实现，满足：
  - 主页：
    - CTA：**开始一场历史会议** / **进入美联储 101** / **打开工具箱**
  - 历史会议流程页：
    - 按步骤展示：数据快照 → 研报 → 规则模型 → 讨论 → 决议/纪要 → 复盘
    - 右侧固定 101 解释面板
  - 101 章节页：
    - 列表展示章节与对应的「流程中的位置」，支持一键跳转到会议页试用
  - 工具箱页：
    - 在有会议上下文时继承当前会议；否则允许用户自由选择参数。

------

## 12. 实现优先级（给后续编码用）

结合路线图，建议按以下顺序实现（每一步都严格遵守上面的模块边界）：

1. **数据基座 & 宏观事件**
   - 完成 `infra.db`、`fomc.data.fred`、`fomc.data.macro_events`、`fomc.data.snapshots` 的基本能力。
   - 能够创建 `Meeting` 与 `MeetingSnapshot`，并为给定月份生成宏观事件月报。
2. **指标研报 + 会议研报**
   - 实现 `fomc.reports.indicators` 与 `fomc.reports.macro_background`。
   - 实现 `generate_meeting_report`，至少支持 NFP / CPI + 宏观背景。
3. **规则模型层**
   - 在 `fomc.models` 中实现 Taylor / Balanced / First-difference 三类规则。
   - 将结果接入 `meeting_report.py`。
4. **历史会议流程 MVP**
   - 实现 `run_historical_meeting` 流程管线。
   - 提供基础 CLI 与简单 Web 页面启动该流程。
5. **美联储 101 & 工具箱 MVP**
   - 为数据篇/规则篇/沟通篇各实现 1 个 101 章节与对应小组件。
   - 实现工具箱的几个核心工具：数据浏览、研报生成、规则模型、修订对比。
6. **Agent 讨论 & 复盘**
   - 基于 `fomc.agents` 实现 4–5 个预设人格与主持人汇总；
   - 接入历史会议流程与会议研报；
   - 后续再扩展修订对比、会后误差分析（市场 vs 规则）。

------

> 本蓝图即为 FOMC 项目的「代码版指南针」：
>
> - 所有新功能都应落在上述模块树中的明确位置；
> - 三种模式（101 / 历史会议模拟 / 工具箱）共用同一骨架，只是在 UI 和入口上有所区别；
> - 重构现有 `data` 与 `macro_events` 代码时，以此结构为目标，一步步迁移。
