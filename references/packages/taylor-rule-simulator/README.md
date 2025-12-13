# Taylor Rule Simulator（src/fomc 重构产物）

本 README 只描述 `src/fomc/` 下的重构结果，因为你将把该目录整体复制到主项目的 `references/` 里供后续集成参考。

## 目标
- 将泰勒规则及其变体的经济建模能力，以 **Python 可复用模块** 的形式整理出来。
- 先用模拟数据跑通公式、接口与可视化；等你在主项目集成时再接入真实数据库/快照。

## 目录（将被复制的部分）
- `src/fomc/rules/`：泰勒规则规则引擎（模型公式、参数预设、时间序列模拟、指标汇总）。
- `src/fomc/apps/`：轻量 Web 测试台（FastAPI + 内嵌 HTML/Chart.js + 本地静态资源）。
- `src/fomc/__init__.py`：包入口占位。

## 规则引擎
代码入口：`src/fomc/rules/taylor.py`

**核心数据结构**
- `ModelType`：模型枚举（`taylor/extended/rudebusch/mankiw/evans/stone`）。
- `TaylorRuleParams`：统一输入参数对象。
- `RatePoint`：时间序列单点（`date, taylor, fed, survey, adjusted`）。

**对外 API**
- `model_defaults(model: ModelType) -> TaylorRuleParams`：返回模型预设参数。
- `calculate_rate(params: TaylorRuleParams) -> float`：模型原始建议利率（泰勒规则/变体）。
- `calculate_adjusted_rate(taylor_rate, prev_fed_rate, rho) -> float`：政策惯性/平滑后的利率。
- `generate_time_series(params) -> list[RatePoint]`：月度模拟序列（placeholder，后续替换为真实数据）。
- `latest_metrics(params, series) -> dict`：最新泰勒利率/FED利率/利差等指标。

**参数字段**
`real_rate, core_inflation, target_inflation, alpha, nairu, unemployment_rate, beta, okun, prev_fed_rate, rho, survey_rate, output_gap, intercept, start_date, end_date, model`

### 快速试用（模拟数据）
```bash
PYTHONPATH=src python3 - <<'PY'
from fomc.rules import model_defaults, generate_time_series, latest_metrics, ModelType

params = model_defaults(ModelType.TAYLOR)
series = generate_time_series(params)
print(series[-1].as_dict())
print(latest_metrics(params, series))
PY
```

## Web 测试台
入口：`src/fomc/apps/sandbox.py`

**特点**
- 深色 Bloomberg 风格界面，用于快速验证规则引擎输出。
- 右侧两张 Chart.js 图：上方三条利率曲线（FED/Taylor/Survey），下方利差柱状图。
- 左侧显示关键利率卡片、公式（符号/数字/调整后分行）、Series JSON。
- 参数面板通过“参数设置”抽屉编辑。
- 不依赖外网 CDN：`chart.min.js` 已本地化并通过 `/static/` 提供。

### 启动
确保 FastAPI/uvicorn 已安装后运行：
```bash
PYTHONPATH=src uvicorn fomc.apps.sandbox:app --app-dir src --reload --port 8000
# 浏览器打开 http://localhost:8000
```

## 集成到主项目时的约定（参考用）
- 保持 `ModelType` 与 `TaylorRuleParams` 字段稳定，方便主项目 AI 直接对照迁移。
- 将 `generate_time_series` 的模拟趋势替换为真实数据读取（FRED/ALFRED/主项目快照），但 **输出结构保持不变**。
