# 联邦货币 LLM 委员会（FOMC）项目

以“工具 + 教学 + 沉浸式流程”帮助用户理解美联储货币政策决策。愿景、交互骨架与路线图详见 `docs/PROJECT_COMPASS.md`。

## 仓库结构
- `docs/`：项目指南针与开发蓝图。
- `src/fomc/`：统一代码包（保持单一顶级包便于安装/导入）  
  - `config/`：路径与 .env 加载  
  - `infra/`：数据库引擎、统一 LLM 客户端  
  - `data/`：指标抓取/图表、宏观事件流水线与数据库模型  
  - `reports/`：LLM 研报生成（非农/CPI）  
  - `apps/`：统一 Web 门户（FastAPI + 内嵌 Flask 报告服务）、CLI 脚本  
- `data/`：运行期 SQLite 文件（`data/fomc_data.db`、`data/macro_events.db`）。
- `references/`：旧版子项目代码，仅供参考，不参与运行。

## 功能概览
- Web 门户（`/toolbox`）：宏观事件、经济数据浏览/数据库管理、非农研报、CPI 研报、政策规则（泰勒规则等）。
- 历史会议模拟（`/history`）：按会议时间线生成/缓存会议材料（宏观事件、NFP、CPI、Taylor），并可运行 LLM 委员讨论→投票→生成 Statement/Minutes。
- 数据层：FRED 指标库 + 宏观事件库（SQLite），支持增量同步与浏览。
- 研报层：基于指标与图表生成研报文本，并可导出 PDF（如安装 Playwright）。

## 快速使用
```bash
# 1) 安装依赖（建议虚拟环境）
pip install -r requirements.txt
# 2) 以可编辑方式安装包，注册 src/fomc 为可导入模块
pip install -e .
# 3) 初始化/更新数据库（FRED API 需配置 FRED_API_KEY）
python -m fomc.apps.cli.init_database
python -m fomc.apps.cli.process_all_indicators --start-date 2010-01-01
# 4) 启动统一门户（http://localhost:9000）
uvicorn fomc.apps.web.main:app --app-dir src --reload --port 9000
```

## 运行与数据管理说明
- 环境变量：在仓库根创建 `.env`，至少包含 `FRED_API_KEY`，可选 `DEEPSEEK_API_KEY`。  
- 数据库：默认路径 `data/fomc_data.db`（指标/研报）和 `data/macro_events.db`（宏观事件），`fomc.config.paths` 统一管理并在缺失时自动创建目录。  
- CLI：`python -m fomc.apps.cli.init_database` 创建表；`python -m fomc.apps.cli.process_all_indicators` 同步指标；宏观事件可通过 Web 入口触发刷新。  
- 工具箱：可在「经济数据」中执行同步/单指标刷新/健康检查；在「政策规则」中计算利率规则模型并可调节平滑系数 ρ。  
- 历史会议模拟：会议级材料与产物会落盘到 `data/meeting_runs/<meeting_id>/`（含 `manifest.json` 与各类 `.md` 工件），便于复现与缓存命中。
- Web：推荐 `uvicorn fomc.apps.web.main:app --app-dir src --reload --port 9000`；如不开 reloader 可去掉 `--reload`。

## 下一阶段：美联储 101（学习模式）
- 目标：把“数据/研报/规则模型/沟通材料”的关键概念做成短章节 + 可执行小组件，并与历史会议流程互链（在流程页可随时打开解释卡）。
- 状态：入口已预留（Web 顶部导航显示“美联储 101（待上线）”），下一阶段将补齐页面、章节结构与组件化解释内容。
