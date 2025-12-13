from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any, Dict

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, validator

from fomc.rules import (
    DEFAULT_PARAMS,
    ModelType,
    TaylorRuleParams,
    calculate_adjusted_rate,
    calculate_rate,
    generate_time_series,
    latest_metrics,
    model_defaults,
)


class TaylorPayload(BaseModel):
    """Request body for rate preview."""

    model: ModelType = ModelType.TAYLOR
    real_rate: float = Field(DEFAULT_PARAMS.real_rate)
    core_inflation: float = Field(DEFAULT_PARAMS.core_inflation)
    target_inflation: float = Field(DEFAULT_PARAMS.target_inflation)
    alpha: float = Field(DEFAULT_PARAMS.alpha)
    nairu: float = Field(DEFAULT_PARAMS.nairu)
    unemployment_rate: float = Field(DEFAULT_PARAMS.unemployment_rate)
    beta: float = Field(DEFAULT_PARAMS.beta)
    okun: float = Field(DEFAULT_PARAMS.okun)
    output_gap: float = Field(DEFAULT_PARAMS.output_gap)
    intercept: float = Field(DEFAULT_PARAMS.intercept)
    prev_fed_rate: float = Field(DEFAULT_PARAMS.prev_fed_rate)
    rho: float = Field(DEFAULT_PARAMS.rho, ge=0.0, le=1.0)
    survey_rate: float = Field(DEFAULT_PARAMS.survey_rate)
    start_date: date | None = None
    end_date: date | None = None

    @validator("model", pre=True)
    def _normalize_model(cls, value: Any) -> ModelType:
        if isinstance(value, ModelType):
            return value
        try:
            return ModelType(str(value))
        except Exception as exc:
            raise ValueError(f"Invalid model: {value}") from exc


def _build_params(payload: TaylorPayload) -> TaylorRuleParams:
    return TaylorRuleParams(
        model=payload.model,
        real_rate=payload.real_rate,
        core_inflation=payload.core_inflation,
        target_inflation=payload.target_inflation,
        alpha=payload.alpha,
        nairu=payload.nairu,
        unemployment_rate=payload.unemployment_rate,
        beta=payload.beta,
        okun=payload.okun,
        output_gap=payload.output_gap,
        intercept=payload.intercept,
        prev_fed_rate=payload.prev_fed_rate,
        rho=payload.rho,
        survey_rate=payload.survey_rate,
        start_date=payload.start_date or DEFAULT_PARAMS.start_date,
        end_date=payload.end_date or DEFAULT_PARAMS.end_date,
    )


app = FastAPI(
    title="Taylor Rule Sandbox",
    description="Lightweight UI and API to exercise the Taylor rule engine with simulated data.",
    version="0.1.0",
)

# Serve local static files (echarts)
app.mount("/static", StaticFiles(directory=Path(__file__).parent), name="static")


@app.get("/", response_class=HTMLResponse)
def sandbox_page() -> str:
    return HTML


@app.get("/api/defaults")
def get_defaults(model: ModelType = ModelType.TAYLOR) -> Dict[str, Any]:
    params = model_defaults(model)
    return {
        "model": params.model.value,
        "real_rate": params.real_rate,
        "core_inflation": params.core_inflation,
        "target_inflation": params.target_inflation,
        "alpha": params.alpha,
        "nairu": params.nairu,
        "unemployment_rate": params.unemployment_rate,
        "beta": params.beta,
        "okun": params.okun,
        "output_gap": params.output_gap,
        "intercept": params.intercept,
        "prev_fed_rate": params.prev_fed_rate,
        "rho": params.rho,
        "survey_rate": params.survey_rate,
        "start_date": params.start_date.isoformat(),
        "end_date": params.end_date.isoformat(),
    }


