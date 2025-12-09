# 联邦货币 LLM 委员会（FOMC）项目

以“工具 + 教学 + 沉浸式流程”帮助用户理解美联储货币政策决策。愿景、交互骨架与路线图详见 `docs/PROJECT_COMPASS.md`。

## 仓库结构（重构版）
- `docs/`：项目指南针与开发蓝图。
- `src/fomc/`：统一代码包  
  - `config/`：路径与 .env 加载  
  - `infra/`：数据库引擎  
  - `data/`：指标抓取/图表、宏观事件流水线与数据库模型  
  - `reports/`：LLM 研报生成（非农/CPI）  
  - `apps/`：统一 Web 门户（FastAPI + 内嵌 Flask 报告服务）、CLI 脚本  
- `data/`：运行期 SQLite 文件（`fomc_data.db`、`macro_events.db`）。
- `references/`：旧版子项目代码，仅供参考，不参与运行。

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

## 近期计划
- 接入规则模型与会议流程，扩展门户的占位功能。
- 将宏观事件、研报、规则结果统一串联为会议快照。

## 运行与数据管理说明
- 环境变量：在仓库根创建 `.env`，至少包含 `FRED_API_KEY`，可选 `DEEPSEEK_API_KEY`。  
- 数据库：默认路径 `data/fomc_data.db`（指标/研报）和 `data/macro_events.db`（宏观事件），`fomc.config.paths` 统一管理。  
- CLI：`python -m fomc.apps.cli.init_database` 创建表；`python -m fomc.apps.cli.process_all_indicators` 同步指标；宏观事件可通过 Web 入口触发刷新。  
- Web：推荐 `uvicorn fomc.apps.web.main:app --app-dir src --reload --port 9000`；如不开 reloader 可去掉 `--reload`。
