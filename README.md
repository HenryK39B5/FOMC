# FOMC Studio（联邦公开市场委员会 · 学习/模拟/工具）

这个项目用同一套底层能力，提供三种入口，帮助用户理解并复现 FOMC 的决策骨架：

- **美联储 101（学习）**：文档式学习 + 可运行小组件（`/fed101`）
- **历史会议模拟（流程）**：按 `meeting_id` 重放会议窗口，生成并缓存材料（`/history`）
- **工具箱（工具）**：把研报、模型、数据浏览拆成独立工具随时调用（`/toolbox`）

愿景、体验骨架与路线图：`docs/PROJECT_COMPASS.md`  
技术实现说明（TechDocs）：`/techdocs`（内容在 `content/techdocs/`）

## 页面示例图（Screenshots）

### 主页
<img src="docs/assets/screenshots/homepage.png" alt="主页" width="900" />

### 美联储101
<img src="docs/assets/screenshots/fed101.png" alt="Fed101" width="900" />

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

- **Fed101**：按“研究方法论”读懂数据/研报/规则/沟通，并能在同一页跑小组件验证
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
- `content/fed101/`：Fed101 内容（Markdown + `fomc-cell`）
- `content/techdocs/`：技术文档内容（Markdown）
- `docs/`：项目指南针与开发蓝图（含目标架构：`docs/development.md`）

## 导航入口（启动后）

- 主页：`http://127.0.0.1:9000/`
- 美联储 101：`http://127.0.0.1:9000/fed101`
- 历史会议模拟：`http://127.0.0.1:9000/history`
- 工具箱：`http://127.0.0.1:9000/toolbox`
- 技术文档：`http://127.0.0.1:9000/techdocs`

## 可选：研报 PDF 导出

项目包含 PDF 导出依赖（Playwright）。如需使用，通常还需要安装浏览器运行时（按 Playwright 官方方式安装）。
