// Shared report rendering helpers for both Toolbox and History Simulation pages.
// Exposes `window.FomcReportRender` with `renderLabor` and `renderCpi`.

(function () {
  const renderMarkdownLite = (text = "") => {
    const escapeHtml = (str) =>
      (str || "").replace(/[&<>"]/g, (ch) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[ch] || ch));

    const renderInline = (escaped) => {
      let s = escaped || "";
      s = s.replace(/`([^`]+?)`/g, "<code>$1</code>");
      s = s.replace(/\[([^\]]+?)\]\((https?:\/\/[^)\s]+)\)/g, '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>');
      s = s.replace(/(^|[\s(])((https?:\/\/)[^\s<]+)/g, '$1<a href="$2" target="_blank" rel="noopener noreferrer">$2</a>');
      s = s.replace(/\*\*([^*]+?)\*\*/g, "<strong>$1</strong>");
      s = s.replace(/(^|[^*])\*([^*]+?)\*(?!\*)/g, "$1<em>$2</em>");
      return s;
    };

    const lines = (text || "").replace(/\r/g, "").split("\n");
    const out = [];
    let inUl = false;
    let inOl = false;
    const closeLists = () => {
      if (inUl) out.push("</ul>");
      if (inOl) out.push("</ol>");
      inUl = false;
      inOl = false;
    };

    for (const raw of lines) {
      const line = raw || "";
      if (!line.trim()) {
        closeLists();
        continue;
      }

      const headingMatch = line.match(/^(#{1,6})\s+(.*)$/);
      if (headingMatch) {
        closeLists();
        const level = Math.min(4, Math.max(2, headingMatch[1].length + 1));
        out.push(`<h${level}>${renderInline(escapeHtml(headingMatch[2]))}</h${level}>`);
        continue;
      }

      const olMatch = line.match(/^\s*\d+\.\s+(.*)$/);
      if (olMatch) {
        if (!inOl) {
          closeLists();
          out.push('<ol class="md-list">');
          inOl = true;
        }
        out.push(`<li>${renderInline(escapeHtml(olMatch[1]))}</li>`);
        continue;
      }

      const ulMatch = line.match(/^\s*-\s+(.*)$/);
      if (ulMatch) {
        if (!inUl) {
          closeLists();
          out.push('<ul class="md-list">');
          inUl = true;
        }
        out.push(`<li>${renderInline(escapeHtml(ulMatch[1]))}</li>`);
        continue;
      }

      closeLists();
      out.push(`<p>${renderInline(escapeHtml(line))}</p>`);
    }
    closeLists();
    return out.join("");
  };

  const themeColors = (() => {
    const styles = getComputedStyle(document.documentElement);
    const fetch = (key, fallback) => (styles.getPropertyValue(key) || "").trim() || fallback;
    return {
      text: fetch("--text", "#cdd6e4"),
      muted: fetch("--muted", "#94a3b8"),
      grid: "rgba(255, 255, 255, 0.08)",
      accent: fetch("--accent", "#38bdf8"),
      accent2: fetch("--accent-2", "#22d3ee"),
    };
  })();

  const summarizeIndicators = (list = []) =>
    list
      .map((item) => {
        const value = item.latest_value ?? item.value ?? "—";
        const units = item.units || "";
        const delta = item.mom_change ? `（环比${item.mom_change}）` : "";
        return `${item.name}: ${value}${units}${delta}`;
      })
      .join(" · ");

  function makeChartFigure(canvas, title) {
    const fig = document.createElement("figure");
    fig.className = "chart-figure";
    const caption = document.createElement("figcaption");
    caption.textContent = title || "";
    const holder = document.createElement("div");
    holder.className = "chart-holder";
    holder.appendChild(canvas);
    fig.appendChild(caption);
    fig.appendChild(holder);
    return fig;
  }

  function insertChartsIntoReport(container, chartMap, titleMap = {}) {
    if (!container || !chartMap) return;
    const used = new Set();
    const headings = Array.from(container.querySelectorAll("h2,h3,h4,h5"));
    headings.forEach((h) => {
      const match = (h.textContent || "").match(/图\s*(\d+)/);
      if (!match) return;
      const idx = match[1];
      const key = `chart${idx}`;
      const chartEl = chartMap[key];
      if (!chartEl) return;
      const fig = makeChartFigure(chartEl, titleMap[idx] || h.textContent || `图${idx}`);
      let anchor = h.nextElementSibling;
      while (anchor && anchor.tagName === "BR") {
        anchor = anchor.nextElementSibling;
      }
      if (anchor && !/^H[1-6]$/.test(anchor.tagName)) {
        anchor.after(fig);
      } else {
        h.after(fig);
      }
      used.add(key);
    });
    Object.keys(chartMap || {}).forEach((key) => {
      if (used.has(key)) return;
      const idx = key.replace("chart", "");
      container.appendChild(makeChartFigure(chartMap[key], titleMap[idx] || `图${idx}`));
    });
  }

  function insertTablesIntoReport(container, tableMap, titleMap = {}) {
    if (!container || !tableMap) return;
    const used = new Set();
    const headings = Array.from(container.querySelectorAll("h2,h3,h4,h5"));

    const nextHeading = (node) => {
      let cur = node?.nextElementSibling;
      while (cur) {
        if (/^H[1-6]$/.test(cur.tagName)) return cur;
        cur = cur.nextElementSibling;
      }
      return null;
    };

    const lastContentBefore = (node, stopNode) => {
      let cur = node?.nextElementSibling;
      let last = null;
      while (cur && cur !== stopNode) {
        if (cur.tagName !== "BR") last = cur;
        cur = cur.nextElementSibling;
      }
      return last;
    };

    headings.forEach((node) => {
      const match = (node.textContent || "").match(/表\s*(\d+)/);
      if (!match) return;
      const idx = match[1];
      const key = `table${idx}`;
      const tableEl = tableMap[key];
      if (!tableEl || used.has(key)) return;
      const titleEl = tableEl.querySelector(".figure-title");
      if (titleEl) titleEl.textContent = titleMap[idx] || titleEl.textContent || `表${idx}`;
      const stopNode = nextHeading(node);
      const last = lastContentBefore(node, stopNode);
      if (last) last.after(tableEl);
      else node.after(tableEl);
      used.add(key);
    });

    Object.keys(tableMap || {}).forEach((key) => {
      if (used.has(key)) return;
      container.appendChild(tableMap[key]);
    });
  }

  const contribCollapseState = { yoy: null, mom: null };

  const renderContribTable = (title, rows = [], mode = "yoy") => {
    const wrapper = document.createElement("div");
    wrapper.className = "contrib-table-wrap";
    const heading = document.createElement("div");
    heading.className = "figure-title";
    heading.textContent = title;
    wrapper.appendChild(heading);

    if (!rows.length) {
      const placeholder = document.createElement("div");
      placeholder.textContent = "暂无数据";
      placeholder.style.color = themeColors.muted;
      wrapper.appendChild(placeholder);
      return wrapper;
    }

    const absMax = (arr, key) => {
      const vals = (arr || [])
        .map((r) => (r[key] === null || r[key] === undefined ? null : Number(r[key])))
        .filter((v) => v !== null && !Number.isNaN(v));
      if (!vals.length) return 0;
      return Math.max(...vals.map((v) => Math.abs(v)));
    };
    const maxChange = absMax(rows, "current");
    const maxContrib = absMax(rows, "contribution");
    const maxDelta = absMax(rows, "delta_contribution");

    const format = (val) => (val === null || val === undefined || Number.isNaN(Number(val)) ? "—" : Number(val).toFixed(2));
    const bar = (val, max) => {
      if (val === null || val === undefined || Number.isNaN(Number(val))) {
        return `<span style="color:${themeColors.muted}">—</span>`;
      }
      const safeMax = max || 1;
      const width = Math.min(100, (Math.abs(Number(val)) / safeMax) * 100);
      const isPos = Number(val) >= 0;
      const align = isPos ? "left:0;" : `left:${100 - width}%;`;
      return `
        <div class="bar-cell">
          <div class="bar-number">${format(val)}</div>
          <div class="bar-track">
            <div class="bar-fill ${isPos ? "" : "neg"}" style="width:${width}%; ${align}"></div>
          </div>
        </div>
      `;
    };
    const heat = (val, max) => {
      if (val === null || val === undefined || Number.isNaN(Number(val))) {
        return `<span style="color:${themeColors.muted}">—</span>`;
      }
      const safeMax = max || 1;
      const intensity = Math.min(1, Math.abs(Number(val)) / safeMax);
      const color =
        Number(val) >= 0
          ? `rgba(249, 115, 22, ${0.35 + 0.4 * intensity})`
          : `rgba(14, 165, 233, ${0.35 + 0.4 * intensity})`;
      return `
        <span class="heat-chip">
          <span class="heat-dot" style="background:${color};"></span>
          <span>${format(val)}</span>
        </span>
      `;
    };

    const nodes = (rows || []).map((r) => ({ ...r, children: [] }));
    const byLabel = new Map();
    nodes.forEach((n) => byLabel.set(n.label, n));
    const roots = [];
    nodes.forEach((n) => {
      const parent = n.parent_label && byLabel.get(n.parent_label);
      if (parent) parent.children.push(n);
      else roots.push(n);
    });

    if (!contribCollapseState[mode]) {
      const initial = new Set();
      nodes.forEach((n) => {
        if (n.children && n.children.length) initial.add(n.label);
      });
      contribCollapseState[mode] = initial;
    }
    const collapsed = contribCollapseState[mode];

    const table = document.createElement("table");
    table.className = "contrib-table";
    table.innerHTML = `
      <thead>
        <tr>
          <th>分项</th>
          <th>权重(%)</th>
          <th>本月(%)</th>
          <th>拉动(ppts)</th>
          <th>上月(%)</th>
          <th>上月拉动(ppts)</th>
          <th>差异(ppts)</th>
        </tr>
      </thead>
    `;
    const tbody = document.createElement("tbody");

    const renderNode = (node, ancestorCollapsed) => {
      if (ancestorCollapsed) return;
      const hasChildren = node.children && node.children.length > 0;
      const isCollapsed = collapsed.has(node.label);
      const indentPx = (node.level || 0) * 14;
      const tr = document.createElement("tr");
      if (node.is_major && node.level === 0) tr.classList.add("major-row");
      const safeLabel = (node.label || "—").replace(/\"/g, "&quot;");
      tr.innerHTML = `
        <td>
          <div style="display:flex; align-items:center; gap:8px; padding-left:${indentPx}px;">
            ${
              hasChildren
                ? `<button class="tree-toggle" data-label="${node.label}" data-mode="${mode}">${isCollapsed ? "▸" : "▾"}</button>`
                : '<span class="tree-leaf"></span>'
            }
            <span class="contrib-label ${node.level === 0 ? "title" : ""}" title="${safeLabel}">${node.label || "—"}</span>
          </div>
        </td>
        <td>${format(node.weight)}</td>
        <td>${bar(node.current, maxChange)}</td>
        <td>${bar(node.contribution, maxContrib)}</td>
        <td>${bar(node.previous, maxChange)}</td>
        <td>${bar(node.previous_contribution, maxContrib)}</td>
        <td>${heat(node.delta_contribution, maxDelta)}</td>
      `;
      tbody.appendChild(tr);
      if (!isCollapsed) {
        (node.children || []).forEach((child) => renderNode(child, false));
      }
    };

    roots.forEach((root) => renderNode(root, false));
    table.appendChild(tbody);
    wrapper.appendChild(table);

    wrapper.querySelectorAll(".tree-toggle").forEach((btn) => {
      btn.addEventListener("click", () => {
        const label = btn.dataset.label;
        const m = btn.dataset.mode;
        const set = contribCollapseState[m] || new Set();
        if (set.has(label)) set.delete(label);
        else set.add(label);
        contribCollapseState[m] = set;
        const fresh = renderContribTable(title, rows, mode);
        wrapper.replaceWith(fresh);
      });
    });

    return wrapper;
  };

  const palette = ["#38bdf8", "#22c55e", "#f59e0b", "#a78bfa", "#ef4444", "#0ea5e9", "#14b8a6", "#f97316", "#ec4899"];

  function createHeadlineChart(data) {
    const payems = data.payems_series || [];
    const unemployment = data.unemployment_series || [];
    if (!payems.length) return null;
    const labels = payems.map((p) => p.date);
    const unempMap = new Map(unemployment.map((u) => [u.date, u.value]));
    const canvas = document.createElement("canvas");
    canvas.height = 260;
    const ctx = canvas.getContext("2d");
    new Chart(ctx, {
      type: "bar",
      data: {
        labels,
        datasets: [
          {
            type: "bar",
            label: "新增非农就业（万人）",
            data: payems.map((p) => p.monthly_change_10k ?? p.value ?? null),
            backgroundColor: "rgba(56, 189, 248, 0.65)",
            borderColor: themeColors.accent,
            borderWidth: 1,
            order: 2,
            yAxisID: "y",
          },
          {
            type: "line",
            label: "失业率(%)",
            data: labels.map((d) => unempMap.get(d) ?? null),
            borderColor: "#f59e0b",
            backgroundColor: "transparent",
            tension: 0.2,
            pointRadius: 3,
            pointHoverRadius: 6,
            pointHitRadius: 10,
            borderWidth: 2,
            order: 1,
            yAxisID: "y1",
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        interaction: { mode: "index", intersect: false },
        scales: {
          x: { ticks: { maxTicksLimit: 8, color: themeColors.muted }, grid: { color: themeColors.grid } },
          y: {
            position: "left",
            ticks: { color: themeColors.muted },
            grid: { color: themeColors.grid },
            title: { display: true, text: "万人", color: themeColors.muted },
          },
          y1: {
            position: "right",
            ticks: { color: themeColors.muted },
            grid: { drawOnChartArea: false },
            title: { display: true, text: "%", color: themeColors.muted },
          },
        },
        plugins: {
          legend: { labels: { color: themeColors.text } },
          tooltip: { mode: "index", intersect: false, backgroundColor: "rgba(8,16,28,0.9)", titleColor: "#fff", bodyColor: "#fff" },
        },
      },
    });
    return canvas;
  }

  function createIndustryChart(contrib) {
    const labels = (contrib.labels || []).slice().reverse();
    if (!labels.length) return null;
    const datasets = (contrib.datasets || []).map((ds, idx) => ({
      label: ds.label || ds.code || `分项${idx + 1}`,
      data: (ds.data || []).slice().reverse(),
      backgroundColor: palette[idx % palette.length],
      stack: "contrib",
      borderWidth: 0,
    }));
    const canvas = document.createElement("canvas");
    canvas.height = 260;
    const ctx = canvas.getContext("2d");
    new Chart(ctx, {
      type: "bar",
      data: { labels, datasets },
      options: {
        indexAxis: "y",
        responsive: true,
        maintainAspectRatio: false,
        interaction: { mode: "index", intersect: false },
        scales: {
          x: { stacked: true, ticks: { color: themeColors.muted }, grid: { color: themeColors.grid }, title: { display: true, text: "贡献率(%)", color: themeColors.muted } },
          y: { stacked: true, ticks: { color: themeColors.muted }, grid: { color: themeColors.grid } },
        },
        plugins: {
          legend: { display: false },
          tooltip: { mode: "index", intersect: false, backgroundColor: "rgba(8,16,28,0.9)", titleColor: "#fff", bodyColor: "#fff" },
        },
      },
    });
    return canvas;
  }

  function createUnemploymentTypesChart(series) {
    if (!series.length) return null;
    const labels = series.map((s) => s.label);
    const prevVals = series.map((s) => s.previous ?? null);
    const currVals = series.map((s) => s.current ?? null);
    const canvas = document.createElement("canvas");
    canvas.height = 240;
    const ctx = canvas.getContext("2d");
    const shared = { categoryPercentage: 0.6, barPercentage: 0.9, maxBarThickness: 34, borderRadius: 6 };
    new Chart(ctx, {
      type: "bar",
      data: {
        labels,
        datasets: [
          { label: "上月", data: prevVals, backgroundColor: "rgba(148, 163, 184, 0.55)", borderColor: "rgba(148, 163, 184, 0.9)", ...shared },
          { label: "本月", data: currVals, backgroundColor: themeColors.accent, borderColor: themeColors.accent, ...shared },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        interaction: { mode: "index", intersect: false },
        scales: {
          x: { stacked: false, ticks: { color: themeColors.muted }, grid: { color: themeColors.grid } },
          y: { stacked: false, ticks: { color: themeColors.muted }, grid: { color: themeColors.grid }, title: { display: true, text: "%", color: themeColors.muted } },
        },
        plugins: {
          legend: { labels: { color: themeColors.text } },
          tooltip: { mode: "index", intersect: false, backgroundColor: "rgba(8,16,28,0.9)", titleColor: "#fff", bodyColor: "#fff" },
        },
      },
    });
    return canvas;
  }

  function createEmploymentParticipationChart(series) {
    if (!series.length) return null;
    const labels = series.map((s) => s.date);
    const empVals = series.map((s) => s.employment_rate ?? null);
    const partVals = series.map((s) => s.participation_rate ?? null);
    const canvas = document.createElement("canvas");
    canvas.height = 240;
    const ctx = canvas.getContext("2d");
    new Chart(ctx, {
      type: "line",
      data: {
        labels,
        datasets: [
          { label: "就业率(%)", data: empVals, borderColor: themeColors.accent, backgroundColor: "rgba(56,189,248,0.10)", tension: 0.22, pointRadius: 0 },
          { label: "劳动参与率(%)", data: partVals, borderColor: "#a78bfa", backgroundColor: "rgba(167,139,250,0.10)", tension: 0.22, pointRadius: 0 },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        interaction: { mode: "index", intersect: false },
        scales: {
          x: { ticks: { maxTicksLimit: 8, color: themeColors.muted }, grid: { color: themeColors.grid } },
          y: { ticks: { color: themeColors.muted }, grid: { color: themeColors.grid }, title: { display: true, text: "%", color: themeColors.muted } },
        },
        plugins: {
          legend: { labels: { color: themeColors.text } },
          tooltip: { mode: "index", intersect: false, backgroundColor: "rgba(8,16,28,0.9)", titleColor: "#fff", bodyColor: "#fff" },
        },
      },
    });
    return canvas;
  }

  function createCpiChart(series, keyMap, yLabel) {
    if (!series.length) return null;
    const labels = series.map((r) => r.date);
    const cpi = series.map((r) => r[keyMap.cpi] ?? null);
    const core = series.map((r) => r[keyMap.core] ?? null);
    const canvas = document.createElement("canvas");
    canvas.height = 240;
    const ctx = canvas.getContext("2d");
    new Chart(ctx, {
      type: "line",
      data: {
        labels,
        datasets: [
          { label: "CPI", data: cpi, borderColor: themeColors.accent, backgroundColor: "rgba(56,189,248,0.10)", tension: 0.22, pointRadius: 0 },
          { label: "核心CPI", data: core, borderColor: "#a78bfa", backgroundColor: "rgba(167,139,250,0.10)", tension: 0.22, pointRadius: 0 },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        interaction: { mode: "index", intersect: false },
        scales: {
          x: { ticks: { maxTicksLimit: 8, color: themeColors.muted }, grid: { color: themeColors.grid } },
          y: { ticks: { color: themeColors.muted }, grid: { color: themeColors.grid }, title: { display: true, text: yLabel || "%", color: themeColors.muted } },
        },
        plugins: {
          legend: { labels: { color: themeColors.text } },
          tooltip: { mode: "index", intersect: false, backgroundColor: "rgba(8,16,28,0.9)", titleColor: "#fff", bodyColor: "#fff" },
        },
      },
    });
    return canvas;
  }

  function buildLaborCharts(data) {
    const charts = {};
    const chart1 = createHeadlineChart(data);
    if (chart1) charts.chart1 = chart1;
    const chart2 = createIndustryChart(data.industry_contribution || {});
    if (chart2) charts.chart2 = chart2;
    const chart3 = createUnemploymentTypesChart(data.unemployment_types_series || []);
    if (chart3) charts.chart3 = chart3;
    const chart4 = createEmploymentParticipationChart(data.employment_participation_series || []);
    if (chart4) charts.chart4 = chart4;
    return charts;
  }

  function buildCpiCharts(data) {
    const charts = {};
    const chart1 = createCpiChart(data.yoy_series || [], { cpi: "cpi_yoy", core: "core_yoy" }, "同比(%)");
    if (chart1) charts.chart1 = chart1;
    const chart2 = createCpiChart(data.mom_series || [], { cpi: "cpi_mom", core: "core_mom" }, "环比(%)");
    if (chart2) charts.chart2 = chart2;
    return charts;
  }

  function buildLaborFallbackText(data) {
    const industry = data?.industry_contribution?.latest_period
      ? `${data.industry_contribution.latest_period} 分行业贡献率`
      : "分行业贡献率数据";
    const industryLine = data?.industry_contribution?.error ? data.industry_contribution.error : industry;
    return [
      "## 图1：新增非农就业与失业率",
      data.chart_commentary || "基于 PAYEMS 与 UNRATE 的近三年窗口走势。",
      "## 图2：分行业新增非农就业贡献率",
      industryLine,
      "## 图3：各类型失业率对比",
      "展示 U1~U6 当月值与上月对比。",
      "## 图4：就业率与劳动参与率",
      "近24个月就业率与劳动参与率的并行走势。",
    ].join("\n");
  }

  function buildCpiFallbackText(data) {
    return [
      "## 图1：美国CPI、核心CPI当月同比",
      data.chart_commentary || "展示近期 CPI/核心CPI 同比走势。",
      "## 图2：CPI、核心CPI季调环比",
      "展示近期 CPI/核心CPI 环比变化。",
      "## 表1：当月CPI同比拉动拆分",
      "分项权重、本月同比与拉动对比上月的差异。",
      "## 表2：当月季调CPI分项环比结构",
      "展示本月季调环比、拉动贡献以及与上月的差异。",
    ].join("\n");
  }

  const laborTitles = {
    1: "图1：新增非农就业（万人）及失业率(%，右)",
    2: "图2：分行业新增非农就业贡献率(%)",
    3: "图3：各类型失业率(%)",
    4: "图4：就业率和劳动参与率(%)",
  };
  const cpiTitles = {
    1: "图1：美国CPI、核心CPI当月同比(%)",
    2: "图2：CPI、核心CPI季调环比(%)",
  };
  const cpiTableTitles = {
    1: "表1：当月CPI同比拉动拆分",
    2: "表2：当月季调CPI分项环比结构",
  };

  function renderLabor(container, data) {
    const insight = summarizeIndicators(data.indicators || []);
    const markdown = data.report_text || buildLaborFallbackText(data);
    const reportHtml = renderMarkdownLite(markdown);
    container.innerHTML = `
      <div class="report-shell">
        <div class="card wide-card report-card">
          <div class="title">结论｜${data.headline_summary || "缺少数据"}</div>
          <div class="muted">窗口 ${data.chart_window?.start_date || ""} → ${data.chart_window?.end_date || ""}</div>
          <div class="summary-card">
            <div class="pill-inline">指标快照：${insight || "暂无数据"}</div>
            <p class="muted">${data.chart_commentary || data.llm_error || ""}</p>
          </div>
          <div class="report-body" id="labor-report-body">${reportHtml}</div>
        </div>
      </div>
    `;
    insertChartsIntoReport(container.querySelector("#labor-report-body"), buildLaborCharts(data), laborTitles);
  }

  function renderCpi(container, data) {
    const insight = summarizeIndicators(data.indicators || []);
    const markdown = data.report_text || buildCpiFallbackText(data);
    const reportHtml = renderMarkdownLite(markdown);
    contribCollapseState.yoy = null;
    contribCollapseState.mom = null;
    const tables = {
      table1: renderContribTable(cpiTableTitles[1], data.contributions_yoy || [], "yoy"),
      table2: renderContribTable(cpiTableTitles[2], data.contributions_mom || [], "mom"),
    };

    container.innerHTML = `
      <div class="report-shell">
        <div class="card wide-card report-card">
          <div class="title">结论｜${data.headline_summary || "缺少数据"}</div>
          <div class="pill-inline">指标快照：${insight || "暂无数据"}</div>
          <div class="muted">${data.chart_commentary || data.llm_error || ""}</div>
          <div class="report-body" id="cpi-report-body">${reportHtml}</div>
        </div>
      </div>
    `;
    const cpiContainer = container.querySelector("#cpi-report-body");
    insertChartsIntoReport(cpiContainer, buildCpiCharts(data), cpiTitles);
    insertTablesIntoReport(cpiContainer, tables, cpiTableTitles);
  }

  window.FomcReportRender = {
    renderMarkdownLite,
    renderLabor,
    renderCpi,
  };
})();