@app.post("/api/preview")
def preview_rates(payload: TaylorPayload) -> Dict[str, Any]:
    try:
        params = _build_params(payload)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    series = generate_time_series(params)
    metrics = latest_metrics(params, series)
    base_rate = calculate_rate(params)
    adjusted_rate = calculate_adjusted_rate(base_rate, params.prev_fed_rate, params.rho)

    return {
        "model": params.model.value,
        "inputs": payload.dict(),
        "taylor_rate": base_rate,
        "adjusted_rate": adjusted_rate,
        "metrics": metrics,
        "series": [point.as_dict() for point in series],
    }


HTML = '''
<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <meta http-equiv="Cache-Control" content="no-cache, no-store, must-revalidate" />
  <meta http-equiv="Pragma" content="no-cache" />
  <meta http-equiv="Expires" content="0" />
  <title>泰勒规则模拟器 | Taylor Rule Simulator</title>
  <script src="/static/chart.min.js?v=1"></script>
  <style>
    :root { color-scheme: dark; }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'Roboto', 'Oxygen', 'Ubuntu', 'Cantarell', 'Fira Sans', 'Droid Sans', 'Helvetica Neue', sans-serif;
      background: #0f0f0f;
      color: #ffffff;
      -webkit-font-smoothing: antialiased;
      -moz-osx-font-smoothing: grayscale;
    }
    header {
      padding: 16px 32px 12px;
      background: #0f0f0f;
      border-bottom: 1px solid #222;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 16px;
    }
    .title-wrap { display: flex; align-items: center; gap: 12px; }
    .title-icon { font-size: 22px; }
    .title-text { display: flex; flex-direction: column; }
    .title { font-size: 22px; font-weight: 800; }
    .subtitle { font-size: 13px; color: #cbd5e1; margin-top: 2px; }
    .controls { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }
    .version { color: #cbd5e1; font-size: 12px; }
    .selector { position: relative; }
    .selector select {
      appearance: none;
      background: #0f0f0f;
      color: #e2e8f0;
      padding: 10px 14px;
      border: 1px solid #444;
      border-radius: 10px;
      font-weight: 700;
      padding-right: 32px;
      cursor: pointer;
    }
    .selector::after {
      content: '▾';
      position: absolute;
      right: 12px;
      top: 50%;
      transform: translateY(-50%);
      color: #cbd5e1;
      pointer-events: none;
      font-size: 12px;
    }
    .ghost-btn { background: transparent; color: #e2e8f0; border: 1px solid #444; border-radius: 10px; padding: 10px 14px; cursor: pointer; font-weight: 700; }
    .layout {
      display: grid;
      grid-template-columns: 360px 1fr;
      gap: 0;
      padding: 0;
      height: calc(100vh - 90px);
      overflow: hidden;
    }
    .panel { background: #0f0f0f; border: none; color: #e2e8f0; }
    .left-panel {
      padding: 24px 24px 16px 32px;
      border-right: 1px solid #222;
      display: flex;
      flex-direction: column;
      gap: 18px;
      overflow-y: auto;
    }
    .left-section {
      border-top: 1px solid #222;
      padding-top: 14px;
      margin-top: 6px;
    }
    .rate-block { padding: 6px 12px 6px 12px; border-left: 6px solid #FF6B35; }
    .rate-block.blue { border-color: #4A90E2; }
    .rate-block.green { border-color: #2ECC71; }
    .rate-block.red { border-color: #FF6B6B; }
    .rate-label { font-size: 13px; color: #cbd5e1; margin-bottom: 4px; }
    .rate-value { font-size: 38px; font-weight: 800; line-height: 1; }
    .chart-panel {
      padding: 16px 32px 0 24px;
      display: flex;
      flex-direction: column;
      gap: 12px;
      overflow-y: auto;
    }
    .chart-stack {
      width: 100%;
      background: #111;
      display: flex;
      flex-direction: column;
      height: 100%;
      min-height: 640px;
    }
    .chart-box { position: relative; width: 100%; }
    #line-box { flex: 7 1 0; min-height: 420px; }
    #spread-box { flex: 3 1 0; min-height: 220px; border-top: 1px solid #222; }
    .chart-box canvas { width: 100% !important; height: 100% !important; display: block; background: #111; }
    .chart-title { font-size: 13px; color: #e2e8f0; font-weight: 600; display: flex; align-items: center; gap: 8px; }
    .legend-pill { display: inline-flex; align-items: center; gap: 6px; padding: 4px 8px; background: #1c1c1c; border: 1px solid #2a2a2a; border-radius: 999px; font-size: 12px; color: #e2e8f0; }
    .legend-dot { width: 10px; height: 10px; border-radius: 50%; display: inline-block; }
    .formula-panel { padding: 0; background: transparent; position: relative; z-index: 5; }
    .formula-title { font-size: 18px; font-weight: 800; color: #FF6B35; margin-bottom: 10px; }
    .formula-body { font-size: 18px; line-height: 1.6; color: #e2e8f0; display: flex; flex-wrap: wrap; gap: 6px; align-items: center; }
    .formula-var { color: #e2e8f0; font-weight: 700; }
    .formula-number { background: #FF6B35; color: #0f0f0f; padding: 4px 8px; border-radius: 6px; font-weight: 800; }
    .formula-highlight { color: #59a9ff; font-weight: 800; }
    .series-panel { padding: 0; background: transparent; position: relative; z-index: 5; }
    pre { background: #0f0f0f; border: 1px solid #222; border-radius: 8px; padding: 12px; overflow: auto; color: #cbd5e1; font-size: 12px; }
    .drawer { position: fixed; inset: 0; background: rgba(0,0,0,0.6); display: none; align-items: center; justify-content: center; z-index: 20; }
    .drawer.show { display: flex; }
    .drawer-content { width: min(90vw, 520px); max-height: 90vh; background: #0f0f0f; border: 1px solid #333; border-radius: 16px; padding: 18px 18px 12px; overflow: auto; box-shadow: 0 20px 60px rgba(0,0,0,0.4); }
    .drawer-header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 10px; }
    .close-btn { background: #1f2937; color: #e2e8f0; border: 1px solid #333; border-radius: 8px; padding: 6px 10px; cursor: pointer; font-weight: 700; }
    form label { display: block; margin-bottom: 4px; font-size: 13px; color: #b0b0b0; }
    form input, form select { width: 100%; padding: 10px 12px; margin-bottom: 10px; background: #1b1b1b; border: 1px solid #333; color: #ffffff; border-radius: 8px; font-size: 14px; outline: none; }
    form input:focus, form select:focus { border-color: #FF6B35; box-shadow: 0 0 0 2px rgba(255, 107, 53, 0.2); }
    .orange-highlight { background: #FF6B35; color: #0f0f0f; font-weight: 700; }
    .primary-btn { width: 100%; padding: 12px; background: linear-gradient(135deg, #FF6B35, #fb923c); border: none; color: #0b1223; font-weight: 800; border-radius: 10px; cursor: pointer; font-size: 15px; }
    .primary-btn:disabled { opacity: 0.65; cursor: not-allowed; }
  </style>
</head>
<body>
  <header>
    <div class="title-wrap">
      <div class="title-icon">🏦</div>
      <div class="title-text">
        <div class="title">泰勒规则模拟器 <span id="ui-version" style="font-size:12px;color:#94a3b8;font-weight:600;margin-left:6px;"></span></div>
        <div class="subtitle">Taylor Rule Simulator - Interactive Federal Funds Rate Calculator</div>
      </div>
    </div>
    <div class="controls">
      <div class="version">基于布隆伯格 Bloomberg 模型 | Version 1.0</div>
      <div class="selector">
        <select id="model-select">
          <option value="taylor">标准泰勒规则模型</option>
          <option value="extended">扩展泰勒规则</option>
          <option value="rudebusch">Rudebusch</option>
          <option value="mankiw">Mankiw</option>
          <option value="evans">Evans</option>
          <option value="stone">Stone &amp; McCarthy</option>
        </select>
      </div>
      <button id="open-drawer" class="ghost-btn">参数设置</button>
    </div>
  </header>

  <main class="layout">
    <section class="panel left-panel">
      <div class="rate-block" id="rate-taylor">
        <div class="rate-label">模型预测利率</div>
        <div class="rate-value" id="taylor-rate">--</div>
      </div>
      <div class="rate-block blue" id="rate-adjusted">
        <div class="rate-label">调整利率</div>
        <div class="rate-value" id="adjusted-rate">--</div>
      </div>
      <div class="rate-block green" id="rate-fed">
        <div class="rate-label">FED利率</div>
        <div class="rate-value" id="fed-rate">--</div>
      </div>
      <div class="rate-block red" id="rate-spread">
        <div class="rate-label">利差</div>
        <div class="rate-value" id="spread-rate">--</div>
      </div>

      <div class="left-section formula-panel">
        <div id="formula-title" class="formula-title">标准泰勒规则</div>
        <div id="formula-body" class="formula-body"></div>
      </div>

      <div class="left-section series-panel">
        <h3 style="margin: 0 0 8px;">Series (前 24 条)</h3>
        <pre id="series-json">{ }</pre>
      </div>
    </section>

    <section class="panel chart-panel">
      <div class="chart-title">
        泰勒规则模拟 - Taylor Rule Simulator
        <span class="legend-pill"><span class="legend-dot" style="background:#4A90E2;"></span> FED利率</span>
        <span class="legend-pill"><span class="legend-dot" style="background:#FFB347;"></span> 泰勒规则预测</span>
        <span class="legend-pill"><span class="legend-dot" style="background:#F5A623;"></span> 经济学家调查</span>
        <span class="legend-pill"><span class="legend-dot" style="background:#FF6B35;"></span> 利差</span>
      </div>
      <div class="chart-stack">
        <div class="chart-box" id="line-box"><canvas id="line-chart"></canvas></div>
        <div class="chart-box" id="spread-box"><canvas id="spread-chart"></canvas></div>
      </div>
    </section>
  </main>

  <div class="drawer" id="drawer">
    <div class="drawer-content">
      <div class="drawer-header">
        <div style="font-weight:800;font-size:16px;">参数设置</div>
        <button id="close-drawer" class="close-btn">关闭</button>
      </div>
      <form id="param-form">
        <label>实际利率 real_rate</label>
        <input name="real_rate" type="number" step="0.01" />
        <label>核心PCE core_inflation</label>
        <input name="core_inflation" type="number" step="0.01" />
        <label>通胀目标 target_inflation</label>
        <input name="target_inflation" type="number" step="0.01" />
        <label>Alpha 通胀缺口 alpha</label>
        <input name="alpha" type="number" step="0.01" class="orange-highlight" />
        <label>NAIRU nairu</label>
        <input name="nairu" type="number" step="0.01" />
        <label>失业率 unemployment_rate</label>
        <input name="unemployment_rate" type="number" step="0.01" class="orange-highlight" />
        <label>Beta 失业/产出 beta</label>
        <input name="beta" type="number" step="0.01" class="orange-highlight" />
        <label>Okun 系数 okun</label>
        <input name="okun" type="number" step="0.01" class="orange-highlight" />
        <label>产出缺口 output_gap</label>
        <input name="output_gap" type="number" step="0.01" />
        <label>截距 intercept</label>
        <input name="intercept" type="number" step="0.01" />
        <label>先前 FED 利率 prev_fed_rate</label>
        <input name="prev_fed_rate" type="number" step="0.01" class="orange-highlight" />
        <label>Rho 政策惯性 rho (0-1)</label>
        <input name="rho" type="number" min="0" max="1" step="0.01" class="orange-highlight" />
        <label>调查利率 survey_rate</label>
        <input name="survey_rate" type="number" step="0.01" />
        <label>开始日期 start_date</label>
        <input name="start_date" type="date" />
        <label>结束日期 end_date</label>
        <input name="end_date" type="date" />
        <button id="submit-btn" type="submit" class="primary-btn">生成</button>
      </form>
    </div>
  </div>

  <script>
    // Simple version marker to confirm cache-busting worked.
    document.getElementById('ui-version').textContent = 'sandbox-ui v1';
    // Surface any silent JS errors.
    window.addEventListener('error', function (e) {
      try {
        console.error('Sandbox UI error:', e.message, e.filename, e.lineno, e.colno);
      } catch (_) {}
    });
  </script>

  <script>
    const form = document.getElementById('param-form');
    const submitBtn = document.getElementById('submit-btn');
    const modelSelect = document.getElementById('model-select');
    const taylorRateEl = document.getElementById('taylor-rate');
    const adjustedRateEl = document.getElementById('adjusted-rate');
    const fedRateEl = document.getElementById('fed-rate');
    const spreadRateEl = document.getElementById('spread-rate');
    const seriesJsonEl = document.getElementById('series-json');
    const formulaTitleEl = document.getElementById('formula-title');
    const formulaBodyEl = document.getElementById('formula-body');
    const lineChartEl = document.getElementById('line-chart');
    const spreadChartEl = document.getElementById('spread-chart');
    const drawer = document.getElementById('drawer');
    const openDrawerBtn = document.getElementById('open-drawer');
    const closeDrawerBtn = document.getElementById('close-drawer');
    let lineChart = null;
    let spreadChart = null;
    let cachedDefaults = null;

    const modelLabels = {
      taylor: '标准泰勒规则',
      extended: '扩展泰勒规则',
      rudebusch: 'Rudebusch',
      mankiw: 'Mankiw',
      evans: 'Evans',
      stone: 'Stone & McCarthy',
    };

    async function loadDefaults(model = 'taylor') {
      const res = await fetch('/api/defaults?model=' + model);
      if (!res.ok) {
        console.error('加载默认参数失败', await res.text());
        return;
      }
      const data = await res.json();
      cachedDefaults = data;
      Object.entries(data).forEach(function ([key, value]) {
        const el = form.elements[key];
        if (!el) return;
        el.value = value;
      });
    }

    function normalizeNumber(key, raw) {
      const val = raw === '' || raw === null || raw === undefined ? NaN : Number(raw);
      if (!Number.isFinite(val)) {
        if (cachedDefaults && cachedDefaults[key] !== undefined) {
          const fallback = Number(cachedDefaults[key]);
          return Number.isFinite(fallback) ? fallback : 0;
        }
        return 0;
      }
      return val;
    }

    function buildPayload() {
      const payload = { model: modelSelect.value };
      for (const el of form.elements) {
        if (!el.name) continue;
        if (el.name === 'start_date' || el.name === 'end_date') {
          payload[el.name] = el.value || null;
        } else {
          payload[el.name] = normalizeNumber(el.name, el.value);
        }
      }
      return payload;
    }

    function renderChart(series) {
      if (!lineChartEl || !spreadChartEl) {
        console.error('Canvas 元素缺失，无法渲染图表');
        return;
      }
      if (!window.Chart) {
        console.error('Chart.js 加载失败，无法渲染图表');
        return;
      }

      const labels = series.map(function (p) { return p.date; });
      const taylor = series.map(function (p) { return p.taylor; });
      const fed = series.map(function (p) { return p.fed; });
      const survey = series.map(function (p) { return p.survey; });
      const spread = series.map(function (p, idx) { return fed[idx] - taylor[idx]; });

      const lineData = {
        labels: labels,
        datasets: [
          {
            label: 'FED利率',
            data: fed,
            borderColor: '#4A90E2',
            backgroundColor: 'rgba(74,144,226,0.2)',
            borderWidth: 2,
            pointRadius: 2,
            tension: 0.1,
          },
          {
            label: '泰勒规则预测',
            data: taylor,
            borderColor: '#FFB347',
            backgroundColor: 'rgba(255,179,71,0.12)',
            borderWidth: 2,
            pointRadius: 2,
            fill: true,
            tension: 0.1,
          },
          {
            label: '经济学家调查',
            data: survey,
            borderColor: '#F5A623',
            backgroundColor: 'rgba(245,166,35,0.12)',
            borderWidth: 2,
            pointRadius: 2,
            borderDash: [6, 4],
            tension: 0.1,
          },
        ],
      };

      const lineOptions = {
        responsive: true,
        maintainAspectRatio: false,
        animation: false,
        interaction: { mode: 'index', intersect: false },
        plugins: {
          legend: { labels: { color: '#ffffff', font: { size: 11 } } },
          tooltip: {
            callbacks: {
              label: function (ctx) {
                return ctx.dataset.label + ': ' + Number(ctx.parsed.y).toFixed(2) + '%';
              },
            },
          },
        },
        scales: {
          x: {
            ticks: {
              color: '#888888',
              maxTicksLimit: 10,
            },
            grid: { display: false },
          },
          y: {
            position: 'right',
            title: { display: true, text: '利率 (%)', color: '#888888', font: { size: 10 } },
            ticks: { color: '#888888' },
            grid: { color: '#3a3a3a', borderDash: [4, 4] },
          },
        },
      };

      if (!lineChart) {
        lineChart = new window.Chart(lineChartEl.getContext('2d'), {
          type: 'line',
          data: lineData,
          options: lineOptions,
        });
      } else {
        lineChart.data = lineData;
        lineChart.options = lineOptions;
        lineChart.update();
      }

      const spreadColors = spread.map(function (v) { return v > 0 ? '#4AE26B' : '#FF6B35'; });
      const spreadData = {
        labels: labels,
        datasets: [
          {
            label: '利差',
            data: spread,
            backgroundColor: spreadColors,
            borderWidth: 0,
          },
        ],
      };

      const spreadOptions = {
        responsive: true,
        maintainAspectRatio: false,
        animation: false,
        plugins: {
          legend: { display: false },
          tooltip: {
            callbacks: {
              label: function (ctx) {
                return '利差: ' + Number(ctx.parsed.y).toFixed(2) + '%';
              },
            },
          },
        },
        scales: {
          x: {
            ticks: {
              color: '#888888',
              maxTicksLimit: 10,
              callback: function (val, idx) {
                return idx % 12 === 0 ? labels[idx].substring(0, 4) : '';
              },
            },
            grid: { display: false },
          },
          y: {
            position: 'right',
            title: { display: true, text: '利差 (%)', color: '#888888', font: { size: 10 } },
            ticks: { color: '#888888' },
            grid: { color: '#3a3a3a', borderDash: [4, 4] },
          },
        },
      };

      if (!spreadChart) {
        spreadChart = new window.Chart(spreadChartEl.getContext('2d'), {
          type: 'bar',
          data: spreadData,
          options: spreadOptions,
        });
      } else {
        spreadChart.data = spreadData;
        spreadChart.options = spreadOptions;
        spreadChart.update();
      }
    }

    function renderFormula(payload, data) {
      const infGap = (payload.core_inflation || 0) - (payload.target_inflation || 0);
      const unempGap = (payload.nairu || 0) - (payload.unemployment_rate || 0);
      const taylor = data.taylor_rate || 0;
      const adjusted = data.adjusted_rate || 0;
      const inertia = payload.rho || 0;
      const prevFed = payload.prev_fed_rate || 0;
      const title = modelLabels[payload.model] || '泰勒规则';
      formulaTitleEl.textContent = title;

      const symbolicLine = [
        '<span class="formula-var">R</span> =',
        '<span class="formula-var">r*</span> +',
        '<span class="formula-var">π</span> +',
        '<span class="formula-var">α</span>(<span class="formula-var">π</span> − <span class="formula-var">π*</span>) +',
        '<span class="formula-var">β</span> × <span class="formula-var">κ</span>(<span class="formula-var">U*</span> − <span class="formula-var">U</span>)',
      ].join(' ');

      const numericLine = [
        '<span class="formula-number">' + taylor.toFixed(2) + '%</span> =',
        '<span class="formula-number">' + payload.real_rate + '</span> +',
        '<span class="formula-highlight">' + payload.core_inflation + '</span> +',
        '<span class="formula-number">' + payload.alpha + '</span>(',
        '<span class="formula-highlight">' + (payload.core_inflation || 0).toFixed(2) + '</span> −',
        '<span class="formula-highlight">' + (payload.target_inflation || 0).toFixed(2) + '</span>) +',
        '<span class="formula-number">' + payload.beta + '</span> ×',
        '<span class="formula-number">' + payload.okun + '</span>(',
        '<span class="formula-number">' + (payload.nairu || 0).toFixed(2) + '</span> −',
        '<span class="formula-number">' + (payload.unemployment_rate || 0).toFixed(2) + '</span>)',
      ].join(' ');

      const adjustedLine = [
        '<span class="formula-var">调整后</span>:',
        '<span class="formula-number">' + adjusted.toFixed(2) + '%</span> =',
        '<span class="formula-number">' + inertia + '</span> ×',
        '<span class="formula-highlight">' + prevFed.toFixed(2) + '</span> +',
        '(1−<span class="formula-number">' + inertia + '</span>) ×',
        '<span class="formula-number">' + taylor.toFixed(2) + '</span>',
      ].join(' ');

      formulaBodyEl.innerHTML =
        '<div style="width:100%;margin-bottom:6px;">' + symbolicLine + '</div>' +
        '<div style="width:100%;margin-bottom:6px;">' + numericLine + '</div>' +
        '<div style="width:100%;font-size:16px;color:#cbd5e1;">' + adjustedLine + '</div>';
    }

    async function runPreview(evt) {
      if (evt) evt.preventDefault();
      submitBtn.disabled = true;
      submitBtn.textContent = '计算中...';
      try {
        const payload = buildPayload();
        const res = await fetch('/api/preview', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        });
        if (!res.ok) {
          const errText = await res.text();
          console.error('预览接口失败', errText);
          throw new Error('请求失败，请检查后端日志或浏览器控制台');
        }
        const data = await res.json();
        taylorRateEl.textContent = data.taylor_rate.toFixed(2) + '%';
        adjustedRateEl.textContent = data.adjusted_rate.toFixed(2) + '%';
        fedRateEl.textContent = (payload.prev_fed_rate || 0).toFixed(2) + '%';
        spreadRateEl.textContent = (data.metrics && data.metrics.spread !== undefined ? data.metrics.spread : 0).toFixed(2) + '%';
        renderChart(data.series);
        renderFormula(payload, data);
        seriesJsonEl.textContent = JSON.stringify(data.series.slice(0, 24), null, 2) + (data.series.length > 24 ? '\\n... (more)' : '');
      } catch (err) {
        alert(err.message || err);
      } finally {
        submitBtn.disabled = false;
        submitBtn.textContent = '生成';
      }
    }

    openDrawerBtn.addEventListener('click', function () { drawer.classList.add('show'); });
    closeDrawerBtn.addEventListener('click', function () { drawer.classList.remove('show'); });
    drawer.addEventListener('click', function (e) { if (e.target === drawer) drawer.classList.remove('show'); });
    form.addEventListener('submit', runPreview);
    modelSelect.addEventListener('change', function (e) { loadDefaults(e.target.value).then(runPreview); });

    loadDefaults(modelSelect.value).then(runPreview);
  </script>
</body>
</html>
'''
